# openpilot/selfdrive/navd/tests/test_bump_speed.py

import gzip
import json
import math
import os
import tempfile

from openpilot.common.constants import CV
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_map import build
from openpilot.selfdrive.navd.offline_map import OfflineMap
from openpilot.selfdrive.navd.curve_speed import lookahead
from openpilot.selfdrive.navd.bump_speed import bump_speed, BUMP_SPEED, A_DECEL, LOOKAHEAD_M
from openpilot.selfdrive.navd.speedlimitd import SpeedLimitTracker
from openpilot.selfdrive.controls.lib.longitudinal_planner import map_speed_cap_from_payload

LAT0, LON0 = 42.28, -83.74
M_PER_DEG_LAT = 111000.0


def lat_at(y_m):
  return LAT0 + y_m / M_PER_DEG_LAT


def lon_at(x_m):
  return LON0 + x_m / (M_PER_DEG_LAT * math.cos(math.radians(LAT0)))


def way(wid, xs, node_ids, cls="residential", **tags):
  return {"type": "way", "id": wid, "tags": {"highway": cls, **tags}, "nodes": node_ids,
          "geometry": [{"lat": lat_at(0), "lon": lon_at(x)} for x in xs]}


def node(nid, x, **tags):
  return {"type": "node", "id": nid, "lat": lat_at(0), "lon": lon_at(x), "tags": tags}


def write_map(elements):
  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path, data


class TestBumpMath(OpenpilotTestCase):
  def test_approach_and_kinds(self):
    kinds = {1: "bump", 2: "hump", 3: None}
    v = bump_speed([(3, 20.0), (1, 100.0)], kinds.get)
    assert abs(v - math.sqrt(BUMP_SPEED["bump"] ** 2 + 2 * A_DECEL * 100.0)) < 1e-9
    assert bump_speed([(2, 0.0)], kinds.get) == BUMP_SPEED["hump"]
    assert bump_speed([(3, 10.0)], kinds.get) is None
    assert bump_speed([(1, LOOKAHEAD_M + 1.0)], kinds.get) is None
    assert bump_speed([], kinds.get) is None


class TestBumpOnMap(OpenpilotTestCase):
  """A straight 25 mph street, 900 m long, with a bump node at 300 m, a table way at 600 m, and an island at 750 m."""

  def setup_method(self):
    elements = [
      way(1, (0, 150, 300, 450), [1, 2, 3, 4], maxspeed="25 mph", name="Bumpy St"),
      way(2, (450, 600, 610, 750, 900), [4, 5, 6, 7, 8], maxspeed="25 mph", name="Bumpy St"),
      node(3, 300, traffic_calming="bump"),
      node(7, 750, traffic_calming="island"),
      node(99, 5000, traffic_calming="bump"),  # not on any mapped road, dropped
    ]
    # the table is a short way of its own tagged traffic_calming, split out of way 2 here for simplicity
    elements[1] = way(2, (450, 600), [4, 5], maxspeed="25 mph", name="Bumpy St")
    elements.append(way(3, (600, 610), [5, 6], maxspeed="25 mph", name="Bumpy St", traffic_calming="table"))
    elements.append(way(4, (610, 750, 900), [6, 7, 8], maxspeed="25 mph", name="Bumpy St"))
    self.path, self.data = write_map(elements)
    self.m = OfflineMap(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def test_map_stores_calming_nodes_on_roads_only(self):
    kinds = sorted(k for _, k in self.data["calming"])
    assert kinds == ["bump", "table", "table"]  # the table way marks both of its nodes
    assert self.data["version"] == 3
    bump_nodes = [n for n, k in self.data["calming"] if k == "bump"]
    assert self.m.calming_at(bump_nodes[0]) == "bump"
    assert abs(self.m.x[bump_nodes[0]] - self.m.to_xy(lat_at(0), lon_at(300))[0]) < 1.0

  def test_lookahead_reports_nodes_with_distance(self):
    match = self.m.match(lat_at(0), lon_at(100), bearing=90)
    pts, ways, nodes = lookahead(self.m, match, max_dist=1000)
    dists = {self.m.calming_at(n): d for n, d in nodes if self.m.calming_at(n)}
    assert abs(dists["bump"] - 200.0) < 3.0
    assert 495.0 < dists["table"] < 515.0
    assert all(d1 <= d2 for (_, d1), (_, d2) in zip(nodes, nodes[1:], strict=False))
    assert len(pts) == len(nodes) + 1

  def drive(self, x_m):
    tracker = SpeedLimitTracker(self.m)
    p = None
    for _ in range(2):
      p = tracker.update(lat_at(0), lon_at(x_m), 90)
    return tracker, p

  def test_bump_cap_in_payload(self):
    _, p = self.drive(200.0)
    expected = math.sqrt(BUMP_SPEED["bump"] ** 2 + 2 * A_DECEL * 100.0) * CV.MS_TO_KPH
    assert abs(p["bump_speed_kph"] - round(expected, 1)) < 0.2
    # the table 400 m out is beyond the bump look-ahead, and the island never counts
    _, p = self.drive(760.0)
    assert "bump_speed_kph" not in p
    # right after the bump the cap is gone (the table is still 300 m away)
    _, p = self.drive(305.0)
    assert "bump_speed_kph" not in p

  def test_cap_rises_slowly_after_the_bump(self):
    tracker, p = self.drive(295.0)
    low = p["bump_speed_kph"]
    assert abs(low - round(math.sqrt(BUMP_SPEED["bump"] ** 2 + 2 * A_DECEL * 5.0) * CV.MS_TO_KPH, 1)) < 0.2
    # approaching the table from 450 m: the cap is allowed to climb only a little per frame
    p = tracker.update(lat_at(0), lon_at(450.0), 90)
    assert low < p["bump_speed_kph"] < low + 2.0


class TestPlannerPayload(OpenpilotTestCase):
  def test_bump_cap_included(self):
    assert map_speed_cap_from_payload(b'{"valid": true, "bump_speed_kph": 20.0, "curve_speed_kph": 40.5}') == 20.0
    assert map_speed_cap_from_payload(b'{"valid": true, "bump_speed_kph": 20.0}') == 20.0
