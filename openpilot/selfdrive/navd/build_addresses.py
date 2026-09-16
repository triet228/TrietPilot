# openpilot/selfdrive/navd/build_addresses.py

"""Converts an Overpass dump of addressed features into the compact offline
address book used by geocoder.py.

Usage:
  python build_addresses.py overpass_addresses.json openpilot/selfdrive/navd/data/annarbor_ypsilanti_addresses.json.gz

Overpass query (same bbox as the road map):

  [out:json][timeout:600];
  nwr["addr:housenumber"]["addr:street"](42.17,-83.85,42.36,-83.53);
  out center tags;

Nodes carry lat/lon directly; ways and relations carry a "center". Features with
a name (shops, schools, restaurants) are also indexed by that name so a place
can be typed instead of a house number.
"""

import gzip
import json
import sys

from openpilot.selfdrive.navd.geocoder import normalize_street


def build(elements):
  streets = {}
  cities = {}
  entries = []
  names = []

  def idx(table, key):
    if key not in table:
      table[key] = len(table)
    return table[key]

  for el in elements:
    tags = el.get("tags", {})
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if not street or not number:
      continue
    if el.get("type") == "node":
      lat, lon = el.get("lat"), el.get("lon")
    else:
      c = el.get("center") or {}
      lat, lon = c.get("lat"), c.get("lon")
    if lat is None or lon is None:
      continue
    lat_e6, lon_e6 = int(round(lat * 1e6)), int(round(lon * 1e6))
    city = tags.get("addr:city", "")
    entries.append([idx(streets, street), number.strip(), lat_e6, lon_e6, idx(cities, city)])
    name = tags.get("name")
    if name:
      names.append([name.strip(), lat_e6, lon_e6, f"{number.strip()} {street}"])

  street_list = [None] * len(streets)
  for s, i in streets.items():
    street_list[i] = s
  city_list = [None] * len(cities)
  for c, i in cities.items():
    city_list[i] = c

  return {
    "version": 1,
    "streets": street_list,
    "streets_norm": [normalize_street(s) for s in street_list],
    "cities": city_list,
    "entries": entries,
    "names": names,
  }


def main():
  if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)
  with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
  out = build(data["elements"])
  with gzip.open(sys.argv[2], "wt", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
  print(f"{len(out['entries'])} addresses on {len(out['streets'])} streets, {len(out['names'])} named places -> {sys.argv[2]}")


if __name__ == "__main__":
  main()
