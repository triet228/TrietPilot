# openpilot/selfdrive/navd/tests/test_router.py

import gzip
import json
import os
import tempfile

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_map import build
from openpilot.selfdrive.navd.offline_map import OfflineMap
from openpilot.selfdrive.navd.router import find_route, snap, build_instructions
from openpilot.selfdrive.navd.navd import Navigator, RouteTracker, load_place, OFF_ROUTE_TIME, REROUTE_COOLDOWN

LAT0, LON0 = 42.28, -83.74
D = 0.002  # ~222 m north-south, ~165 m east-west


def grid_map():
  """3x3 grid of two-way residential streets with one arterial (row 1) and a one-way column (col 2).

  Node naming: row r (0..2, south to north), col c (0..2, west to east).
  Horizontal street r is named "H{r}", vertical street c is "V{c}".
  """
  def coord(r, c):
    return (LAT0 + r * D, LON0 + c * D)

  elements = []
  wid = 1
  for r in range(3):
    cls = "primary" if r == 1 else "residential"
    tags = {"name": f"H{r}"}
    if r == 1:
      tags["maxspeed"] = "45 mph"
    el = {"type": "way", "id": wid, "tags": {"highway": cls, **tags},
          "nodes": [r * 10 + c for c in range(3)],
          "geometry": [{"lat": la, "lon": lo} for la, lo in (coord(r, c) for c in range(3))]}
    elements.append(el)
    wid += 1
  for c in range(3):
    tags = {"name": f"V{c}"}
    if c == 2:
      tags["oneway"] = "yes"  # south to north only
    el = {"type": "way", "id": wid, "tags": {"highway": "residential", **tags},
          "nodes": [r * 10 + c for r in range(3)],
          "geometry": [{"lat": la, "lon": lo} for la, lo in (coord(r, c) for r in range(3))]}
    elements.append(el)
    wid += 1

  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path


class FakeParams:
  def __init__(self):
    self.d = {}

  def get(self, k):
    return self.d.get(k)

  def put(self, k, v, block=False):
    self.d[k] = v

  def remove(self, k):
    self.d.pop(k, None)


class Fix:
  def __init__(self, lat, lon, bearing=0.0, speed=10.0):
    self.latitude = lat
    self.longitude = lon
    self.bearingDeg = bearing
    self.speed = speed


