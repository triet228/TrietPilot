# openpilot/selfdrive/controls/lib/stop_profile.py

"""Shapes the longitudinal target when a stop is predicted ahead.

The planner and the end-to-end model decide *that* the car should stop for a
red light, stop sign, or stopped lead. This module only decides *how* the
approach feels. It defines a braking schedule as a function of distance to the
stop point, integrates it into a target speed curve, and tracks that curve:

  far:      the schedule decel falls off as 1/sqrt(d), so far from the stop the
            car is under the curve and simply coasts. No gas, no brake.
  gentle:   as the car catches the curve, braking blends in at whatever the
            schedule says there, and grows smoothly as the distance closes.
  firm:     inside D_FIRM the schedule holds A_FIRM, a steady confident squeeze.
  release:  the schedule blends down to A_RELEASE over the last few metres so the
            car does not rock on its suspension as it comes to rest. The low
            level controller's stopping state then re-applies brake for the
            hold, which gives the firm-ease-firm feel of a practiced stop.

The shaper never asks for less braking than the plan, except in the release
zone and only when the plan itself is not braking hard. Accelerations are m/s^2,
negative is braking, distances are metres.
"""

import numpy as np

# braking schedule, from the stop point outward
D_RELEASE = 3.0   # last metres, eased brake
A_RELEASE = 0.6
D_BLEND = 2.0     # metres over which firm blends down into release
D_FIRM = 12.0     # inside this distance hold firm braking
A_FIRM = 1.5
P_FAR = 0.5       # beyond D_FIRM the schedule decel is A_FIRM * (D_FIRM / d) ** P_FAR

# tracking gain on speed error against the curve, 1/s. positive error (too
# fast for this distance) adds brake, negative error removes it. the added
# brake is capped so being far above the curve never turns into a hard stop.
K_SPEED = 0.5
TRACK_MAX = 1.0

# brake may build no faster than this, m/s^3. easing off is not limited, and the
# plan's own braking is never limited, only what this profile adds on top.
BUILD_JERK = 0.8
DT_DEFAULT = 0.05  # planner rate (DT_MDL)

# table resolution and extent for the target speed curve
_D_MAX = 400.0
_D_STEP = 0.1

# a predicted trajectory point below this speed counts as the stop location
V_STOP_PRED = 0.5


def schedule_decel(d, a_firm=A_FIRM, a_release=A_RELEASE):
  """Braking magnitude the schedule wants at distance d from the stop."""
  d = np.asarray(d, dtype=float)
  far = a_firm * (D_FIRM / np.maximum(d, D_FIRM)) ** P_FAR
  near = np.interp(d, [D_RELEASE, D_RELEASE + D_BLEND], [a_release, a_firm])
  return np.where(d < D_FIRM, near, far)


class Schedule:
  """The braking schedule for one (a_firm, a_release) pair with its integrated target speed curve."""

  def __init__(self, a_firm=A_FIRM, a_release=A_RELEASE):
    self.a_firm = a_firm
    self.a_release = a_release
    self.d_grid = np.arange(0.0, _D_MAX + _D_STEP, _D_STEP)
    decel = schedule_decel(self.d_grid, a_firm, a_release)
    # v_t^2(d) = 2 * integral_0^d decel(s) ds, trapezoid rule
    self.v2_grid = np.concatenate(([0.0], 2.0 * np.cumsum(0.5 * (decel[1:] + decel[:-1]) * _D_STEP)))

  def decel(self, d):
    return float(schedule_decel(d, self.a_firm, self.a_release))

  def target_speed(self, d):
    """Speed the curve wants at distance d. Zero at or past the stop point."""
    if d <= 0.0:
      return 0.0
    return float(np.sqrt(np.interp(d, self.d_grid, self.v2_grid)))

  def profile_accel(self, v_ego, d_stop):
    """Feedforward schedule braking plus capped proportional tracking of the curve."""
    track = min(K_SPEED * (v_ego - self.target_speed(d_stop)), TRACK_MAX)
    return -self.decel(d_stop) - track


_DEFAULT_SCHEDULE = Schedule()


def target_speed(d):
  return _DEFAULT_SCHEDULE.target_speed(d)


def profile_accel(v_ego, d_stop):
  return _DEFAULT_SCHEDULE.profile_accel(v_ego, d_stop)


def stop_distance_from_model(model_v2):
  """Distance to where the model's own plan reaches a stop, or None."""
  vel = model_v2.velocity.x
  pos = model_v2.position.x
  n = min(len(vel), len(pos))
  for i in range(n):
    if vel[i] < V_STOP_PRED:
      return max(float(pos[i]), 0.0)
  return None


def stop_distance_from_lead(lead, stop_distance):
  """Distance to the desired stopping point behind a stopped lead, or None."""
  if not lead.present or lead.vLead >= V_STOP_PRED:
    return None
  return max(float(lead.dRel) - stop_distance, 0.0)


class StopProfile:
  """Stateful shaper: remembers its last output so brake build-up can be jerk limited."""

  def __init__(self, dt=DT_DEFAULT, a_firm=A_FIRM, a_release=A_RELEASE):
    self.dt = dt
    self.a_prev = None
    self.schedule = Schedule(a_firm, a_release)

  def reset(self):
    self.a_prev = None

  def update(self, a_target, v_ego, d_stop, accel_coast):
    """Returns the shaped acceleration target given the plan's own a_target."""
    if d_stop is None:
      self.a_prev = None
      return a_target

    # a stop is coming: the profile may coast or brake, never throttle
    a_prof = min(self.schedule.profile_accel(v_ego, d_stop), accel_coast)

    # build brake gradually from wherever the car currently is. on the first
    # frame that is the plan's own accel, clipped to coast so a car under
    # throttle starts its braking from zero rather than from a positive value.
    start = self.a_prev if self.a_prev is not None else min(a_target, accel_coast)
    a_prof = max(a_prof, start - BUILD_JERK * self.dt)
    self.a_prev = a_prof

    # in the release zone the profile is allowed to ease off the plan's braking,
    # unless the plan is braking hard, in which case it knows something we do not
    if d_stop < D_RELEASE + D_BLEND and a_target > -self.schedule.a_firm:
      return float(a_prof)

    return float(min(a_target, a_prof))
