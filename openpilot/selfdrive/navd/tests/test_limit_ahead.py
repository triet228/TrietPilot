# openpilot/selfdrive/navd/tests/test_limit_ahead.py

import datetime
import gzip
import json
import math
import os
import tempfile

from openpilot.common.constants import CV
from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_map import build, parse_maxspeed
from openpilot.selfdrive.navd.conditional_limit import parse_conditional, active_limit
from openpilot.selfdrive.navd.offline_map import OfflineMap, USEasternFallback
from openpilot.selfdrive.navd.curve_speed import lookahead
from openpilot.selfdrive.navd.limit_ahead import limit_ahead_speed, A_DECEL, LOOKAHEAD_M
from openpilot.selfdrive.navd.speedlimitd import SpeedLimitTracker, cruise_target_kph
from openpilot.selfdrive.controls.lib.longitudinal_planner import map_speed_cap_from_payload

LAT0, LON0 = 42.28, -83.74
M_PER_DEG_LAT = 111000.0
SCHOOL_TAG = "25 mph @ (Mo-Fr 08:20-08:50,15:45-16:15; PH off; SH off)"


def lat_at(y_m):
  return LAT0 + y_m / M_PER_DEG_LAT


def lon_at(x_m):
  return LON0 + x_m / (M_PER_DEG_LAT * math.cos(math.radians(LAT0)))


def way(wid, xs, node_ids, cls="secondary", **tags):
  return {"type": "way", "id": wid, "tags": {"highway": cls, **tags}, "nodes": node_ids,
          "geometry": [{"lat": lat_at(0), "lon": lon_at(x)} for x in xs]}


def write_map(elements):
  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path


def mph(v):
  return v * CV.MPH_TO_MS


class TestConditionalLimit(OpenpilotTestCase):
  def test_parse_school_zone_tag(self):
    rules = parse_conditional(SCHOOL_TAG, parse_maxspeed)
    assert rules == [{"s": 25, "d": [0, 1, 2, 3, 4], "t": [[500, 530], [945, 975]]}]

  def test_parse_variants(self):
    assert parse_conditional(None, parse_maxspeed) == []
    assert parse_conditional("none @ (Mo-Fr 08:00-09:00)", parse_maxspeed) == []
    # no day spec means every day, no time spec means all day
    assert parse_conditional("30 mph @ 07:00-19:00", parse_maxspeed) == [{"s": 30, "d": list(range(7)), "t": [[420, 1140]]}]
    assert parse_conditional("30 mph @ (Sa,Su)", parse_maxspeed) == [{"s": 30, "d": [5, 6], "t": [[0, 1440]]}]
    # two rules in one tag
    two = parse_conditional("20 mph @ (Mo-Fr 07:00-08:00); 30 mph @ (Sa-Su 10:00-12:00)", parse_maxspeed)
    assert [r["s"] for r in two] == [20, 30]
    # gibberish never produces a rule
    assert parse_conditional("25 mph @ (wet)", parse_maxspeed) == []

  def test_active_limit_windows(self):
    rules = parse_conditional(SCHOOL_TAG, parse_maxspeed)
    tue = datetime.datetime(2026, 9, 15)  # a Tuesday
    assert active_limit(rules, tue.replace(hour=8, minute=30)) == 25
    assert active_limit(rules, tue.replace(hour=15, minute=50)) == 25
    assert active_limit(rules, tue.replace(hour=8, minute=50)) is None  # end is exclusive
    assert active_limit(rules, tue.replace(hour=12, minute=0)) is None
    sat = datetime.datetime(2026, 9, 19, 8, 30)
    assert active_limit(rules, sat) is None
    assert active_limit(rules, None) is None
    assert active_limit([], tue) is None

  def test_overnight_window_wraps(self):
    rules = parse_conditional("20 mph @ (22:00-06:00)", parse_maxspeed)
    assert active_limit(rules, datetime.datetime(2026, 9, 15, 23, 0)) == 20
    assert active_limit(rules, datetime.datetime(2026, 9, 15, 3, 0)) == 20
    assert active_limit(rules, datetime.datetime(2026, 9, 15, 12, 0)) is None


