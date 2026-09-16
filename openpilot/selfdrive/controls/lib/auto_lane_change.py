# openpilot/selfdrive/controls/lib/auto_lane_change.py

"""Nudgeless lane change on freeways.

Upstream openpilot waits in preLaneChange until the driver nudges the wheel toward
the signalled side. On a freeway that nudge is pure ceremony, so here the car starts
the lane change on its own once the blinker has been on for AUTO_START_DELAY. The
freeway classification comes from speedlimitd's offline map payload, the same one
that picks the cruise offset and Experimental mode, so in town (or off the map) the
nudge is still required.

The car has to be in preLaneChange already, which means the blinker came on while
lateral control was active and the car is above the lane change minimum speed, and
the blind spot check in DesireHelper still applies for cars that report one. The
2021 Corolla LE has no blind spot monitor, so there the driver is the blind spot
monitor: check the mirror before signalling, and cancel the signal to abort.
Turn it off with the NudgelessLaneChange param.
"""

import json

from openpilot.common.realtime import DT_MDL

AUTO_START_DELAY = 1.0  # s the blinker has to be on before the car moves over


def freeway_from_payload(raw):
  """True when speedlimitd currently matches a freeway or trunk road."""
  try:
    payload = json.loads(bytes(raw))
  except (ValueError, TypeError):
    return False
  return bool(payload.get("valid")) and bool(payload.get("freeway"))


class AutoLaneChange:
  """Counts how long the car has waited in preLaneChange on a freeway."""

  def __init__(self, dt=DT_MDL):
    self.dt = dt
    self.timer = 0.0

  def update(self, pre_lane_change, freeway, enabled):
    """True when the lane change may start without a steering nudge."""
    if not (enabled and freeway and pre_lane_change):
      self.timer = 0.0
      return False
    self.timer += self.dt
    return self.timer >= AUTO_START_DELAY
