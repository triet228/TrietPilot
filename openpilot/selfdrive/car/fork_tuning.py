# openpilot/selfdrive/car/fork_tuning.py

"""Per-car values for the fork's own longitudinal behaviour.

Everything TrietPilot adds on top of openpilot's planner and controller reads its
constants from here, keyed by the car fingerprint, so tuning a car is a matter of
editing one table. The upstream car port (opendbc) is never modified.

The 2021 Corolla LE is a Toyota Safety Sense 2.0 car. What is known about it:
  * the PCM lags accel commands by roughly 0.3-0.5 s and is soft off the line, so a
    slow launch ramp on top of that feels dead. Ramp faster and shorter.
  * brake hold only engages once the commanded accel reaches the port's stopAccel
    (about -2.5 m/s^2). At the default 0.5 m/s^2 per second that takes five seconds
    of creeping pressure; ramp a little faster so the hold lands in about three.
  * the radar tracks a stopped lead well at close range, so the re-launch hysteresis
    can be a bit tighter without creep-brake cycling.
  * the brakes are smooth but not strong at low pressure, so the end-of-stop release
    is kept slightly firmer than the generic value to avoid a rolling stop.

These are starting points chosen from the port's characteristics, not from logs of this
exact car. Adjust after a few drives; every value here is safe to move by 30 percent.
"""

DEFAULT = {
  # longcontrol: jerk-limited launch after the stopping state
  "starting_jerk": 2.0,          # m/s^3
  "starting_time": 1.0,          # s
  # longcontrol: brake build toward stopAccel once stopped
  "stopping_decel_rate": 0.5,    # m/s^2 per s
  # planner: re-launch hysteresis behind a stopped lead
  "launch_gap_hysteresis": 2.0,  # m beyond STOP_DISTANCE
  "launch_lead_speed": 1.0,      # m/s
  # stop profile shape
  "stop_a_firm": 1.5,            # m/s^2
  "stop_a_release": 0.6,         # m/s^2
}

CARS = {
  "TOYOTA_COROLLA_TSS2": {
    "starting_jerk": 3.0,
    "starting_time": 0.8,
    "stopping_decel_rate": 0.8,
    "launch_gap_hysteresis": 1.5,
    "stop_a_release": 0.7,
  },
}


def fingerprint_of(CP):
  fp = getattr(CP, "carFingerprint", None)
  if fp is None:
    return None
  return str(fp)


def tuning_for(CP):
  """DEFAULT merged with the car's overrides. Unknown or missing cars get DEFAULT."""
  out = dict(DEFAULT)
  fp = fingerprint_of(CP)
  if fp in CARS:
    out.update(CARS[fp])
  return out
