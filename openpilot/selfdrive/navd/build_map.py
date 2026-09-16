# openpilot/selfdrive/navd/build_map.py

"""Converts an Overpass API JSON dump of roads into the compact offline map used
by speedlimitd and navd.

Usage:
  python build_map.py overpass.json openpilot/selfdrive/navd/data/annarbor_ypsilanti.json.gz

To regenerate or widen the area, run this Overpass query (adjust the bbox):

  [out:json][timeout:600];
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|
                   secondary|secondary_link|tertiary|tertiary_link|unclassified|
                   residential|living_street)$"](42.17,-83.85,42.36,-83.53);
  out geom;

`out geom` is required: it includes both node ids (for graph connectivity) and
coordinates. The output format is documented in offline_map.py.
"""

import gzip
import json
import re
import sys

# highway classes, index is what gets stored in the map file
ROAD_CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
                "residential", "living_street"]

# Michigan statutory / typical limits, mph, used when OSM has no maxspeed tag
DEFAULT_SPEED_MPH = {
  "motorway": 70, "motorway_link": 45,
  "trunk": 55, "trunk_link": 40,
  "primary": 45, "primary_link": 35,
  "secondary": 40, "secondary_link": 30,
  "tertiary": 35, "tertiary_link": 25,
  "unclassified": 35,
  "residential": 25,
  "living_street": 15,
}

_MAXSPEED_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?\s*$", re.IGNORECASE)


def parse_maxspeed(tag):
  """Returns speed in mph or None. OSM values look like '45 mph', '50', 'signals'."""
  if not tag:
    return None
  m = _MAXSPEED_RE.match(tag)
  if not m:
    return None
  val = float(m.group(1))
  unit = (m.group(2) or "km/h").lower()
  if unit != "mph":
    val = val / 1.609344
  return int(round(val))


def parse_oneway(tags):
  """0 two-way, 1 forward only (node order), -1 reverse only."""
  ow = tags.get("oneway")
  if ow in ("yes", "true", "1"):
    return 1
  if ow == "-1":
    return -1
  if ow == "no":
    return 0
  # OSM convention: motorways and roundabouts are one-way unless tagged otherwise
  if tags.get("highway") in ("motorway", "motorway_link"):
    return 1
  if tags.get("junction") in ("roundabout", "circular"):
    return 1
  return 0


def build(elements):
  node_index = {}
  node_lat = []
  node_lon = []
  ways = []

  for el in elements:
    if el.get("type") != "way" or "nodes" not in el or "geometry" not in el:
      continue
    tags = el.get("tags", {})
    cls = tags.get("highway")
    if cls not in DEFAULT_SPEED_MPH:
      continue

    idxs = []
    for nid, geom in zip(el["nodes"], el["geometry"], strict=True):
      if nid not in node_index:
        node_index[nid] = len(node_lat)
        node_lat.append(int(round(geom["lat"] * 1e6)))
        node_lon.append(int(round(geom["lon"] * 1e6)))
      idxs.append(node_index[nid])
    if len(idxs) < 2:
      continue

    speed = parse_maxspeed(tags.get("maxspeed"))
    ways.append({
      "n": idxs,
      "s": speed if speed is not None else DEFAULT_SPEED_MPH[cls],
      "x": speed is not None,
      "c": ROAD_CLASSES.index(cls),
      "o": parse_oneway(tags),
      "name": tags.get("name") or tags.get("ref") or "",
    })

  return {
    "version": 1,
    "classes": ROAD_CLASSES,
    "lat": node_lat,
    "lon": node_lon,
    "ways": ways,
  }


def main():
  if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)
  with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
  out = build(data["elements"])
  with gzip.open(sys.argv[2], "wt", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))
  explicit = sum(w["x"] for w in out["ways"])
  print(f"{len(out['ways'])} ways, {len(out['lat'])} nodes, {explicit} with explicit maxspeed -> {sys.argv[2]}")


if __name__ == "__main__":
  main()