class TestFallbackTimezone(OpenpilotTestCase):
  def test_us_eastern_dst_rule(self):
    tz = USEasternFallback()
    summer = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=tz)
    winter = datetime.datetime(2026, 1, 15, 12, 0, tzinfo=tz)
    assert summer.utcoffset() == datetime.timedelta(hours=-4) and summer.tzname() == "EDT"
    assert winter.utcoffset() == datetime.timedelta(hours=-5) and winter.tzname() == "EST"
    # 2026: DST starts March 8 and ends November 1
    assert datetime.datetime(2026, 3, 8, 1, 59, tzinfo=tz).utcoffset() == datetime.timedelta(hours=-5)
    assert datetime.datetime(2026, 3, 8, 3, 0, tzinfo=tz).utcoffset() == datetime.timedelta(hours=-4)
    assert datetime.datetime(2026, 11, 1, 1, 59, tzinfo=tz).utcoffset() == datetime.timedelta(hours=-4)
    assert datetime.datetime(2026, 11, 1, 3, 0, tzinfo=tz).utcoffset() == datetime.timedelta(hours=-5)
    # a school-zone morning in UTC lands in the window in local time
    utc = datetime.datetime(2026, 9, 15, 12, 30, tzinfo=datetime.UTC)
    local = utc.astimezone(tz)
    assert (local.hour, local.minute) == (8, 30)


class TestLimitAheadMath(OpenpilotTestCase):
  def test_only_lower_targets_count(self):
    targets = {1: mph(55), 2: mph(35), 3: mph(65)}
    v = limit_ahead_speed([(1, 100.0), (2, 200.0), (3, 300.0)], mph(55), lambda wi, when: targets[wi])
    assert abs(v - math.sqrt(mph(35) ** 2 + 2 * A_DECEL * 200.0)) < 1e-9
    assert limit_ahead_speed([(3, 300.0)], mph(55), lambda wi, when: targets[wi]) is None
    assert limit_ahead_speed([], mph(55), lambda wi, when: targets[wi]) is None

  def test_closest_binding_drop_wins(self):
    targets = {1: mph(35), 2: mph(25)}
    v = limit_ahead_speed([(1, 50.0), (2, 400.0)], mph(55), lambda wi, when: targets[wi])
    assert abs(v - math.sqrt(mph(35) ** 2 + 2 * A_DECEL * 50.0)) < 1e-9

  def test_at_the_sign_equals_the_new_target(self):
    v = limit_ahead_speed([(1, 0.0)], mph(55), lambda wi, when: mph(35))
    assert abs(v - mph(35)) < 1e-9


