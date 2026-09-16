# openpilot/selfdrive/navd/tests/test_geocoder.py

import gzip
import json
import os
import tempfile

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.navd.build_addresses import build
from openpilot.selfdrive.navd.geocoder import Geocoder, normalize_street, parse_query


def node(hn, street, lat, lon, city="Ann Arbor", name=None):
  tags = {"addr:housenumber": hn, "addr:street": street, "addr:city": city}
  if name:
    tags["name"] = name
  return {"type": "node", "id": hash((hn, street)) & 0xffff, "lat": lat, "lon": lon, "tags": tags}


def way(hn, street, lat, lon, city="Ypsilanti"):
  return {"type": "way", "id": 1, "center": {"lat": lat, "lon": lon},
          "tags": {"addr:housenumber": hn, "addr:street": street, "addr:city": city}}


def make_geocoder():
  elements = [
    node("1200", "Packard Street", 42.2650, -83.7300),
    node("1234", "Packard Street", 42.2655, -83.7290),
    node("1300", "Packard Street", 42.2660, -83.7280),
    node("100", "South Main Street", 42.2810, -83.7480),
    way("500", "West Michigan Avenue", 42.2400, -83.6150),
    node("3711", "Plaza Drive", 42.2328, -83.7478, name="Zingerman's Bakehouse"),
    node("2501", "Jackson Avenue", 42.2800, -83.7800, name="Westgate Library"),
  ]
  data = build(elements)
  fd, path = tempfile.mkstemp(suffix=".json.gz")
  os.close(fd)
  with gzip.open(path, "wt", encoding="utf-8") as f:
    json.dump(data, f)
  return path


class TestNormalize(OpenpilotTestCase):
  def test_street_abbreviations(self):
    assert normalize_street("Packard St") == "packard street"
    assert normalize_street("S. Main St.") == "south main street"
    assert normalize_street("W Michigan Ave") == "west michigan avenue"
    assert normalize_street("Plymouth Rd") == "plymouth road"
    assert normalize_street("Huron Pkwy") == "huron parkway"

  def test_parse_query(self):
    assert parse_query("1234 Packard St") == ("1234", "packard street", None)
    assert parse_query("1234 Packard St, Ypsilanti") == ("1234", "packard street", "ypsilanti")
    assert parse_query("12A Main St") == ("12a", "main street", None)
    # street normalization expands a lone "s" to south; place names go through normalize_name instead
    assert parse_query("Zingerman's") == (None, "zingerman south", None)


class TestGeocoder(OpenpilotTestCase):
  def setup_method(self):
    self.path = make_geocoder()
    self.g = Geocoder(self.path)

  def teardown_method(self):
    os.remove(self.path)

  def test_exact(self):
    hit = self.g.lookup("1234 Packard St")
    assert hit["label"] == "1234 Packard Street" and not hit["approx"]
    assert abs(hit["lat"] - 42.2655) < 1e-6

  def test_abbreviations_and_case(self):
    assert self.g.lookup("100 s main st")["label"] == "100 South Main Street"
    assert self.g.lookup("500 W MICHIGAN AVE")["label"] == "500 West Michigan Avenue"

  def test_nearest_number_is_approximate(self):
    hit = self.g.lookup("1250 Packard Street")
    assert hit["approx"]
    assert hit["label"] == "near 1234 Packard Street"

  def test_fuzzy_street(self):
    hit = self.g.lookup("1234 Packerd Street")
    assert hit["approx"] and "Packard" in hit["label"]

  def test_city_filter(self):
    hit = self.g.lookup("500 W Michigan Ave, Ypsilanti")
    assert hit["label"] == "500 West Michigan Avenue"

  def test_place_name(self):
    hit = self.g.lookup("Zingerman's Bakehouse")
    assert not hit["approx"] and hit["label"].startswith("Zingerman's Bakehouse, 3711 Plaza Drive")
    fuzzy = self.g.lookup("zingermans bakehous")
    assert fuzzy["approx"] and "Zingerman" in fuzzy["label"]
    partial = self.g.lookup("westgate")
    assert "Westgate Library" in partial["label"]

  def test_far_number_is_rejected(self):
    # 9999 is nowhere near the 1200-1300 block that exists, better to say not found than send the car off
    assert self.g.lookup("9999 Packard Street") is None

  def test_unknown(self):
    assert self.g.lookup("9999 Nowhere Boulevard") is None
    assert self.g.lookup("") is None
    assert self.g.lookup("xyz") is None
