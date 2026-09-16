# openpilot/selfdrive/controls/tests/test_auto_lane_change.py

from openpilot.cereal import log
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChange, freeway_from_payload, AUTO_START_DELAY
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeState, LaneChangeDirection, LANE_CHANGE_SPEED_MIN


class FakeCarState:
  def __init__(self, v_ego=30.0, left=False, right=False, torque=0.0, pressed=False, left_bs=False, right_bs=False):
    self.vEgo = v_ego
    self.leftBlinker = left
    self.rightBlinker = right
    self.steeringTorque = torque
    self.steeringPressed = pressed
    self.leftBlindspot = left_bs
    self.rightBlindspot = right_bs


class TestAutoLaneChange(OpenpilotTestCase):
  def test_freeway_from_payload(self):
    assert freeway_from_payload(b'{"valid": true, "freeway": true}') is True
    assert freeway_from_payload(b'{"valid": true, "freeway": false}') is False
    assert freeway_from_payload(b'{"valid": false, "freeway": true}') is False
    assert freeway_from_payload(b'nope') is False

  def test_starts_after_delay_on_freeway_only(self):
    alc = AutoLaneChange(dt=0.25)
    steps = int(AUTO_START_DELAY / 0.25)
    for _ in range(steps - 1):
      assert alc.update(True, True, True) is False
    assert alc.update(True, True, True) is True
    # in town it never fires, and the timer resets
    alc = AutoLaneChange(dt=0.25)
    for _ in range(steps * 2):
      assert alc.update(True, False, True) is False
    assert alc.timer == 0.0
    # disabled never fires either
    for _ in range(steps * 2):
      assert alc.update(True, True, False) is False

  def test_timer_resets_when_leaving_pre_lane_change(self):
    alc = AutoLaneChange(dt=0.5)
    alc.update(True, True, True)
    assert alc.timer == 0.5
    alc.update(False, True, True)
    assert alc.timer == 0.0


class TestDesireHelperAutoStart(OpenpilotTestCase):
  def enter_pre(self, dh):
    dh.update(FakeCarState(), True, 0.0)
    dh.update(FakeCarState(left=True), True, 0.0)
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    assert dh.lane_change_direction == LaneChangeDirection.left

  def test_nudge_still_required_by_default(self):
    dh = DesireHelper()
    self.enter_pre(dh)
    for _ in range(int(3.0 / DT_MDL)):
      dh.update(FakeCarState(left=True), True, 0.0)
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    assert dh.desire == log.Desire.none

  def test_auto_start_replaces_the_nudge(self):
    dh = DesireHelper()
    self.enter_pre(dh)
    dh.update(FakeCarState(left=True), True, 0.0, auto_start=True)
    assert dh.lane_change_state == LaneChangeState.laneChangeStarting
    assert dh.desire == log.Desire.laneChangeLeft

  def test_blindspot_blocks_auto_start(self):
    dh = DesireHelper()
    self.enter_pre(dh)
    dh.update(FakeCarState(left=True, left_bs=True), True, 0.0, auto_start=True)
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    # the other side's blind spot does not matter
    dh.update(FakeCarState(left=True, right_bs=True), True, 0.0, auto_start=True)
    assert dh.lane_change_state == LaneChangeState.laneChangeStarting

  def test_auto_start_needs_pre_lane_change(self):
    dh = DesireHelper()
    # too slow to ever enter preLaneChange, so auto_start is ignored
    dh.update(FakeCarState(v_ego=LANE_CHANGE_SPEED_MIN - 1.0), True, 0.0)
    dh.update(FakeCarState(v_ego=LANE_CHANGE_SPEED_MIN - 1.0, left=True), True, 0.0, auto_start=True)
    assert dh.lane_change_state == LaneChangeState.off

  def test_cancelling_the_signal_aborts(self):
    dh = DesireHelper()
    self.enter_pre(dh)
    dh.update(FakeCarState(), True, 0.0, auto_start=True)
    assert dh.lane_change_state == LaneChangeState.off
