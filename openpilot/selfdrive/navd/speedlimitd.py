# openpilot/selfdrive/navd/speedlimitd.py

"""Publishes the posted speed limit and the cruise target derived from it.

Matches GPS position against the offline map at 5 Hz and publishes a small
JSON blob on customReservedRawData1:

  {"valid": true, "limit_mph": 45, "target_kph": 88.5, "freeway": false,
   "road": "Washtenaw Avenue", "explicit": true, "school_zone": false,
   "curve_speed_kph": 62.3, "limit_ahead_kph": 70.2, "bump_speed_kph": 33.0}

curve_speed_kph is the map-based curve speed cap from curve_speed.py, present only
while moving with a valid bearing and a bend somewhere in the look-ahead.
limit_ahead_kph is the pre-slow cap from limit_ahead.py, present only while a road
with a lower cruise target is coming up in the look-ahead; it brings the car down
to the new target by the time it reaches the sign. bump_speed_kph is the speed bump
cap from bump_speed.py, present only while a mapped bump is within its look-ahead. The
longitudinal planner takes the minimum of all of them and the set speed.

limit_mph is the limit in force right now: a school zone's conditional limit during
its hours (school_zone true), the ordinary posted limit otherwise. Conditional
limits are evaluated at the map's own local time, see conditional_limit.py.

target = limit + LOCAL_OFFSET_MPH on ordinary roads, limit + FREEWAY_OFFSET_MPH
on motorways and trunks. card.py applies the target as the set speed when the
SpeedLimitCruise toggle is on. Nothing here talks to the network; the map is a
file in this repo.

A road change has to be seen on two consecutive matches before it is published,
so parallel roads and overpasses do not make the limit flicker.

When the AutoExperimentalMode param is on, the same road classification also
drives the ExperimentalMode param: Experimental on local roads (so the car stops
for lights and signs), chill on freeways. selfdrived re-reads that param about
once a second.
"""

import json

from openpilot.cereal import messaging
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navd.offline_map import OfflineMap
from openpilot.selfdrive.navd.curve_speed import lookahead, curve_speed, CurveSpeedFilter
from openpilot.selfdrive.navd.curve_speed import LOOKAHEAD_M as CURVE_LOOKAHEAD_M
from openpilot.selfdrive.navd.limit_ahead import limit_ahead_speed, LOOKAHEAD_M as LIMIT_LOOKAHEAD_M
from openpilot.selfdrive.navd.bump_speed import bump_speed, LOOKAHEAD_M as BUMP_LOOKAHEAD_M

RATE = 5
LOCAL_OFFSET_MPH = 10
FREEWAY_OFFSET_MPH = 20
# GPS fixes older than this are ignored
MAX_FIX_AGE_S = 2.0
# use the reported GPS bearing only when moving faster than this, m/s
MIN_BEARING_SPEED = 2.0


def cruise_target_kph(limit_mph, freeway):
  offset = FREEWAY_OFFSET_MPH if freeway else LOCAL_OFFSET_MPH
  # round to a tenth like the manual imperial increment so the HUD shows a whole mph
  return round((limit_mph + offset) * CV.MPH_TO_KPH, 1)


