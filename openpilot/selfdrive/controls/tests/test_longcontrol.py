from openpilot.common.test import OpenpilotTestCase
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.longcontrol import (LongCtrlState, LongControl, long_control_state_trans,
                                                          STOPPING_DECEL_RATE, STARTING_JERK, STARTING_TIME)


class TestLongControlStateTransition(OpenpilotTestCase):

  def test_stay_stopped(self):
    active = True
    current_state = LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.pid
    active = False
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.off

  def test_engage(self):
    active = True
    current_state = LongCtrlState.off
    next_state = long_control_state_trans(active, current_state,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.pid


class FakeCP:
  stopAccel = -2.0

  class longitudinalTuning:
    kiBP = [0.]
    kiV = [0.]


class FakeCS:
  def __init__(self, v_ego=0.0, a_ego=0.0, brake_pressed=False, standstill=False):
    self.vEgo = v_ego
    self.aEgo = a_ego
    self.brakePressed = brake_pressed

    class cruiseState:
      pass
    self.cruiseState = cruiseState()
    self.cruiseState.standstill = standstill


class TestLongControlSmoothStopGo(OpenpilotTestCase):
  LIMITS = (-3.5, 2.0)

  def setup_method(self):
    self.LoC = LongControl(FakeCP())

  def stop(self, frames=1):
    out = None
    for _ in range(frames):
      out = self.LoC.update(True, FakeCS(), 0.0, True, self.LIMITS)
    return out

  def test_stopping_ramp_rate(self):
    first = self.stop()
    second = self.stop()
    assert self.LoC.long_control_state == LongCtrlState.stopping
    assert abs((first - second) - STOPPING_DECEL_RATE * DT_CTRL) < 1e-9

  def test_stopping_settles_at_stop_accel(self):
    out = self.stop(frames=int(5 / DT_CTRL))
    assert abs(out - FakeCP.stopAccel) < STOPPING_DECEL_RATE * DT_CTRL + 1e-9

  def test_launch_releases_brake_then_ramps(self):
    self.stop(frames=int(5 / DT_CTRL))
    # brake release: the first frame may jump straight from stopAccel to zero
    out = self.LoC.update(True, FakeCS(), 1.5, False, self.LIMITS)
    assert self.LoC.long_control_state == LongCtrlState.pid
    assert abs(out - STARTING_JERK * DT_CTRL) < 1e-9
    # then the command may only rise at STARTING_JERK
    prev = out
    for _ in range(10):
      out = self.LoC.update(True, FakeCS(), 1.5, False, self.LIMITS)
      assert abs((out - prev) - STARTING_JERK * DT_CTRL) < 1e-9
      prev = out

  def test_launch_ramp_expires(self):
    self.stop()
    frames = int(STARTING_TIME / DT_CTRL)
    for _ in range(frames):
      self.LoC.update(True, FakeCS(), 1.5, False, self.LIMITS)
    assert self.LoC.starting_frames == 0
    out = self.LoC.update(True, FakeCS(), 1.5, False, self.LIMITS)
    assert abs(out - 1.5) < 1e-9

  def test_launch_ramp_does_not_limit_braking(self):
    self.stop()
    out = self.LoC.update(True, FakeCS(), -1.0, False, self.LIMITS)
    assert abs(out - (-1.0)) < 1e-9

  def test_off_clears_ramp(self):
    self.stop()
    self.LoC.update(True, FakeCS(), 1.5, False, self.LIMITS)
    assert self.LoC.starting_frames > 0
    self.LoC.update(False, FakeCS(), 1.5, False, self.LIMITS)
    assert self.LoC.starting_frames == 0
