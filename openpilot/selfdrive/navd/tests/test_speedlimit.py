# openpilot/selfdrive/navd/tests/test_speedlimit.py

import gzip
import json
import os
import tempfile

from openpilot.common.constants import CV
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_map import build, parse_maxspeed, parse_oneway, DEFAULT_SPEED_MPH
from openpilot.selfdrive.navd.offline_map import OfflineMap, MAX_MATCH_DIST
from openpilot.selfdrive.navd.speedlimitd import SpeedLimitTracker, cruise_target_kph, LOCAL_OFFSET_MPH, FREEWAY_OFFSET_MPH
from openpilot.selfdrive.car.cruise import VCruiseHelper, parse_speed_limit_target, V_CRUISE_UNSET

LAT0, LON0 = 42.28, -83.74
DLAT = 0.001  # ~111 m


def way(wid, cls, coords, **tags):
  return {
    "type": "way", "id": wid,
    "tags": {"highway": cls, **tags},
    "nodes": [wid * 100 + i for i in range(len(coords))],
    "geometry": [{"lat": la, "lon": lo} for la, lo in coords],
  }


def synthetic_map():
  """East-west arterial, north-south residential crossing it, one-way motorway to the north."""
  elements = [
    way(1, "primary", [(LAT0, LON0 - 0.01), (LAT0, LON0), (LAT0, LON0 + 0.01)], maxspeed="45 mph", name="Arterial"),
    way(2, "residential", [(LAT0 - 0.01, LON0), (LAT0, LON0), (LAT0 + 0.01, LON0)], name="Side St"),
    way(3, "motorway", [(LAT0 + 5 * DLAT, LON0 - 0.01), (LAT0 + 5 * DLAT, LON0 + 0.01)], maxspeed="70 mph", oneway="yes", name="I 94"),
  ]
  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path


class FakeCP:
  pcmCruise = False


class TestBuildMap(OpenpilotTestCase):
  def test_parse_maxspeed(self):
    assert parse_maxspeed("45 mph") == 45
    assert parse_maxspeed("50") == 31
    assert parse_maxspeed("80 km/h") == 50
    assert parse_maxspeed("signals") is None
    assert parse_maxspeed(None) is None

  def test_parse_oneway(self):
    assert parse_oneway({"oneway": "yes"}) == 1
    assert parse_oneway({"oneway": "-1"}) == -1
    assert parse_oneway({"highway": "residential"}) == 0
    assert parse_oneway({"highway": "motorway"}) == 1
    assert parse_oneway({"junction": "roundabout"}) == 1

  def test_defaults_fill_missing_limits(self):
    data = build([way(1, "residential", [(LAT0, LON0), (LAT0, LON0 + 0.001)])])
    assert data["ways"][0]["s"] == DEFAULT_SPEED_MPH["residential"]
    assert data["ways"][0]["x"] is False

  def test_shared_nodes_are_deduplicated(self):
    data = build([
      way(1, "primary", [(LAT0, LON0), (LAT0, LON0 + 0.001)]),
      {**way(2, "primary", [(LAT0, LON0 + 0.001), (LAT0, LON0 + 0.002)]), "nodes": [101, 201]},
    ])
    assert len(data["lat"]) == 3


