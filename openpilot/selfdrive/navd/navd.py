# openpilot/selfdrive/navd/navd.py

"""Fully offline turn-by-turn navigation on the bundled Ann Arbor / Ypsilanti map.

Destinations come from params written by the UI:
  NavDestination  {"lat": .., "lon": .., "name": "Home"}   active target, cleared on arrival
  NavHome / NavWork  same shape, saved places the UI offers as one-press destinations

With no destination set, the start of a drive near Home routes to Work and near Work
routes to Home (auto_destination.py). That guess is dropped, not re-routed, when the
car leaves its route.

Every cycle (2 Hz) navd reads the GPS fix, keeps the car located along the
current route, re-routes when the car has left it, and publishes a JSON status
on customReservedRawData2 for the HUD banner:

  {"active": true, "status": "routing", "dest": "Home",
   "maneuver": "turn", "modifier": "left", "street": "Packard Street",
   "distance_m": 230.0, "remaining_m": 5400.0, "eta_s": 480.0,
   "next": {"maneuver": "arrive", "modifier": "", "street": "", "distance_m": 900.0},
   "turn_speed_kph": 58.3}

status is one of: idle, no_gps, routing, off_route, no_route, arrived.

turn_speed_kph is the speed cap from turn_speed.py for the maneuvers ahead, present
only while routing with a corner within reach; the longitudinal planner takes the
minimum of it and the set speed so the car arrives at the turn already slowed down.
Turn it off with the NavTurnSlowdown param.
No network access anywhere: the map is a file in this repo.
"""

import json
import math
import time

from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navd.offline_map import OfflineMap, haversine
from openpilot.selfdrive.navd.router import find_route, snap
from openpilot.selfdrive.navd.speedlimitd import latest_fix, MIN_BEARING_SPEED
from openpilot.selfdrive.navd.curve_speed import CurveSpeedFilter
from openpilot.selfdrive.navd.turn_speed import turn_speed
from openpilot.selfdrive.navd.auto_destination import auto_destination, WINDOW_S

RATE = 2
OFF_ROUTE_DIST = 40.0      # m from the route polyline before the car counts as off route
OFF_ROUTE_TIME = 4.0       # s continuously off route before re-routing
REROUTE_COOLDOWN = 10.0    # s between routing attempts
ARRIVE_DIST = 30.0         # m from the destination that counts as arrived
ARRIVED_SHOW_TIME = 15.0   # s the arrived banner stays up
SEARCH_AHEAD = 40          # route nodes scanned ahead of the last known position
MANEUVER_PASSED_M = 12.0   # a maneuver this far behind the car is considered done


def load_place(params, key):
  raw = params.get(key)
  if not raw:
    return None
  try:
    place = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return {"lat": float(place["lat"]), "lon": float(place["lon"]), "name": str(place.get("name", key))}
  except (ValueError, TypeError, KeyError):
    return None


class RouteTracker:
  """Locates the car along a Route and reports the next maneuvers."""

  def __init__(self, offline_map, route):
    self.map = offline_map
    self.route = route
    self.xs = [c[0] for c in route.coords]
    self.ys = [c[1] for c in route.coords]
    self.seg = 0
    self.dist_along = 0.0
    self.off_route_dist = 0.0

  def update(self, lat, lon):
    """Project the car onto the route near the last known segment. Returns distance off route in metres."""
    px, py = self.map.to_xy(lat, lon)
    best = None
    lo = max(0, self.seg - 2)
    hi = min(len(self.xs) - 1, self.seg + SEARCH_AHEAD)
    for i in range(lo, hi):
      ax, ay, bx, by = self.xs[i], self.ys[i], self.xs[i + 1], self.ys[i + 1]
      dx, dy = bx - ax, by - ay
      l2 = dx * dx + dy * dy
      t = 0.0 if l2 == 0 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / l2))
      d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
      if best is None or d < best[0]:
        best = (d, i, t)
    if best is None:
      return float("inf")
    d, i, t = best
    self.seg = i
    seg_len = self.route.cum_dist[i + 1] - self.route.cum_dist[i]
    self.dist_along = self.route.cum_dist[i] + t * seg_len
    self.off_route_dist = d
    return d

  def remaining_m(self):
    return max(0.0, self.route.total_dist - self.dist_along)

  def eta_s(self):
    cd, ct = self.route.cum_dist, self.route.cum_time
    i = self.seg
    seg_len = cd[i + 1] - cd[i]
    frac = 0.0 if seg_len <= 0 else (self.dist_along - cd[i]) / seg_len
    time_here = ct[i] + frac * (ct[i + 1] - ct[i])
    return max(0.0, self.route.total_time - time_here)

  def upcoming(self):
    """Instructions not yet passed, nearest first."""
    return [ins for ins in self.route.instructions if ins["dist"] - self.dist_along > -MANEUVER_PASSED_M]


