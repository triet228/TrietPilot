# openpilot/selfdrive/car/tests/test_fork_tuning.py

from openpilot.common.realtime import DT_CTRL
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.car.fork_tuning import tuning_for, DEFAULT, CARS
from openpilot.selfdrive.controls.lib.longcontrol import LongControl
from openpilot.selfdrive.controls.lib.stop_profile import StopProfile, Schedule, A_FIRM, A_RELEASE, D_RELEASE


class CP:
  stopAccel = -2.5

  class longitudinalTuning:
    kiBP = [0.]
    kiV = [0.]

  def __init__(self, fingerprint=None):
    if fingerprint is not None:
      self.carFingerprint = fingerprint


class TestForkTuning(OpenpilotTestCase):
  def test_unknown_car_gets_defaults(self):
    assert tuning_for(CP()) == DEFAULT
    assert tuning_for(CP("SOME_OTHER_CAR")) == DEFAULT
    assert tuning_for(None) == DEFAULT

  def test_corolla_overrides_are_applied_and_complete(self):
    t = tuning_for(CP("TOYOTA_COROLLA_TSS2"))
    assert set(t) == set(DEFAULT)
    for k, v in CARS["TOYOTA_COROLLA_TSS2"].items():
      assert t[k] == v
    # every override key must exist in DEFAULT so a typo cannot silently do nothing
    for car, overrides in CARS.items():
      assert set(overrides) <= set(DEFAULT), car

  def test_corolla_launches_faster_than_default(self):
    generic = LongControl(CP())
    corolla = LongControl(CP("TOYOTA_COROLLA_TSS2"))
    assert corolla.starting_jerk > generic.starting_jerk
    assert corolla.starting_time < generic.starting_time
    assert corolla.stopping_decel_rate > generic.stopping_decel_rate

    class CS:
      vEgo = 0.0
      aEgo = 0.0
      brakePressed = False

      class cruiseState:
        standstill = False

    for c in (generic, corolla):
      c.update(True, CS(), 0.0, True, (-3.5, 2.0))
      c.update(True, CS(), 1.5, False, (-3.5, 2.0))
    generic_step = generic.update(True, CS(), 1.5, False, (-3.5, 2.0))
    corolla_step = corolla.update(True, CS(), 1.5, False, (-3.5, 2.0))
    assert corolla_step > generic_step
    assert abs((corolla_step - corolla.last_output_accel) - 0.0) < 1e-9  # sanity: value stored
    assert abs(corolla.starting_jerk * DT_CTRL * 2 - corolla_step) < 1e-9

  def test_stop_profile_uses_car_release(self):
    t = tuning_for(CP("TOYOTA_COROLLA_TSS2"))
    sp = StopProfile(0.05, t["stop_a_firm"], t["stop_a_release"])
    assert sp.schedule.decel(D_RELEASE) == t["stop_a_release"]
    assert Schedule().decel(D_RELEASE) == A_RELEASE
    assert Schedule().decel(10.0) == A_FIRM
    # a firmer release means a slightly higher target speed near the stop
    assert sp.schedule.target_speed(2.0) > Schedule().target_speed(2.0)