class TestOfflineMap(OpenpilotTestCase):
  def setup_method(self):
    self.path = synthetic_map()
    self.m = OfflineMap(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def test_match_on_road(self):
    r = self.m.match(LAT0 + 0.00005, LON0 + 0.004, bearing=90)
    assert r is not None
    assert self.m.road_name(r.way_idx) == "Arterial"
    assert self.m.speed_limit_mph(r.way_idx) == 45
    assert not self.m.is_freeway(r.way_idx)
    assert r.dist < 10

  def test_bearing_picks_the_aligned_road_at_intersection(self):
    east = self.m.match(LAT0, LON0, bearing=90)
    north = self.m.match(LAT0, LON0, bearing=0)
    assert self.m.road_name(east.way_idx) == "Arterial"
    assert self.m.road_name(north.way_idx) == "Side St"

  def test_no_match_far_away(self):
    assert self.m.match(LAT0 + 0.002, LON0 + 0.004) is None
    assert self.m.match(LAT0 + 0.002, LON0 + 0.004, max_dist=MAX_MATCH_DIST * 10) is not None

  def test_freeway_and_oneway_direction(self):
    # heading east on the eastbound-only motorway, at the point where Side St crosses under it
    r = self.m.match(LAT0 + 5 * DLAT, LON0, bearing=90)
    assert self.m.is_freeway(r.way_idx)
    assert self.m.speed_limit_mph(r.way_idx) == 70
    assert r.forward
    # heading west there is no aligned road, so the crossing street and the wrong-way
    # freeway tie on penalty; either way the freeway must not be reported as forward
    r = self.m.match(LAT0 + 5 * DLAT, LON0, bearing=270)
    assert self.m.road_name(r.way_idx) != "I 94" or r.forward

  def test_adjacency_respects_oneway(self):
    adj = self.m.adjacency()
    fw = [i for i, w in enumerate(self.m.ways) if w["name"] == "I 94"][0]
    a, b = self.m.ways[fw]["n"][0], self.m.ways[fw]["n"][1]
    assert any(n == b for n, _, _ in adj[a])
    assert all(n != a for n, _, _ in adj.get(b, []))
    # two-way arterial links both directions
    ar = [i for i, w in enumerate(self.m.ways) if w["name"] == "Arterial"][0]
    a, b = self.m.ways[ar]["n"][0], self.m.ways[ar]["n"][1]
    assert any(n == b for n, _, _ in adj[a]) and any(n == a for n, _, _ in adj[b])


class TestSpeedLimitTracker(OpenpilotTestCase):
  def setup_method(self):
    self.path = synthetic_map()
    self.tracker = SpeedLimitTracker(OfflineMap(self.path))

  def teardown_method(self):
    os.remove(self.path)

  def test_target_offsets(self):
    assert cruise_target_kph(45, False) == round((45 + LOCAL_OFFSET_MPH) * CV.MPH_TO_KPH, 1)
    assert cruise_target_kph(70, True) == round((70 + FREEWAY_OFFSET_MPH) * CV.MPH_TO_KPH, 1)

  def test_debounce_requires_two_sightings(self):
    on_arterial = (LAT0, LON0 + 0.004, 90)
    on_freeway = (LAT0 + 5 * DLAT, LON0, 90)
    assert self.tracker.update(*on_arterial)["valid"] is False  # first sighting only pending
    p = self.tracker.update(*on_arterial)
    assert p["valid"] and p["road"] == "Arterial" and p["limit_mph"] == 45 and not p["freeway"]
    # a single glitchy freeway match does not change anything
    p = self.tracker.update(*on_freeway)
    assert p["road"] == "Arterial"
    p = self.tracker.update(*on_arterial)
    assert p["road"] == "Arterial"
    # two in a row does
    self.tracker.update(*on_freeway)
    p = self.tracker.update(*on_freeway)
    assert p["road"] == "I 94" and p["freeway"] and p["target_kph"] == cruise_target_kph(70, True)

  def test_leaving_the_map_invalidates(self):
    pt = (LAT0, LON0 + 0.004, 90)
    self.tracker.update(*pt)
    self.tracker.update(*pt)
    self.tracker.update(LAT0 + 0.05, LON0, 90)
    p = self.tracker.update(LAT0 + 0.05, LON0, 90)
    assert p == {"valid": False}


class TestCruiseIntegration(OpenpilotTestCase):
  def test_parse_payload(self):
    assert parse_speed_limit_target(b'{"valid": true, "target_kph": 88.5}') == 88.5
    assert parse_speed_limit_target(b'{"valid": false}') is None
    assert parse_speed_limit_target(b'not json') is None
    assert parse_speed_limit_target(b'{"valid": true, "target_kph": "fast"}') is None

  def test_apply_once_per_target(self):
    h = VCruiseHelper(FakeCP())
    h.v_cruise_kph = 60.0
    h.apply_speed_limit_target(88.5, True)
    assert h.v_cruise_kph == 88.5
    # driver nudges it, same target does not fight back
    h.v_cruise_kph = 90.1
    h.apply_speed_limit_target(88.5, True)
    assert h.v_cruise_kph == 90.1
    # new road, new target wins
    h.apply_speed_limit_target(104.6, True)
    assert h.v_cruise_kph == 104.6

  def test_not_applied_when_disengaged_or_uninitialized(self):
    h = VCruiseHelper(FakeCP())
    h.apply_speed_limit_target(88.5, True)
    assert h.v_cruise_kph == V_CRUISE_UNSET
    h.v_cruise_kph = 60.0
    h.apply_speed_limit_target(88.5, False)
    assert h.v_cruise_kph == 60.0
    # engaging afterwards applies the current road's target right away
    h.apply_speed_limit_target(88.5, True)
    assert h.v_cruise_kph == 88.5

  def test_pcm_cruise_untouched(self):
    class PcmCP:
      pcmCruise = True
    h = VCruiseHelper(PcmCP())
    h.v_cruise_kph = 60.0
    h.apply_speed_limit_target(88.5, True)
    assert h.v_cruise_kph == 60.0
