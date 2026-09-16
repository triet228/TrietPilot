# openpilot/selfdrive/navd/tests/test_turn_speed.py

import math

from openpilot.common.constants import CV
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.turn_speed import turn_speed, TURN_SPEED, A_DECEL, LOOKAHEAD_M
from openpilot.selfdrive.navd.navd import Navigator
from openpilot.selfdrive.controls.lib.longitudinal_planner import nav_speed_cap_from_payload


def ins(kind, dist):
  return {"type": kind, "modifier": "left", "street": "Main St", "dist": dist, "node": 0}


class TestTurnSpeedMath(OpenpilotTestCase):
  def test_approach_law(self):
    v = turn_speed([ins("turn", 1200.0)], 1000.0)
    assert abs(v - math.sqrt(TURN_SPEED["turn"] ** 2 + 2 * A_DECEL * 200.0)) < 1e-9

  def test_held_at_turn_speed_through_the_node(self):
    assert turn_speed([ins("turn", 1000.0)], 1000.0) == TURN_SPEED["turn"]
    # just past the node (navd still lists it for a few metres) the cap stays at turn speed
    assert turn_speed([ins("turn", 1000.0)], 1008.0) == TURN_SPEED["turn"]

  def test_out_of_reach_and_non_corners_ignored(self):
    assert turn_speed([ins("turn", 1000.0 + LOOKAHEAD_M + 1.0)], 1000.0) is None
    assert turn_speed([ins("merge", 1050.0), ins("keep", 1080.0)], 1000.0) is None
    assert turn_speed([], 0.0) is None

  def test_most_binding_maneuver_wins(self):
    near_slight = ins("slight", 1050.0)
    far_uturn = ins("uturn", 1100.0)
    v = turn_speed([near_slight, far_uturn], 1000.0)
    expected = min(math.sqrt(TURN_SPEED["slight"] ** 2 + 2 * A_DECEL * 50.0),
                   math.sqrt(TURN_SPEED["uturn"] ** 2 + 2 * A_DECEL * 100.0))
    assert abs(v - expected) < 1e-9

  def test_type_ordering(self):
    assert TURN_SPEED["uturn"] < TURN_SPEED["arrive"] < TURN_SPEED["turn"] < TURN_SPEED["slight"] < TURN_SPEED["exit"]


class FakeTracker:
  def __init__(self, instructions, dist_along):
    self.instructions = instructions
    self.dist_along = dist_along

  def upcoming(self):
    return [i for i in self.instructions if i["dist"] - self.dist_along > -12.0]

  def remaining_m(self):
    return 5000.0

  def eta_s(self):
    return 400.0


class FakeParams:
  def get(self, key):
    return None


class TestNavdPayload(OpenpilotTestCase):
  def make_nav(self, instructions, dist_along, status="routing"):
    nav = Navigator(None, FakeParams())
    nav.dest = {"lat": 0.0, "lon": 0.0, "name": "Work"}
    nav.status = status
    nav.tracker = FakeTracker(instructions, dist_along)
    return nav

  def test_turn_speed_in_payload(self):
    nav = self.make_nav([ins("turn", 1150.0), ins("arrive", 3000.0)], 1000.0)
    p = nav.payload()
    assert p["maneuver"] == "turn" and abs(p["distance_m"] - 150.0) < 1e-9
    expected = math.sqrt(TURN_SPEED["turn"] ** 2 + 2 * A_DECEL * 150.0) * CV.MS_TO_KPH
    assert abs(p["turn_speed_kph"] - round(expected, 1)) < 0.11

  def test_no_cap_when_far_or_off_route_or_disabled(self):
    nav = self.make_nav([ins("turn", 2000.0)], 1000.0)
    assert "turn_speed_kph" not in nav.payload()
    nav = self.make_nav([ins("turn", 1100.0)], 1000.0, status="off_route")
    assert "turn_speed_kph" not in nav.payload()
    nav = self.make_nav([ins("turn", 1100.0)], 1000.0)
    nav.turn_slowdown = False
    assert "turn_speed_kph" not in nav.payload()

  def test_cap_rises_slowly_after_the_turn(self):
    nav = self.make_nav([ins("turn", 1000.0), ins("turn", 1250.0)], 1005.0)
    low = nav.payload()["turn_speed_kph"]
    assert abs(low - round(TURN_SPEED["turn"] * CV.MS_TO_KPH, 1)) < 0.11
    # first turn passed: the next one is 220 m out, but the filter only lets the cap climb a little per cycle
    nav.tracker.dist_along = 1030.0
    p = nav.payload()
    assert low < p["turn_speed_kph"] < low + 5.0


class TestPlannerPayload(OpenpilotTestCase):
  def test_nav_speed_cap(self):
    assert nav_speed_cap_from_payload(b'{"active": true, "status": "routing", "turn_speed_kph": 31.5}') == 31.5
    assert nav_speed_cap_from_payload(b'{"active": true, "status": "routing"}') is None
    assert nav_speed_cap_from_payload(b'{"active": false, "turn_speed_kph": 31.5}') is None
    assert nav_speed_cap_from_payload(b'nope') is None
