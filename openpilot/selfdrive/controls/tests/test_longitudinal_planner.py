# openpilot/selfdrive/controls/tests/test_longitudinal_planner.py

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.lib.longitudinal_planner import hold_stop_for_lead, LAUNCH_GAP_HYSTERESIS, LAUNCH_LEAD_SPEED, STANDSTILL_SPEED
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import STOP_DISTANCE


class FakeLead:
  def __init__(self, present=True, d_rel=STOP_DISTANCE, v_lead=0.0):
    self.present = present
    self.dRel = d_rel
    self.vLead = v_lead


class TestHoldStopForLead(OpenpilotTestCase):
  def test_holds_when_lead_still_close(self):
    assert hold_stop_for_lead(True, 0.0, FakeLead(d_rel=STOP_DISTANCE + LAUNCH_GAP_HYSTERESIS - 0.5))

  def test_releases_on_gap(self):
    assert not hold_stop_for_lead(True, 0.0, FakeLead(d_rel=STOP_DISTANCE + LAUNCH_GAP_HYSTERESIS + 0.5))

  def test_releases_on_lead_speed(self):
    assert not hold_stop_for_lead(True, 0.0, FakeLead(v_lead=LAUNCH_LEAD_SPEED + 0.5))

  def test_no_hold_without_lead(self):
    assert not hold_stop_for_lead(True, 0.0, FakeLead(present=False))

  def test_no_hold_if_not_previously_stopped(self):
    assert not hold_stop_for_lead(False, 0.0, FakeLead())

  def test_no_hold_once_rolling(self):
    assert not hold_stop_for_lead(True, STANDSTILL_SPEED + 0.1, FakeLead())
