# openpilot/system/loggerd/incidentd.py

"""Automatic incident preservation for the dashcam.

Watches vehicle and sensor state while onroad and publishes a userBookmark
whenever something that looks like an incident happens. loggerd already
preserves the current segment (and marks the route for upload) on every
userBookmark, and deleter keeps preserved segments plus the two before them,
so this daemon needs no changes to the logging pipeline itself.

Triggers:
  * hard braking: sustained longitudinal deceleration from carState
  * impact: large deviation of the device accelerometer from gravity
  * safety events: forward collision warning or AEB in onroadEvents
  * panda loss: pandaStates stops arriving while onroad, which usually
    means the harness or power was disrupted
"""

from openpilot.cereal import log, messaging
from openpilot.common.swaglog import cloudlog

EventName = log.OnroadEvent.EventName

# longitudinal deceleration considered a hard brake, m/s^2 (~0.45 g).
# comfortable braking is around -2.5, so this is well above normal traffic.
HARD_BRAKE_ACCEL = -4.5
# ignore hard braking below this speed, m/s, to skip parking taps and ACC creep
HARD_BRAKE_MIN_SPEED = 5.0
# carState is 100 Hz, so this is ~50 ms of sustained deceleration
HARD_BRAKE_FRAMES = 5

# deviation of accelerometer magnitude from gravity treated as an impact, m/s^2.
# because gravity adds in quadrature, a purely horizontal hit needs ~33 m/s^2
# (~3.4 g) to trip this; potholes and curb hits on the comma mount read below that.
IMPACT_ACCEL = 25.0
GRAVITY = 9.81

SAFETY_EVENTS = (EventName.fcw, EventName.aeb)

# seconds between bookmarks; loggerd dedupes per segment anyway, this just
# keeps the log and alert quiet during a long event
COOLDOWN = 10.0


class IncidentDetector:
  """Pure trigger logic so it can be unit tested without messaging."""

  def __init__(self):
    self.hard_brake_frames = 0
    self.panda_seen = False
    self.last_trigger_t = None

  def _cooldown_ok(self, t):
    return self.last_trigger_t is None or (t - self.last_trigger_t) >= COOLDOWN

  def check_hard_brake(self, a_ego, v_ego):
    if a_ego <= HARD_BRAKE_ACCEL and v_ego >= HARD_BRAKE_MIN_SPEED:
      self.hard_brake_frames += 1
    else:
      self.hard_brake_frames = 0
    return self.hard_brake_frames >= HARD_BRAKE_FRAMES

  def check_impact(self, accel_v):
    if len(accel_v) < 3:
      return False
    mag = (accel_v[0] ** 2 + accel_v[1] ** 2 + accel_v[2] ** 2) ** 0.5
    return abs(mag - GRAVITY) >= IMPACT_ACCEL

  def check_safety_events(self, event_names):
    return any(name in SAFETY_EVENTS for name in event_names)

  def check_panda_loss(self, panda_alive):
    # only a transition from alive to dead counts, so startup before pandad
    # publishes does not trigger
    if panda_alive:
      self.panda_seen = True
      return False
    return self.panda_seen

  def update(self, t, a_ego=None, v_ego=None, accel_v=None, event_names=(), panda_alive=None):
    """Returns the trigger reason as a string, or None.

    Every check runs so per-trigger state (frame counters, panda seen) stays
    current even while in cooldown.
    """
    reasons = []
    if a_ego is not None and self.check_hard_brake(a_ego, v_ego):
      reasons.append("hard brake")
    if accel_v is not None and self.check_impact(accel_v):
      reasons.append("impact")
    if self.check_safety_events(event_names):
      reasons.append("safety event")
    if panda_alive is not None and self.check_panda_loss(panda_alive):
      reasons.append("panda loss")

    if not reasons or not self._cooldown_ok(t):
      return None
    self.last_trigger_t = t
    return ", ".join(reasons)


def main():
  detector = IncidentDetector()
  sm = messaging.SubMaster(['carState', 'accelerometer', 'onroadEvents', 'pandaStates'])
  pm = messaging.PubMaster(['userBookmark'])

  while True:
    sm.update(100)
    t = sm.logMonoTime['carState'] * 1e-9 if sm.recv_frame['carState'] > 0 else 0.0

    kwargs = {}
    if sm.updated['carState']:
      kwargs['a_ego'] = sm['carState'].aEgo
      kwargs['v_ego'] = sm['carState'].vEgo
    if sm.updated['accelerometer']:
      accel = sm['accelerometer']
      if accel.which() == 'acceleration':
        kwargs['accel_v'] = list(accel.acceleration.v)
    if sm.updated['onroadEvents']:
      kwargs['event_names'] = [e.name for e in sm['onroadEvents']]
    if sm.recv_frame['pandaStates'] > 0:
      kwargs['panda_alive'] = sm.alive['pandaStates']

    reason = detector.update(t, **kwargs)
    if reason is not None:
      cloudlog.event("incidentd.preserve", reason=reason, error=True)
      pm.send('userBookmark', messaging.new_message('userBookmark', valid=True))


if __name__ == "__main__":
  main()
