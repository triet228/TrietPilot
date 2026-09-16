# openpilot/selfdrive/navd/tests/test_curve_speed.py

import gzip
import json
import math
import os
import tempfile

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_map import build
from openpilot.selfdrive.navd.offline_map import OfflineMap
from openpilot.selfdrive.navd.curve_speed import (lookahead_points, curvatures, curve_speed, CurveSpeedFilter,
                                                  A_LAT_MAX, A_DECEL, MIN_CURVE_SPEED, RISE_RATE)
from openpilot.selfdrive.controls.lib.longitudinal_planner import map_speed_cap_from_payload

LAT0, LON0 = 42.28, -83.74
M_PER_DEG_LAT = 111000.0


def arc_points(radius, angle_deg, n=20, offset=0.0):
  """(x, y, dist) samples along a circular arc, optionally after a straight run of `offset` metres."""
  pts = []
  d = 0.0
  prev = None
  for i in range(n + 1):
    t = math.radians(angle_deg) * i / n
    x = offset + radius * math.sin(t)
    y = radius * (1 - math.cos(t))
    if prev is not None:
      d += math.hypot(x - prev[0], y - prev[1])
    pts.append((x, y, d))
    prev = (x, y)
  return pts


def straight_points(length, step=20.0):
  return [(float(i), 0.0, float(i)) for i in range(0, int(length) + 1, int(step))]


def way(wid, coords, node_ids, cls="secondary", **tags):
  return {"type": "way", "id": wid, "tags": {"highway": cls, **tags}, "nodes": node_ids,
          "geometry": [{"lat": la, "lon": lo} for la, lo in coords]}


def lat_at(y_m):
  return LAT0 + y_m / M_PER_DEG_LAT


def lon_at(x_m):
  return LON0 + x_m / (M_PER_DEG_LAT * math.cos(math.radians(LAT0)))


def write_map(elements):
  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path


class TestCurvatureMath(OpenpilotTestCase):
  def test_curvature_of_arc(self):
    pts = arc_points(100.0, 60.0)
    ks = curvatures(pts)
    interior = ks[2:-2]
    assert all(abs(k - 0.01) < 0.0005 for k in interior), interior

  def test_straight_is_zero(self):
    assert all(k == 0.0 for k in curvatures(straight_points(200)))

  def test_curve_speed_in_the_bend(self):
    # sitting at the start of a 100 m radius bend: comfortable speed is sqrt(a_lat * r)
    pts = arc_points(100.0, 60.0)
    v = curve_speed(pts, personality=1)
    assert v is not None
    assert abs(v - math.sqrt(A_LAT_MAX[1] * 100.0)) < 0.6

  def test_curve_speed_far_ahead_is_higher(self):
    # the same bend 200 m out allows sqrt(v_curve^2 + 2 a d) now
    near = curve_speed(arc_points(100.0, 60.0), personality=1)
    arc = [(x, y, d + 200.0) for x, y, d in arc_points(100.0, 60.0, offset=200.0)]
    far = curve_speed(straight_points(200)[:-1] + arc, personality=1)
    expected = math.sqrt(near ** 2 + 2 * A_DECEL * 200.0)
    assert far > near
    assert abs(far - expected) < 1.0

  def test_personality_changes_limit(self):
    pts = arc_points(100.0, 60.0)
    assert curve_speed(pts, 0) > curve_speed(pts, 1) > curve_speed(pts, 2)

  def test_straight_road_no_limit(self):
    assert curve_speed(straight_points(300)) is None

  def test_hairpin_floor(self):
    v = curve_speed(arc_points(5.0, 150.0), personality=2)
    assert v >= MIN_CURVE_SPEED - 1e-9

  def test_filter_drops_fast_rises_slow(self):
    f = CurveSpeedFilter(0.2)
    assert f.update(20.0) == 20.0
    assert f.update(10.0) == 10.0
    assert abs(f.update(20.0) - (10.0 + RISE_RATE * 0.2)) < 1e-9
    assert f.update(None) is None
    assert f.update(15.0) == 15.0


class TestLookahead(OpenpilotTestCase):
  """A straight east-west road that continues into a second way, with a side street forking off."""

  def setup_method(self):
    main1 = [(lat_at(0), lon_at(x)) for x in (0, 100, 200)]
    main2 = [(lat_at(0), lon_at(x)) for x in (200, 300, 400, 500)]
    side = [(lat_at(0), lon_at(200)), (lat_at(100), lon_at(210))]
    self.path = write_map([
      way(1, main1, [1, 2, 3], name="Main W"),
      way(2, main2, [3, 4, 5, 6], name="Main E"),
      way(3, side, [3, 30], cls="residential", name="Side"),
    ])
    self.m = OfflineMap(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def test_follows_straight_continuation_past_side_street(self):
    match = self.m.match(lat_at(0), lon_at(50), bearing=90)
    pts = lookahead_points(self.m, match, max_dist=1000)
    assert abs(pts[0][0] - self.m.to_xy(lat_at(0), lon_at(50))[0]) < 1.0
    # reaches the far end of Main E, 450 m ahead of the car
    assert abs(pts[-1][2] - 450.0) < 3.0
    # stays on the east-west line, never wanders up Side
    assert all(abs(y - pts[0][1]) < 2.0 for _, y, _ in pts)

  def test_stops_at_max_dist(self):
    match = self.m.match(lat_at(0), lon_at(50), bearing=90)
    pts = lookahead_points(self.m, match, max_dist=120)
    assert 120 <= pts[-1][2] < 200

  def test_reverse_direction(self):
    match = self.m.match(lat_at(0), lon_at(350), bearing=270)
    pts = lookahead_points(self.m, match, max_dist=1000)
    assert pts[-1][0] < pts[0][0]
    assert abs(pts[-1][2] - 350.0) < 3.0


class TestLookaheadFork(OpenpilotTestCase):
  """A Y fork: two continuations at +15 and -15 degrees, which is ambiguous, so the look-ahead must stop."""

  def setup_method(self):
    stem = [(lat_at(0), lon_at(x)) for x in (0, 100, 200)]
    left = [(lat_at(0), lon_at(200)), (lat_at(27), lon_at(300))]
    right = [(lat_at(0), lon_at(200)), (lat_at(-27), lon_at(300))]
    self.path = write_map([way(1, stem, [1, 2, 3]), way(2, left, [3, 4]), way(3, right, [3, 5])])
    self.m = OfflineMap(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def test_stops_at_ambiguous_fork(self):
    match = self.m.match(lat_at(0), lon_at(50), bearing=90)
    pts = lookahead_points(self.m, match, max_dist=1000)
    assert abs(pts[-1][2] - 150.0) < 3.0


class TestPayload(OpenpilotTestCase):
  def test_curve_speed_from_payload(self):
    assert map_speed_cap_from_payload(b'{"valid": true, "curve_speed_kph": 40.5}') == 40.5
    assert map_speed_cap_from_payload(b'{"valid": true}') is None
    assert map_speed_cap_from_payload(b'{"valid": false, "curve_speed_kph": 40.5}') is None
    assert map_speed_cap_from_payload(b'nope') is None