class SpeedLimitTracker:
  """Debounces road changes and turns a map match into the published payload."""

  def __init__(self, offline_map):
    self.map = offline_map
    self.way_idx = None
    self.pending_way = None
    self.curve_filter = CurveSpeedFilter(1.0 / RATE)
    self.curve_speed_ms = None
    self.limit_filter = CurveSpeedFilter(1.0 / RATE)
    self.limit_ahead_ms = None
    self.bump_filter = CurveSpeedFilter(1.0 / RATE)
    self.bump_speed_ms = None
    self.now = None

  def target_ms(self, way_idx, when=None):
    """Cruise target (m/s) the speed limit cruise would set on a way, at time `when`."""
    limit = self.map.speed_limit_mph(way_idx, when)
    return cruise_target_kph(limit, self.map.is_freeway(way_idx)) * CV.KPH_TO_MS

  def update(self, lat, lon, bearing, personality=1, now=None):
    self.now = now if now is not None else self.map.local_now()
    match = self.map.match(lat, lon, bearing)
    new_way = match.way_idx if match is not None else None

    # curve speed and the limit look-ahead need the travel direction, so only when moving with a bearing
    v_curve = None
    v_limit = None
    v_bump = None
    if match is not None and bearing is not None:
      pts, ways_ahead, nodes_ahead = lookahead(self.map, match, max(CURVE_LOOKAHEAD_M, LIMIT_LOOKAHEAD_M, BUMP_LOOKAHEAD_M))
      v_bump = bump_speed(nodes_ahead, self.map.calming_at)
      # one walk serves both: curve speed sees the geometry out to its own horizon (including
      # the point that crosses it, as before), the limit look-ahead sees the ways out to its
      cut = next((i for i, p in enumerate(pts) if p[2] >= CURVE_LOOKAHEAD_M), len(pts) - 1)
      v_curve = curve_speed(pts[:cut + 1], personality)
      ways_ahead = [(wi, d) for wi, d in ways_ahead if d <= LIMIT_LOOKAHEAD_M]
      # drops are measured against the road the car is matched to right now. For the one
      # frame between crossing onto the slower road and the debounce accepting it, the cap
      # simply vanishes; that is harmless, and a glitchy match can never yank the speed down.
      v_limit = limit_ahead_speed(ways_ahead, self.target_ms(match.way_idx, self.now), self.target_ms, self.now)
    self.curve_speed_ms = self.curve_filter.update(v_curve)
    self.limit_ahead_ms = self.limit_filter.update(v_limit)
    self.bump_speed_ms = self.bump_filter.update(v_bump)

    if new_way == self.way_idx:
      self.pending_way = None
    elif new_way == self.pending_way:
      # second consecutive sighting, accept the change
      self.way_idx = new_way
      self.pending_way = None
    else:
      self.pending_way = new_way

    return self.payload()

  def payload(self):
    if self.way_idx is None:
      return {"valid": False}
    limit = self.map.speed_limit_mph(self.way_idx, self.now)
    freeway = self.map.is_freeway(self.way_idx)
    p = {
      "valid": True,
      "limit_mph": limit,
      "target_kph": cruise_target_kph(limit, freeway),
      "freeway": freeway,
      "road": self.map.road_name(self.way_idx),
      "explicit": bool(self.map.ways[self.way_idx]["x"]),
      "school_zone": limit != self.map.speed_limit_mph(self.way_idx),
    }
    if self.curve_speed_ms is not None:
      p["curve_speed_kph"] = round(self.curve_speed_ms * CV.MS_TO_KPH, 1)
    if self.limit_ahead_ms is not None:
      p["limit_ahead_kph"] = round(self.limit_ahead_ms * CV.MS_TO_KPH, 1)
    if self.bump_speed_ms is not None:
      p["bump_speed_kph"] = round(self.bump_speed_ms * CV.MS_TO_KPH, 1)
    return p


class ExperimentalModeSwitcher:
  """Picks Experimental mode on local roads and chill mode on freeways.

  Only acts on a change of road type, so a manual toggle on the screen sticks until
  the next local/freeway transition. Nothing is written while the car is off the
  map, or while the AutoExperimentalMode param is off.
  """

  def __init__(self, params):
    self.params = params
    self.last_applied = None

  def update(self, payload, enabled):
    """Returns the mode that was just written (True = experimental), or None if nothing changed."""
    if not enabled or not payload.get("valid"):
      return None
    desired = not payload["freeway"]
    if desired == self.last_applied:
      return None
    self.last_applied = desired
    self.params.put_bool("ExperimentalMode", desired)
    return desired


def latest_fix(sm):
  """Most recent GPS fix from either receiver, or None."""
  best = None
  for svc in ("gpsLocation", "gpsLocationExternal"):
    if sm.recv_frame[svc] == 0 or not sm.alive[svc]:
      continue
    g = sm[svc]
    if not g.hasFix:
      continue
    if best is None or sm.logMonoTime[svc] > best[0]:
      best = (sm.logMonoTime[svc], g)
  return None if best is None else best[1]


def main():
  cloudlog.info("speedlimitd loading map")
  tracker = SpeedLimitTracker(OfflineMap())
  cloudlog.info("speedlimitd map loaded")

  params = Params()
  switcher = ExperimentalModeSwitcher(params)
  auto_experimental = params.get_bool("AutoExperimentalMode")
  personality = int(params.get("LongitudinalPersonality") or 1)

  sm = messaging.SubMaster(["gpsLocation", "gpsLocationExternal"])
  pm = messaging.PubMaster(["customReservedRawData1"])
  rk = Ratekeeper(RATE)

  while True:
    sm.update(0)
    fix = latest_fix(sm)
    if fix is None:
      payload = {"valid": False}
    else:
      bearing = fix.bearingDeg if fix.speed > MIN_BEARING_SPEED else None
      payload = tracker.update(fix.latitude, fix.longitude, bearing, personality)

    if rk.frame % RATE == 0:
      auto_experimental = params.get_bool("AutoExperimentalMode")
      personality = int(params.get("LongitudinalPersonality") or 1)
    switched = switcher.update(payload, auto_experimental)
    if switched is not None:
      cloudlog.info(f"speedlimitd: {'experimental' if switched else 'chill'} mode on {payload.get('road') or 'unnamed road'}")

    msg = messaging.new_message("customReservedRawData1", valid=True)
    msg.customReservedRawData1 = json.dumps(payload, separators=(",", ":")).encode()
    pm.send("customReservedRawData1", msg)
    rk.keep_time()


if __name__ == "__main__":
  main()