class GridTest(OpenpilotTestCase):
  def setup_method(self):
    self.path = grid_map()
    self.m = OfflineMap(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def node(self, r, c):
    lat, lon = LAT0 + r * D, LON0 + c * D
    for i in range(len(self.m.lat)):
      if abs(self.m.lat[i] - lat) < 1e-7 and abs(self.m.lon[i] - lon) < 1e-7:
        return i
    raise AssertionError("node not found")

  def latlon(self, r, c):
    return LAT0 + r * D, LON0 + c * D


class TestRouter(GridTest):
  def test_snap_prefers_node_ahead(self):
    # on H1 between col 0 and 1, heading east: snaps to col 1
    lat, lon = LAT0 + D, LON0 + 0.3 * D
    assert snap(self.m, lat, lon, bearing=90)[0] == self.node(1, 1)
    assert snap(self.m, lat, lon, bearing=270)[0] == self.node(1, 0)
    assert self.m.road_name(snap(self.m, lat, lon, bearing=90)[1]) == "H1"
    # no bearing: nearest end
    assert snap(self.m, lat, lon)[0] == self.node(1, 0)

  def test_snap_far_off_road(self):
    assert snap(self.m, LAT0 - 5 * D, LON0) is None

  def test_route_prefers_arterial(self):
    # corner to corner diagonally: the middle leg runs on the 45 mph arterial H1, not H0 or H2
    route = find_route(self.m, self.node(0, 0), self.node(2, 2))
    assert route is not None
    assert route.nodes[0] == self.node(0, 0) and route.nodes[-1] == self.node(2, 2)
    names = [self.m.road_name(w) for w in route.ways]
    assert "H1" in names and "H0" not in names and "H2" not in names

  def test_virtual_start_vertex(self):
    # car a third of the way along H1 heading east: route starts under the car, first edge is on H1
    lat, lon = LAT0 + D, LON0 + 0.3 * D
    node, way = snap(self.m, lat, lon, bearing=90)
    route = find_route(self.m, node, self.node(1, 2), self.m.to_xy(lat, lon), way)
    assert route.nodes[0] is None
    assert self.m.road_name(route.ways[0]) == "H1"
    assert abs(route.total_dist - 1.7 * 165) < 8
    assert route.instructions[-1]["type"] == "arrive"

  def test_route_respects_oneway(self):
    # V2 is south->north only, so north->south along col 2 must detour
    route = find_route(self.m, self.node(2, 2), self.node(0, 2))
    assert route is not None
    for a, b, w in zip(route.nodes[:-1], route.nodes[1:], route.ways, strict=True):
      if self.m.road_name(w) == "V2":
        assert self.m.lat[b] > self.m.lat[a], "travelled the wrong way down V2"

  def test_same_node(self):
    route = find_route(self.m, self.node(1, 1), self.node(1, 1))
    assert route is not None and route.ways == [] and route.total_dist == 0.0

  def test_unreachable_returns_none(self):
    assert find_route(self.m, None, self.node(0, 0)) is None

  def test_instructions_for_two_turns(self):
    # (0,0) north on V0 to H1, east on H1, then north on V2 to (2,2)
    route = find_route(self.m, self.node(0, 0), self.node(2, 2))
    ins = route.instructions
    kinds = [(i["type"], i["modifier"], i["street"]) for i in ins]
    assert kinds[-1][0] == "arrive"
    turns = [k for k in kinds if k[0] == "turn"]
    assert len(turns) >= 1
    assert turns[0] == ("turn", "right", "H1")
    # distances increase along the route and end at the total
    dists = [i["dist"] for i in ins]
    assert dists == sorted(dists)
    assert abs(dists[-1] - route.total_dist) < 1e-6

  def test_straight_route_has_only_arrive(self):
    route = find_route(self.m, self.node(1, 0), self.node(1, 2))
    assert [i["type"] for i in build_instructions(self.m, route)] == ["arrive"]


class TestNavigator(GridTest):
  def setup_method(self):
    super().setup_method()
    self.params = FakeParams()
    self.nav = Navigator(self.m, self.params)

  def set_dest(self, r, c, name="Work"):
    lat, lon = self.latlon(r, c)
    self.params.put("NavDestination", json.dumps({"lat": lat, "lon": lon, "name": name}))

  def test_idle_without_destination(self):
    assert self.nav.update(Fix(*self.latlon(0, 0)), 0.0) == {"active": False, "status": "idle"}

  def test_no_gps(self):
    self.set_dest(2, 2)
    p = self.nav.update(None, 0.0)
    assert p["active"] and p["status"] == "no_gps"

  def test_routes_and_reports_first_maneuver(self):
    self.set_dest(2, 2)
    p = self.nav.update(Fix(*self.latlon(0, 0), bearing=0), 0.0)
    assert p["status"] == "routing"
    assert p["dest"] == "Work"
    assert p["maneuver"] == "turn" and p["modifier"] == "right" and p["street"] == "H1"
    assert 0 < p["distance_m"] <= p["remaining_m"]
    assert p["eta_s"] > 0

  def test_progress_and_arrival(self):
    self.set_dest(2, 2)
    self.nav.update(Fix(*self.latlon(0, 0), bearing=0), 0.0)
    # half way up V0 the turn is closer
    lat, lon = LAT0 + 0.5 * D, LON0
    p = self.nav.update(Fix(lat, lon, bearing=0), 1.0)
    assert p["status"] == "routing"
    assert p["maneuver"] == "turn" and p["street"] == "H1"
    assert abs(p["distance_m"] - 0.5 * 222) < 10
    # at the destination
    lat, lon = self.latlon(2, 2)
    p = self.nav.update(Fix(lat + 0.00001, lon), 2.0)
    assert p["status"] == "arrived"
    assert self.params.get("NavDestination") is None
    # banner persists briefly, then idle
    assert self.nav.update(Fix(lat, lon), 3.0)["status"] == "arrived"
    assert self.nav.update(Fix(lat, lon), 100.0)["status"] == "idle"

  def test_off_route_triggers_reroute(self):
    self.set_dest(2, 2)
    self.nav.update(Fix(*self.latlon(0, 0), bearing=0), 0.0)
    first_route = self.nav.route
    # drive the wrong way: east along H0 instead of north on V0
    t = REROUTE_COOLDOWN + 1.0
    lat, lon = LAT0, LON0 + 1.5 * D
    for _ in range(int(OFF_ROUTE_TIME * 2) + 3):
      p = self.nav.update(Fix(lat, lon, bearing=90), t)
      t += 0.5
    assert self.nav.route is not first_route
    assert p["status"] == "routing"

  def test_new_destination_replaces_route(self):
    self.set_dest(2, 2)
    self.nav.update(Fix(*self.latlon(0, 0), bearing=0), 0.0)
    self.set_dest(0, 2, name="Home")
    p = self.nav.update(Fix(*self.latlon(0, 0), bearing=90), 1.0)
    assert p["dest"] == "Home"
    assert self.nav.route.nodes[-1] == self.node(0, 2)

  def test_load_place(self):
    self.params.put("NavHome", json.dumps({"lat": 1.5, "lon": -2.5}))
    assert load_place(self.params, "NavHome") == {"lat": 1.5, "lon": -2.5, "name": "NavHome"}
    self.params.put("NavHome", "garbage")
    assert load_place(self.params, "NavHome") is None
    assert load_place(self.params, "NavWork") is None


class TestRouteTracker(GridTest):
  def test_tracker_follows_route(self):
    route = find_route(self.m, self.node(1, 0), self.node(1, 2))
    tr = RouteTracker(self.m, route)
    assert tr.update(LAT0 + D, LON0 + D) < 1.0
    assert abs(tr.dist_along - 0.5 * route.total_dist) < 2.0
    assert abs(tr.remaining_m() - 0.5 * route.total_dist) < 2.0
    assert tr.eta_s() > 0
    # 60 m south of the road is off route
    assert tr.update(LAT0 + D - 60 / 111000, LON0 + D) > 50
