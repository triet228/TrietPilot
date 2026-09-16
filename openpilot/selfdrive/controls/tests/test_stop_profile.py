# openpilot/selfdrive/controls/tests/test_stop_profile.py

import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.lib.stop_profile import (StopProfile, schedule_decel, target_speed,
                                                          stop_distance_from_model, stop_distance_from_lead,
                                                          A_FIRM, A_RELEASE, D_RELEASE, D_BLEND, D_FIRM, TRACK_MAX, BUILD_JERK)

DT = 0.05
COAST = -0.3
STANDSTILL = 0.3  # controller stopping state takes over below this


def shape(a_target, v_ego, d_stop):
  return StopProfile(DT).update(a_target, v_ego, d_stop, COAST)


def simulate(v0, d0, a_plan=1.0, dt=DT):
  """Drive the shaper alone toward a stop. The plan asks for throttle so the shaper does all the work."""
  v, x, t = v0, 0.0, 0.0
  sp = StopProfile(dt)
  log = []
  while v > STANDSTILL and t < 120:
    d = d0 - x
    a = sp.update(a_plan, v, d, COAST)
    log.append((t, x, v, d, a))
    v = max(v + a * dt, 0.0)
    x += v * dt
    t += dt
  return np.array(log)


class FakeXYZT:
  def __init__(self, x):
    self.x = x


class FakeModel:
  def __init__(self, vel, pos):
    self.velocity = FakeXYZT(vel)
    self.position = FakeXYZT(pos)


class FakeLead:
  def __init__(self, present=True, d_rel=30.0, v_lead=0.0):
    self.present = present
    self.dRel = d_rel
    self.vLead = v_lead


class TestStopProfile(OpenpilotTestCase):
  def test_schedule_shape(self):
    assert schedule_decel(0.0) == A_RELEASE
    assert schedule_decel(D_RELEASE) == A_RELEASE
    assert abs(schedule_decel(D_FIRM - 0.01) - A_FIRM) < 1e-6
    assert schedule_decel(D_FIRM) == A_FIRM
    assert schedule_decel(4 * D_FIRM) == A_FIRM / 2
    d = np.arange(0.0, 300.0, 0.5)
    assert np.all(np.diff(schedule_decel(d)[d > D_FIRM]) <= 0), "schedule should fall off with distance"

  def test_target_speed_monotonic(self):
    d = np.arange(0.0, 300.0, 0.5)
    v = np.array([target_speed(x) for x in d])
    assert v[0] == 0.0
    assert np.all(np.diff(v) > 0)
    assert target_speed(-1.0) == 0.0

  def test_no_stop_passthrough(self):
    assert shape(1.2, 20.0, None) == 1.2

  def test_far_coast_only(self):
    # well under the curve: lift off, do not brake
    assert shape(1.2, 5.0, 300.0) == COAST

  def test_never_brakes_less_than_plan_outside_release(self):
    assert shape(-2.5, 15.0, 30.0) == -2.5

  def test_release_defers_to_hard_plan(self):
    # inside release zone, a plan braking harder than firm is left alone
    assert shape(-2.5, 1.0, 1.0) == -2.5
    # a gentle plan is replaced by the release profile when on the curve
    out = shape(-1.2, target_speed(1.0), 1.0)
    assert abs(out + A_RELEASE) < 1e-6

  def _check_run(self, v0, d0, monotonic=True):
    log = simulate(v0, d0)
    t, x, v, d, a = log.T

    # stops near the target, never past it
    assert x[-1] <= d0 + 0.05, f"overshot: {x[-1]:.2f} > {d0}"
    assert x[-1] > d0 - 2.0, f"stopped short: {x[-1]:.2f} of {d0}"

    # never harder than firm plus the capped tracking correction
    assert a.min() >= -(A_FIRM + TRACK_MAX) - 1e-6, f"too hard: {a.min():.2f}"

    # braking builds monotonically (small tolerance) until the release blend starts,
    # when the car starts under the curve
    approach = a[d > D_RELEASE + D_BLEND + 0.5]
    if monotonic:
      assert np.all(np.diff(approach) <= 0.02), "braking eased off during approach"

    # jerk stays comfortable through the whole approach
    jerk = np.abs(np.diff(approach)) / DT
    assert np.all(jerk < 1.0), f"jerk {jerk.max():.2f}"

    # release: the last metres brake less than the firm zone did
    firm = a[(d < D_FIRM) & (d > D_RELEASE + D_BLEND)]
    tail = a[d < D_RELEASE]
    assert len(firm) > 0 and len(tail) > 0
    assert tail.mean() > firm.mean() + 0.3
    return log

  def test_highway_stop(self):
    # 20 m/s with only 200 m is above the curve from the start, so braking is
    # needed right away. it must still build gradually, never step in.
    log = self._check_run(20.0, 200.0, monotonic=False)
    a = log[:, 4]
    assert abs(a[0] - (COAST - BUILD_JERK * DT)) < 1e-9
    assert a[10] > -1.0

  def test_build_is_jerk_limited_from_throttle(self):
    # plan is accelerating hard, stop appears close: braking starts from coast and ramps
    sp = StopProfile(DT)
    first = sp.update(1.5, 15.0, 30.0, COAST)
    assert abs(first - (COAST - BUILD_JERK * DT)) < 1e-9
    second = sp.update(1.5, 15.0, 30.0, COAST)
    assert abs((first - second) - BUILD_JERK * DT) < 1e-9

  def test_reset_on_stop_cancelled(self):
    sp = StopProfile(DT)
    for _ in range(20):
      sp.update(1.0, 15.0, 30.0, COAST)
    assert sp.a_prev is not None
    assert sp.update(1.0, 15.0, None, COAST) == 1.0
    assert sp.a_prev is None

  def test_city_stop(self):
    log = self._check_run(13.0, 120.0)
    assert np.all(log[:20, 4] == COAST)

  def test_short_notice_stop(self):
    # lead appears stopped 40 m out at 8 m/s: braking starts immediately, still smooth
    self._check_run(8.0, 40.0)

  def test_stop_distance_from_model(self):
    m = FakeModel(vel=[10.0, 8.0, 3.0, 0.2, 0.0], pos=[0.0, 20.0, 40.0, 55.0, 56.0])
    assert stop_distance_from_model(m) == 55.0
    assert stop_distance_from_model(FakeModel(vel=[10.0, 10.0], pos=[0.0, 50.0])) is None

  def test_stop_distance_from_lead(self):
    assert stop_distance_from_lead(FakeLead(d_rel=30.0), 6.0) == 24.0
    assert stop_distance_from_lead(FakeLead(d_rel=30.0, v_lead=5.0), 6.0) is None
    assert stop_distance_from_lead(FakeLead(present=False), 6.0) is None
    assert stop_distance_from_lead(FakeLead(d_rel=4.0), 6.0) == 0.0
