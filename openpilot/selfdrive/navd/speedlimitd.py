# openpilot/selfdrive/navd/speedlimitd.py

"""Publishes the posted speed limit and the cruise target derived from it.

Matches GPS position against the offline map at 5 Hz and publishes a small
JSON blob on customReservedRawData1:

  {"valid": true, "limit_mph": 45, "target_kph": 88.5, "freeway": false,
   "road": "Washtenaw Avenue", "explicit": true}

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

  def update(self, lat, lon, bearing):
    match = self.map.match(lat, lon, bearing)
    new_way = match.way_idx if match is not None else None

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
    limit = self.map.speed_limit_mph(self.way_idx)
    freeway = self.map.is_freeway(self.way_idx)
    return {
      "valid": True,
      "limit_mph": limit,
      "target_kph": cruise_target_kph(limit, freeway),
      "freeway": freeway,
      "road": self.map.road_name(self.way_idx),
      "explicit": bool(self.map.ways[self.way_idx]["x"]),
    }


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
      payload = tracker.update(fix.latitude, fix.longitude, bearing)

    if rk.frame % RATE == 0:
      auto_experimental = params.get_bool("AutoExperimentalMode")
    switched = switcher.update(payload, auto_experimental)
    if switched is not None:
      cloudlog.info(f"speedlimitd: {'experimental' if switched else 'chill'} mode on {payload.get('road') or 'unnamed road'}")

    msg = messaging.new_message("customReservedRawData1", valid=True)
    msg.customReservedRawData1 = json.dumps(payload, separators=(",", ":")).encode()
    pm.send("customReservedRawData1", msg)
    rk.keep_time()


if __name__ == "__main__":
  main()
