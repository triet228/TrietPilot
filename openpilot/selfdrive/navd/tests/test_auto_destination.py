# openpilot/selfdrive/navd/tests/test_auto_destination.py

import json

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.auto_destination import auto_destination, RADIUS_M, WINDOW_S
from openpilot.selfdrive.navd.navd import Navigator, OFF_ROUTE_DIST, OFF_ROUTE_TIME

HOME = {"lat": 42.2800, "lon": -83.7400, "name": "Home"}
WORK = {"lat": 42.2930, "lon": -83.7130, "name": "Work"}
DLAT_100M = 0.0009  # ~100 m


class FakeParams:
  def __init__(self, **values):
    self.values = {k: json.dumps(v) for k, v in values.items()}
    self.log = []

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value):
    self.values[key] = json.dumps(value)
    self.log.append(("put", key))

  def remove(self, key):
    self.values.pop(key, None)
    self.log.append(("remove", key))


class FakeFix:
  def __init__(self, lat, lon):
    self.latitude, self.longitude, self.speed, self.bearingDeg = lat, lon, 0.0, 0.0


class FakeTracker:
  """Reports a fixed distance off route and never arrives."""

  def __init__(self, off):
    self.off = off
    self.dist_along = 0.0

  def update(self, lat, lon):
    return self.off

  def remaining_m(self):
    return 5000.0

  def eta_s(self):
    return 400.0

  def upcoming(self):
    return []


class TestAutoDestination(OpenpilotTestCase):
  def test_home_to_work_and_back(self):
    assert auto_destination(HOME["lat"] + DLAT_100M, HOME["lon"], HOME, WORK)["name"] == "Work"
    assert auto_destination(WORK["lat"], WORK["lon"] + 0.001, HOME, WORK)["name"] == "Home"

  def test_no_guess_elsewhere_or_unconfigured(self):
    assert auto_destination(42.25, -83.70, HOME, WORK) is None
    assert auto_destination(HOME["lat"], HOME["lon"], None, WORK) is None
    assert auto_destination(HOME["lat"], HOME["lon"], HOME, None) is None
    near_work = {**WORK, "lat": HOME["lat"] + 0.003, "lon": HOME["lon"]}  # ~330 m from home
    assert auto_destination(HOME["lat"], HOME["lon"], HOME, near_work) is None

  def test_radius(self):
    far = HOME["lat"] + (RADIUS_M + 50.0) / 111000.0
    assert auto_destination(far, HOME["lon"], HOME, WORK) is None


class TestNavigatorAutoDestination(OpenpilotTestCase):
  def make_nav(self, **params):
    nav = Navigator(None, FakeParams(NavHome=HOME, NavWork=WORK, **params))
    nav._plan = lambda fix, now: None  # routing needs the map; the tests only care about the destination
    return nav

  def test_guess_from_home_once_per_drive(self):
    nav = self.make_nav()
    at_home = FakeFix(HOME["lat"] + DLAT_100M / 2, HOME["lon"])
    p = nav.update(at_home, 100.0)
    assert p["active"] and p["dest"] == "Work"
    assert nav.is_auto
    assert json.loads(nav.params.values["NavDestination"])["name"] == "Work"
    # driver cancels: the same drive does not guess again
    nav.params.remove("NavDestination")
    p = nav.update(at_home, 101.0)
    assert not p["active"]
    assert ("put", "NavDestination") not in nav.params.log[2:]

  def test_no_guess_without_places_or_away_from_them(self):
    nav = Navigator(None, FakeParams())
    nav._plan = lambda fix, now: None
    assert not nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0)["active"]
    nav = self.make_nav()
    assert not nav.update(FakeFix(42.25, -83.70), 100.0)["active"]
    assert nav.params.log == []

  def test_guess_window_expires(self):
    nav = self.make_nav()
    nav.update(FakeFix(42.25, -83.70), 100.0)  # first fix, away from both
    assert not nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0 + WINDOW_S + 1.0)["active"]
    nav = self.make_nav()
    nav.update(FakeFix(42.25, -83.70), 100.0)
    assert nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0 + WINDOW_S / 2)["active"]

  def test_disabled(self):
    nav = self.make_nav()
    nav.auto_home_work = False
    assert not nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0)["active"]

  def test_manual_destination_is_never_replaced(self):
    nav = self.make_nav(NavDestination={"lat": 42.25, "lon": -83.70, "name": "Gym"})
    p = nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0)
    assert p["dest"] == "Gym" and not nav.is_auto

  def test_off_route_gives_up_only_for_a_guess(self):
    nav = self.make_nav()
    nav.update(FakeFix(HOME["lat"], HOME["lon"]), 100.0)
    nav.route = object()
    nav.tracker = FakeTracker(OFF_ROUTE_DIST + 10.0)
    nav.status = "routing"
    away = FakeFix(42.27, -83.75)
    nav.update(away, 200.0)
    p = nav.update(away, 200.0 + OFF_ROUTE_TIME + 1.0)
    assert not p["active"] and nav.status == "idle"
    assert "NavDestination" not in nav.params.values
    # a destination the driver chose keeps re-routing instead
    nav = self.make_nav(NavDestination={"lat": 42.25, "lon": -83.70, "name": "Gym"})
    nav.update(away, 100.0)
    nav.route = object()
    nav.tracker = FakeTracker(OFF_ROUTE_DIST + 10.0)
    nav.status = "routing"
    nav.update(away, 200.0)
    p = nav.update(away, 200.0 + OFF_ROUTE_TIME + 1.0)
    assert p["active"] and p["status"] == "off_route"
    assert "NavDestination" in nav.params.values
