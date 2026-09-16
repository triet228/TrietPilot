# openpilot/selfdrive/navd/geocoder.py

"""Offline address lookup on the bundled address book.

Typed input like "1234 Packard St", "1234 packard", "1234 Packard St, Ypsilanti"
or a place name like "Zingerman's" is resolved to a lat/lon. Street names are
normalized so common abbreviations and directions match however they were typed.

Resolution order:
  1. exact house number on the normalized street
  2. nearest house number on that street (marked approximate)
  3. same again on the closest-spelled street if the typed one is unknown
  4. named place (shop, school, restaurant) by exact, then fuzzy, name
"""

import difflib
import gzip
import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_ADDRESSES = os.path.join(DATA_DIR, "annarbor_ypsilanti_addresses.json.gz")

STREET_ABBREVIATIONS = {
  "st": "street", "str": "street", "ave": "avenue", "av": "avenue", "rd": "road", "dr": "drive", "blvd": "boulevard",
  "ln": "lane", "ct": "court", "pkwy": "parkway", "pky": "parkway", "hwy": "highway", "cir": "circle", "pl": "place",
  "trl": "trail", "tr": "trail", "ter": "terrace", "terr": "terrace", "sq": "square", "xing": "crossing",
  "n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
  "mt": "mount", "ft": "fort", "hts": "heights",
}

_NUMBER_RE = re.compile(r"^\s*(\d+[a-zA-Z]?)\s+(.+)$")
# a nearest-number match further than this from the typed number is more likely a wrong street than a gap in the data
MAX_NUMBER_GAP = 300
# how close a typed street must be spelled to an existing one; 0.75 let "nowhere road" match "tower road"
STREET_FUZZ_CUTOFF = 0.85
_HOUSE_NUM_RE = re.compile(r"\d+")


def normalize_street(name):
  words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
  return " ".join(STREET_ABBREVIATIONS.get(w, w) for w in words)


def normalize_name(name):
  return " ".join(re.sub(r"[^a-z0-9 ]", " ", name.lower()).split())


def parse_query(text):
  """('1234', 'packard street', 'ypsilanti') from '1234 Packard St, Ypsilanti'. Number and city may be None."""
  text = text.strip()
  city = None
  if "," in text:
    text, city = (p.strip() for p in text.rsplit(",", 1))
    city = normalize_name(city) or None
  m = _NUMBER_RE.match(text)
  if m:
    return m.group(1).lower(), normalize_street(m.group(2)), city
  return None, normalize_street(text), city


def house_number_value(number):
  m = _HOUSE_NUM_RE.search(number)
  return int(m.group(0)) if m else None


class Geocoder:
  def __init__(self, path=DEFAULT_ADDRESSES):
    with gzip.open(path, "rt", encoding="utf-8") as f:
      data = json.load(f)
    self.streets = data["streets"]
    self.streets_norm = data["streets_norm"]
    self.cities = data["cities"]
    self.by_street = {}
    for street_idx, number, lat_e6, lon_e6, city_idx in data["entries"]:
      norm = self.streets_norm[street_idx]
      self.by_street.setdefault(norm, []).append((number, lat_e6 * 1e-6, lon_e6 * 1e-6, city_idx, street_idx))
    self.names = [(normalize_name(n), n, lat_e6 * 1e-6, lon_e6 * 1e-6, addr) for n, lat_e6, lon_e6, addr in data["names"]]
    self._name_keys = [n[0] for n in self.names]

  def _result(self, lat, lon, label, approx):
    return {"lat": lat, "lon": lon, "label": label, "approx": approx}

  def _lookup_on_street(self, norm_street, number, city):
    entries = self.by_street.get(norm_street)
    if not entries:
      return None
    if city:
      filtered = [e for e in entries if normalize_name(self.cities[e[3]] or "") == city]
      entries = filtered or entries
    street_name = self.streets[entries[0][4]]

    exact = [e for e in entries if e[0].lower() == number]
    if exact:
      e = exact[0]
      return self._result(e[1], e[2], f"{e[0]} {street_name}", False)

    want = house_number_value(number)
    if want is None:
      return None
    scored = [(abs(house_number_value(e[0]) - want), e) for e in entries if house_number_value(e[0]) is not None]
    if not scored:
      return None
    gap, e = min(scored, key=lambda t: t[0])
    if gap > MAX_NUMBER_GAP:
      return None
    return self._result(e[1], e[2], f"near {e[0]} {street_name}", True)

  def lookup(self, text):
    """Best match for the typed text, or None."""
    if not text or not text.strip():
      return None
    number, norm_street, city = parse_query(text)

    if number is not None:
      hit = self._lookup_on_street(norm_street, number, city)
      if hit:
        return hit
      close = difflib.get_close_matches(norm_street, list(self.by_street.keys()), n=1, cutoff=STREET_FUZZ_CUTOFF)
      if close:
        hit = self._lookup_on_street(close[0], number, city)
        if hit:
          hit["approx"] = True
          return hit

    # a place name, or a street without a number
    key = normalize_name(text.split(",")[0])
    for norm, name, lat, lon, addr in self.names:
      if norm == key:
        return self._result(lat, lon, f"{name}, {addr}", False)
    close = difflib.get_close_matches(key, self._name_keys, n=1, cutoff=0.8)
    if close:
      for norm, name, lat, lon, addr in self.names:
        if norm == close[0]:
          return self._result(lat, lon, f"{name}, {addr}", True)
    contains = [n for n in self.names if key in n[0]] if len(key) >= 4 else []
    if len(contains) == 1:
      norm, name, lat, lon, addr = contains[0]
      return self._result(lat, lon, f"{name}, {addr}", True)
    return None
