import numpy as np
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.car.fork_tuning import tuning_for

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState

# The stopping ramp and the jerk-limited launch are tuned per car in
# selfdrive/car/fork_tuning.py. The module-level names keep the generic defaults
# for tests and for reading the code:
#   stopping_decel_rate  m/s^2 per second the brake ramps toward CP.stopAccel once
#                        stopped; the ramp starts after the car is at rest, so a slow
#                        one avoids the lurch of settling into the brake hold
#   starting_jerk/time   after leaving the stopping state the accel command may rise
#                        at most this fast for this long. brake release is immediate
#                        (the limit only applies above zero), this keeps the throttle
#                        from stepping on
from openpilot.selfdrive.car.fork_tuning import DEFAULT as _FORK_DEFAULT
STOPPING_DECEL_RATE = _FORK_DEFAULT["stopping_decel_rate"]
STARTING_JERK = _FORK_DEFAULT["starting_jerk"]
STARTING_TIME = _FORK_DEFAULT["starting_time"]


def long_control_state_trans(active, long_control_state, should_stop, brake_pressed, cruise_standstill):
  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed)

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.pid:
      if should_stop:
        long_control_state = LongCtrlState.stopping

  return long_control_state

class LongControl:
  def __init__(self, CP):
    self.CP = CP
    self.long_control_state = LongCtrlState.off
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0
    self.starting_frames = 0
    tuning = tuning_for(CP)
    self.stopping_decel_rate = tuning["stopping_decel_rate"]
    self.starting_jerk = tuning["starting_jerk"]
    self.starting_time = tuning["starting_time"]

  def reset(self):
    self.pid.reset()

  def update(self, active, CS, a_target, should_stop, accel_limits):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    prev_state = self.long_control_state
    self.long_control_state = long_control_state_trans(active, self.long_control_state, should_stop,
                                                       CS.brakePressed, CS.cruiseState.standstill)
    if prev_state == LongCtrlState.stopping and self.long_control_state == LongCtrlState.pid:
      self.starting_frames = int(self.starting_time / DT_CTRL)

    if self.long_control_state == LongCtrlState.off:
      self.starting_frames = 0
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        # TODO: can we just go straight to stopAccel?
        output_accel -= self.stopping_decel_rate * DT_CTRL
      self.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)
      if self.starting_frames > 0:
        output_accel = min(output_accel, max(self.last_output_accel, 0.0) + self.starting_jerk * DT_CTRL)
        self.starting_frames -= 1

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