class Navigator:
  def __init__(self, offline_map, params):
    self.map = offline_map
    self.params = params
    self.dest = None
    self.route = None
    self.tracker = None
    self.status = "idle"
    self.off_route_since = None
    self.last_route_attempt = 0.0
    self.arrived_at = None
    self.turn_slowdown = True
    self.turn_filter = CurveSpeedFilter(1.0 / RATE)
    # zero-tap Home/Work guess: once per drive, only in the first WINDOW_S after GPS comes up
    self.auto_home_work = True
    self.auto_decided = False
    self.first_fix_t = None
    self.auto_latlon = None
    self.is_auto = False

  def _clear(self, status="idle"):
    self.route = None
    self.tracker = None
    self.off_route_since = None
    self.status = status

  def _plan(self, fix, now):
    self.last_route_attempt = now
    bearing = fix.bearingDeg if fix.speed > MIN_BEARING_SPEED else None
    start = snap(self.map, fix.latitude, fix.longitude, bearing)
    goal = snap(self.map, self.dest["lat"], self.dest["lon"])
    if start is None or goal is None:
      cloudlog.warning("navd: start or destination is off the map")
      self._clear("no_route")
      return
    route = find_route(self.map, start[0], goal[0], self.map.to_xy(fix.latitude, fix.longitude), start[1])
    if route is None or not route.ways:
      cloudlog.warning(f"navd: no route from {fix.latitude:.5f},{fix.longitude:.5f} to {self.dest['name']}")
      self._clear("no_route")
      return
    self.route = route
    self.tracker = RouteTracker(self.map, route)
    self.off_route_since = None
    self.status = "routing"
    cloudlog.info(f"navd: routed to {self.dest['name']}: {route.total_dist / 1609.34:.1f} mi, {route.total_time / 60:.0f} min")

  def _guess_destination(self, fix, now):
    """Writes NavDestination from the Home/Work geofence if this drive still allows a guess."""
    if now - self.first_fix_t > WINDOW_S:
      self.auto_decided = True
      return None
    guess = auto_destination(fix.latitude, fix.longitude, load_place(self.params, "NavHome"), load_place(self.params, "NavWork"))
    if guess is None:
      return None
    self.params.put("NavDestination", guess)
    self.auto_decided = True
    self.auto_latlon = (guess["lat"], guess["lon"])
    cloudlog.info(f"navd: starting near {'Home' if guess['name'] == 'Work' else 'Work'}, guessing {guess['name']}")
    return guess

  def update(self, fix, now):
    if fix is not None and self.first_fix_t is None:
      self.first_fix_t = now
    dest = load_place(self.params, "NavDestination")
    if dest is None and fix is not None and self.auto_home_work and not self.auto_decided:
      dest = self._guess_destination(fix, now)

    if dest is None:
      if self.arrived_at is not None and now - self.arrived_at < ARRIVED_SHOW_TIME:
        return self.payload()
      self.arrived_at = None
      self.dest = None
      if self.status != "idle":
        self._clear("idle")
      return self.payload()

    if self.dest is None or (dest["lat"], dest["lon"]) != (self.dest["lat"], self.dest["lon"]):
      self.dest = dest
      self.is_auto = self.auto_latlon is not None and (dest["lat"], dest["lon"]) == self.auto_latlon
      self._clear("routing")
      self.arrived_at = None

    if fix is None:
      self.status = "no_gps"
      return self.payload()

    if haversine(fix.latitude, fix.longitude, self.dest["lat"], self.dest["lon"]) < ARRIVE_DIST:
      cloudlog.info(f"navd: arrived at {self.dest['name']}")
      self.params.remove("NavDestination")
      self.arrived_at = now
      self._clear("arrived")
      return self.payload()

    if self.route is None:
      if now - self.last_route_attempt >= REROUTE_COOLDOWN or self.status == "routing":
        self._plan(fix, now)
      return self.payload()

    off = self.tracker.update(fix.latitude, fix.longitude)
    if off <= OFF_ROUTE_DIST and self.tracker.remaining_m() < ARRIVE_DIST:
      # destination snapped to a road node the car has now reached
      cloudlog.info(f"navd: arrived at {self.dest['name']} (end of route)")
      self.params.remove("NavDestination")
      self.arrived_at = now
      self._clear("arrived")
      return self.payload()
    if off > OFF_ROUTE_DIST:
      if self.off_route_since is None:
        self.off_route_since = now
      elif now - self.off_route_since > OFF_ROUTE_TIME:
        if self.is_auto:
          # the guess was wrong (or the driver is going somewhere else): give up rather than nag
          cloudlog.info(f"navd: left the guessed route to {self.dest['name']}, giving up navigation")
          self.params.remove("NavDestination")
          self.is_auto = False
          self._clear("idle")
          return self.payload()
        self.status = "off_route"
        if now - self.last_route_attempt >= REROUTE_COOLDOWN:
          self._plan(fix, now)
    else:
      self.off_route_since = None
      self.status = "routing"
    return self.payload()

  def payload(self):
    routing = self.tracker is not None and self.status == "routing" and self.dest is not None
    # the filter lets the cap drop at once but rise only slowly, so the throttle does not surge after a turn
    v_turn = turn_speed(self.tracker.upcoming(), self.tracker.dist_along) if routing and self.turn_slowdown else None
    v_turn = self.turn_filter.update(v_turn)

    if self.status == "arrived":
      return {"active": True, "status": "arrived", "dest": self.dest["name"] if self.dest else ""}
    if self.dest is None or self.status == "idle":
      return {"active": False, "status": "idle"}
    p = {"active": True, "status": self.status, "dest": self.dest["name"]}
    if v_turn is not None:
      p["turn_speed_kph"] = round(v_turn * 3.6, 1)
    if self.tracker is not None:
      ups = self.tracker.upcoming()
      p["remaining_m"] = self.tracker.remaining_m()
      p["eta_s"] = self.tracker.eta_s()
      if ups:
        cur = ups[0]
        p["maneuver"] = cur["type"]
        p["modifier"] = cur["modifier"]
        p["street"] = cur["street"]
        p["distance_m"] = max(0.0, cur["dist"] - self.tracker.dist_along)
        if len(ups) > 1:
          nxt = ups[1]
          p["next"] = {"maneuver": nxt["type"], "modifier": nxt["modifier"], "street": nxt["street"],
                       "distance_m": max(0.0, nxt["dist"] - self.tracker.dist_along)}
    return p


def main():
  cloudlog.info("navd loading map")
  offline_map = OfflineMap()
  offline_map.adjacency()
  cloudlog.info("navd map loaded")

  params = Params()
  nav = Navigator(offline_map, params)
  sm = messaging.SubMaster(["gpsLocation", "gpsLocationExternal"])
  pm = messaging.PubMaster(["customReservedRawData2"])
  rk = Ratekeeper(RATE)

  while True:
    sm.update(0)
    if rk.frame % RATE == 0:
      nav.turn_slowdown = params.get_bool("NavTurnSlowdown")
      nav.auto_home_work = params.get_bool("NavAutoHomeWork")
    payload = nav.update(latest_fix(sm), time.monotonic())
    msg = messaging.new_message("customReservedRawData2", valid=True)
    msg.customReservedRawData2 = json.dumps(payload, separators=(",", ":")).encode()
    pm.send("customReservedRawData2", msg)
    rk.keep_time()


if __name__ == "__main__":
  main()
