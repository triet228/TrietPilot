# openpilot/selfdrive/navd/offline_map.py

"""Offline road map for a fixed area, built from OpenStreetMap by build_map.py.

File format (gzipped JSON):
  classes: list of highway class names, indexed by way["c"]
  lat, lon: node coordinates as integers in 1e-6 degrees
  ways: list of {n: [node idx...], s: speed limit mph, x: limit was explicit in OSM,
                 c: class idx, o: oneway (0 both, 1 forward, -1 reverse), name: str}

Everything runs in memory with a coarse grid index so lookups are a few hundred
microseconds. Distances use a local equirectangular projection, accurate to well
under a metre across a city-sized area.
"""

import gzip
import json
import math
import os

import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_MAP = os.path.join(DATA_DIR, "annarbor_ypsilanti.json.gz")

EARTH_RADIUS = 6371000.0
GRID_DEG = 0.004  # ~450 m cells

# classes treated as freeway for the cruise offset. trunk covers US-23 / US-12 style divided highways.
FREEWAY_CLASSES = ("motorway", "motorway_link", "trunk", "trunk_link")

# beyond this the car is not considered to be on any known road
MAX_MATCH_DIST = 30.0  # m
# penalty added to distance when the road runs across the direction of travel
HEADING_PENALTY = 25.0  # m


def local_xy(lat, lon, lat0, lon0):
  """Metres east/north of (lat0, lon0)."""
  x = math.radians(lon - lon0) * EARTH_RADIUS * math.cos(math.radians(lat0))
  y = math.radians(lat - lat0) * EARTH_RADIUS
  return x, y


def haversine(lat1, lon1, lat2, lon2):
  p1, p2 = math.radians(lat1), math.radians(lat2)
  dphi = p2 - p1
  dl = math.radians(lon2 - lon1)
  a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * EARTH_RADIUS * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
  """Initial bearing from point 1 to point 2, degrees clockwise from north."""
  p1, p2 = math.radians(lat1), math.radians(lat2)
  dl = math.radians(lon2 - lon1)
  x = math.sin(dl) * math.cos(p2)
  y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
  return math.degrees(math.atan2(x, y)) % 360.0


def angle_diff(a, b):
  """Smallest absolute difference between two bearings, degrees."""
  return abs((a - b + 180.0) % 360.0 - 180.0)


class Match:
  def __init__(self, way_idx, seg_idx, dist, forward, frac):
    self.way_idx = way_idx
    self.seg_idx = seg_idx  # segment between way nodes seg_idx and seg_idx + 1
    self.dist = dist        # metres from the query point to the segment
    self.forward = forward  # travelling in node order
    self.frac = frac        # position along the segment, 0..1


class OfflineMap:
  def __init__(self, path=DEFAULT_MAP):
    with gzip.open(path, "rt", encoding="utf-8") as f:
      data = json.load(f)
    self.classes = data["classes"]
    self.lat = np.asarray(data["lat"], dtype=np.float64) * 1e-6
    self.lon = np.asarray(data["lon"], dtype=np.float64) * 1e-6
    self.ways = data["ways"]

    self.lat0 = float(self.lat.mean())
    self.lon0 = float(self.lon.mean())
    self.cos_lat0 = math.cos(math.radians(self.lat0))
    self.x = np.radians(self.lon - self.lon0) * EARTH_RADIUS * self.cos_lat0
    self.y = np.radians(self.lat - self.lat0) * EARTH_RADIUS

    self._build_grid()
    self._adjacency = None

  # ---- spatial index -------------------------------------------------------

  def _cell(self, lat, lon):
    return (int(math.floor(lat / GRID_DEG)), int(math.floor(lon / GRID_DEG)))

  def _build_grid(self):
    self.grid = {}
    for wi, way in enumerate(self.ways):
      n = way["n"]
      for si in range(len(n) - 1):
        a, b = n[si], n[si + 1]
        c0 = self._cell(self.lat[a], self.lon[a])
        c1 = self._cell(self.lat[b], self.lon[b])
        for ci in range(min(c0[0], c1[0]), max(c0[0], c1[0]) + 1):
          for cj in range(min(c0[1], c1[1]), max(c0[1], c1[1]) + 1):
            self.grid.setdefault((ci, cj), []).append((wi, si))

  def _candidates(self, lat, lon):
    ci, cj = self._cell(lat, lon)
    for di in (-1, 0, 1):
      for dj in (-1, 0, 1):
        yield from self.grid.get((ci + di, cj + dj), ())

  def to_xy(self, lat, lon):
    return local_xy(lat, lon, self.lat0, self.lon0)

  # ---- map matching --------------------------------------------------------

  def match(self, lat, lon, bearing=None, max_dist=MAX_MATCH_DIST):
    """Nearest road segment to a point, or None. A bearing (degrees) penalizes cross roads."""
    px, py = self.to_xy(lat, lon)
    best = None
    best_score = None
    for wi, si in self._candidates(lat, lon):
      n = self.ways[wi]["n"]
      a, b = n[si], n[si + 1]
      ax, ay, bx, by = self.x[a], self.y[a], self.x[b], self.y[b]
      dx, dy = bx - ax, by - ay
      seg_len2 = dx * dx + dy * dy
      if seg_len2 <= 0.0:
        continue
      t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
      t = min(1.0, max(0.0, t))
      cx, cy = ax + t * dx, ay + t * dy
      dist = math.hypot(px - cx, py - cy)
      if dist > max_dist:
        continue

      forward = True
      score = dist
      if bearing is not None:
        seg_bearing = math.degrees(math.atan2(dx, dy)) % 360.0
        diff_fwd = angle_diff(bearing, seg_bearing)
        diff_rev = angle_diff(bearing, (seg_bearing + 180.0) % 360.0)
        oneway = self.ways[wi]["o"]
        if oneway == 1:
          diff = diff_fwd
        elif oneway == -1:
          diff = diff_rev
          forward = False
        else:
          forward = diff_fwd <= diff_rev
          diff = min(diff_fwd, diff_rev)
        if diff > 45.0:
          score += HEADING_PENALTY

      if best_score is None or score < best_score:
        best_score = score
        best = Match(wi, si, dist, forward, t)
    return best

  # ---- attributes ----------------------------------------------------------

  def speed_limit_mph(self, way_idx):
    return self.ways[way_idx]["s"]

  def road_class(self, way_idx):
    return self.classes[self.ways[way_idx]["c"]]

  def is_freeway(self, way_idx):
    return self.road_class(way_idx) in FREEWAY_CLASSES

  def road_name(self, way_idx):
    return self.ways[way_idx]["name"]

  def node_latlon(self, node_idx):
    return float(self.lat[node_idx]), float(self.lon[node_idx])

  # ---- graph for routing ---------------------------------------------------

  def adjacency(self):
    """node idx -> list of (neighbor node idx, length m, way idx). Built lazily, respects oneway."""
    if self._adjacency is not None:
      return self._adjacency
    adj = {}
    for wi, way in enumerate(self.ways):
      n = way["n"]
      ow = way["o"]
      for si in range(len(n) - 1):
        a, b = n[si], n[si + 1]
        length = math.hypot(self.x[b] - self.x[a], self.y[b] - self.y[a])
        if ow >= 0:
          adj.setdefault(a, []).append((b, length, wi))
        if ow <= 0:
          adj.setdefault(b, []).append((a, length, wi))
    self._adjacency = adj
    return adj

  def segment_speed_ms(self, way_idx):
    return self.ways[way_idx]["s"] * 0.44704
