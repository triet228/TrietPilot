# openpilot/system/loggerd/tests/test_incidentd.py

from openpilot.system.loggerd.incidentd import (IncidentDetector, HARD_BRAKE_ACCEL, HARD_BRAKE_FRAMES,
                                                HARD_BRAKE_MIN_SPEED, IMPACT_ACCEL, GRAVITY, COOLDOWN, EventName)


class TestIncidentDetector:
  def setup_method(self):
    self.d = IncidentDetector()

  def brake(self, frames, a_ego=HARD_BRAKE_ACCEL - 1, v_ego=HARD_BRAKE_MIN_SPEED + 5, t0=0.0):
    reason = None
    for i in range(frames):
      reason = self.d.update(t0 + i * 0.01, a_ego=a_ego, v_ego=v_ego)
    return reason

  def test_no_trigger_normal_driving(self):
    for i in range(100):
      assert self.d.update(i * 0.01, a_ego=-2.0, v_ego=20.0, accel_v=[0.0, 0.0, GRAVITY],
                           event_names=[EventName.steerSaturated], panda_alive=True) is None

  def test_hard_brake_needs_sustained_frames(self):
    assert self.brake(HARD_BRAKE_FRAMES - 1) is None
    assert self.brake(1, t0=1.0) == "hard brake"

  def test_hard_brake_counter_resets(self):
    self.brake(HARD_BRAKE_FRAMES - 1)
    assert self.d.update(0.5, a_ego=0.0, v_ego=20.0) is None
    assert self.brake(HARD_BRAKE_FRAMES - 1, t0=1.0) is None

  def test_hard_brake_ignored_at_low_speed(self):
    assert self.brake(HARD_BRAKE_FRAMES * 2, v_ego=HARD_BRAKE_MIN_SPEED - 1) is None

  def test_impact(self):
    assert self.d.update(0.0, accel_v=[0.0, 0.0, GRAVITY + IMPACT_ACCEL - 1]) is None
    assert self.d.update(1.0, accel_v=[0.0, 0.0, GRAVITY + IMPACT_ACCEL + 1]) == "impact"

  def test_impact_ignores_short_vector(self):
    assert self.d.update(0.0, accel_v=[100.0]) is None

  def test_safety_events(self):
    assert self.d.update(0.0, event_names=[EventName.fcw]) == "safety event"
    assert self.d.update(COOLDOWN + 1, event_names=[EventName.aeb]) == "safety event"

  def test_panda_loss_only_after_seen(self):
    assert self.d.update(0.0, panda_alive=False) is None
    assert self.d.update(1.0, panda_alive=True) is None
    assert self.d.update(2.0, panda_alive=False) == "panda loss"

  def test_cooldown(self):
    assert self.d.update(0.0, event_names=[EventName.fcw]) == "safety event"
    assert self.d.update(COOLDOWN / 2, event_names=[EventName.fcw]) is None
    assert self.d.update(COOLDOWN, event_names=[EventName.fcw]) == "safety event"

  def test_multiple_reasons_joined(self):
    reason = self.brake(HARD_BRAKE_FRAMES)
    assert reason == "hard brake"
    self.d.last_trigger_t = None
    assert self.d.update(1.0, a_ego=HARD_BRAKE_ACCEL - 1, v_ego=20.0, event_names=[EventName.fcw]) == "hard brake, safety event"