class TestLimitAheadOnMap(OpenpilotTestCase):
  """Straight road: 45 mph for 500 m, then a school zone way (30, 25 in hours) for 500 m, then 25 mph."""

  def setup_method(self):
    self.path = write_map([
      way(1, (0, 250, 500), [1, 2, 3], maxspeed="45 mph", name="Fast"),
      way(2, (500, 750, 1000), [3, 4, 5], cls="tertiary", maxspeed="30 mph", name="School", **{"maxspeed:conditional": SCHOOL_TAG}),
      way(3, (1000, 1250, 1500), [5, 6, 7], maxspeed="25 mph", name="Slow"),
    ])
    self.m = OfflineMap(self.path)
    self.fast = next(i for i, w in enumerate(self.m.ways) if w["name"] == "Fast")
    self.school = next(i for i, w in enumerate(self.m.ways) if w["name"] == "School")
    self.slow = next(i for i, w in enumerate(self.m.ways) if w["name"] == "Slow")
    self.in_hours = datetime.datetime(2026, 9, 15, 8, 30)
    self.off_hours = datetime.datetime(2026, 9, 15, 12, 0)

  def teardown_method(self):
    os.remove(self.path)

  def test_map_stores_and_evaluates_conditional_limit(self):
    assert self.m.has_conditional_limit(self.school)
    assert not self.m.has_conditional_limit(self.slow)
    assert self.m.speed_limit_mph(self.school) == 30
    assert self.m.speed_limit_mph(self.school, self.off_hours) == 30
    assert self.m.speed_limit_mph(self.school, self.in_hours) == 25
    assert self.m.speed_limit_mph(self.slow, self.in_hours) == 25
    assert self.m.local_now().tzinfo is not None

  def test_lookahead_reports_ways_with_start_distance(self):
    match = self.m.match(lat_at(0), lon_at(100), bearing=90)
    pts, ways = lookahead(self.m, match, max_dist=2000)
    assert [wi for wi, _ in ways] == [self.school, self.slow]
    assert abs(ways[0][1] - 400.0) < 3.0
    assert abs(ways[1][1] - 900.0) < 3.0
    assert pts[-1][2] >= ways[1][1]

  def drive(self, x_m, now, tracker=None):
    tracker = tracker or SpeedLimitTracker(self.m)
    p = None
    for _ in range(2):
      p = tracker.update(lat_at(0), lon_at(x_m), 90, now=now)
    return tracker, p

  @staticmethod
  def approach_kph(limit_mph, dist):
    v = math.sqrt((cruise_target_kph(limit_mph, False) * CV.KPH_TO_MS) ** 2 + 2 * A_DECEL * dist)
    return round(v * CV.MS_TO_KPH, 1)

  def test_pre_slow_ahead_of_drop(self):
    _, p = self.drive(300.0, self.off_hours)
    assert p["road"] == "Fast" and p["target_kph"] == cruise_target_kph(45, False)
    assert abs(p["limit_ahead_kph"] - self.approach_kph(30, 200.0)) < 0.2
    # already below the current target, so the planner holds the car back from here on
    assert p["limit_ahead_kph"] < p["target_kph"]

  def test_no_cap_far_from_the_drop_or_after_the_last_one(self):
    _, p = self.drive(500.0 - LOOKAHEAD_M - 50.0, self.off_hours)
    assert p["road"] == "Fast"
    assert "limit_ahead_kph" not in p
    _, p = self.drive(1200.0, self.off_hours)
    assert p["road"] == "Slow"
    assert "limit_ahead_kph" not in p

  def test_school_zone_lowers_the_target_only_in_hours(self):
    _, off = self.drive(300.0, self.off_hours)
    _, on = self.drive(300.0, self.in_hours)
    assert abs(off["limit_ahead_kph"] - self.approach_kph(30, 200.0)) < 0.2
    assert abs(on["limit_ahead_kph"] - self.approach_kph(25, 200.0)) < 0.2
    assert on["limit_ahead_kph"] < off["limit_ahead_kph"]
    # inside the zone the published limit is the conditional one during its hours
    _, p = self.drive(700.0, self.in_hours)
    assert p["road"] == "School" and p["limit_mph"] == 25 and p["school_zone"] is True
    assert p["target_kph"] == cruise_target_kph(25, False)
    _, p = self.drive(700.0, self.off_hours)
    assert p["limit_mph"] == 30 and p["school_zone"] is False
    # in hours the school zone already is 25, so the 25 mph road after it is not a drop
    _, p = self.drive(900.0, self.in_hours)
    assert "limit_ahead_kph" not in p
    _, p = self.drive(900.0, self.off_hours)
    assert abs(p["limit_ahead_kph"] - self.approach_kph(25, 100.0)) < 0.2

  def test_cap_is_measured_against_the_matched_road(self):
    tracker, p = self.drive(450.0, self.off_hours)
    assert p["road"] == "Fast" and "limit_ahead_kph" in p
    # first frame on the school road: still publishes Fast, but nothing lower lies ahead of the
    # school road within reach, so the cap is gone rather than pinned to a stale road
    p = tracker.update(lat_at(0), lon_at(510.0), 90, now=self.off_hours)
    assert p["road"] == "Fast"
    assert "limit_ahead_kph" not in p

  def test_rise_is_rate_limited(self):
    tracker, p = self.drive(300.0, self.off_hours)
    low = p["limit_ahead_kph"]
    # jump backwards along the road (further from the sign): the cap may only rise slowly
    p = tracker.update(lat_at(0), lon_at(150.0), 90, now=self.off_hours)
    assert low < p["limit_ahead_kph"] < low + 2.0


class TestPlannerPayload(OpenpilotTestCase):
  def test_min_of_both_caps(self):
    assert map_speed_cap_from_payload(b'{"valid": true, "curve_speed_kph": 40.5}') == 40.5
    assert map_speed_cap_from_payload(b'{"valid": true, "limit_ahead_kph": 50.0}') == 50.0
    assert map_speed_cap_from_payload(b'{"valid": true, "curve_speed_kph": 40.5, "limit_ahead_kph": 30.0}') == 30.0
    assert map_speed_cap_from_payload(b'{"valid": true}') is None
    assert map_speed_cap_from_payload(b'{"valid": false, "limit_ahead_kph": 30.0}') is None
    assert map_speed_cap_from_payload(b'nope') is None
