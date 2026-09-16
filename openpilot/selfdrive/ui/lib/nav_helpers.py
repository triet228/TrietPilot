# openpilot/selfdrive/ui/lib/nav_helpers.py

"""Shared helpers for the offline navigation UI: reading navd / speedlimitd payloads,
saving Home and Work from the current GPS fix, and formatting instructions."""

import json

from openpilot.selfdrive.ui.ui_state import ui_state

PLACE_KEYS = {"Home": "NavHome", "Work": "NavWork"}

MANEUVER_ARROWS = {
  ("turn", "left"): "←", ("turn", "right"): "→",
  ("slight", "left"): "↖", ("slight", "right"): "↗",
  ("keep", "left"): "↖", ("keep", "right"): "↗",
  ("exit", "left"): "↖", ("exit", "right"): "↗",
  ("merge", "left"): "↖", ("merge", "right"): "↗",
  ("uturn", "left"): "↶", ("uturn", "right"): "↷",
}


def parse_payload(raw):
  try:
    return json.loads(bytes(raw))
  except (ValueError, TypeError):
    return None


def nav_payload():
  sm = ui_state.sm
  if sm.recv_frame["customReservedRawData2"] == 0 or not sm.alive["customReservedRawData2"]:
    return None
  return parse_payload(sm["customReservedRawData2"])


def speed_limit_payload():
  sm = ui_state.sm
  if sm.recv_frame["customReservedRawData1"] == 0 or not sm.alive["customReservedRawData1"]:
    return None
  return parse_payload(sm["customReservedRawData1"])


def current_fix():
  """Most recent GPS fix seen by the UI from either receiver, or None."""
  sm = ui_state.sm
  best = None
  for svc in ("gpsLocation", "gpsLocationExternal"):
    if sm.recv_frame[svc] == 0:
      continue
    g = sm[svc]
    if not g.hasFix:
      continue
    if best is None or sm.logMonoTime[svc] > best[0]:
      best = (sm.logMonoTime[svc], g)
  return None if best is None else best[1]


def load_place(name):
  raw = ui_state.params.get(PLACE_KEYS[name])
  if not raw:
    return None
  try:
    place = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return {"lat": float(place["lat"]), "lon": float(place["lon"]), "name": name}
  except (ValueError, TypeError, KeyError):
    return None


def save_place_here(name):
  """Store the current GPS position as Home or Work. Returns True on success."""
  fix = current_fix()
  if fix is None:
    return False
  ui_state.params.put(PLACE_KEYS[name], {"lat": fix.latitude, "lon": fix.longitude, "name": name})
  return True


def start_navigation(name):
  place = load_place(name)
  if place is None:
    return False
  ui_state.params.put("NavDestination", place)
  return True


def stop_navigation():
  ui_state.params.remove("NavDestination")


def place_text(name):
  place = load_place(name)
  if place is None:
    return "not set"
  return f"{place['lat']:.5f}, {place['lon']:.5f}"


def format_distance(meters, is_metric):
  if is_metric:
    if meters < 1000:
      return f"{int(round(meters / 10.0) * 10)} m"
    return f"{meters / 1000.0:.1f} km"
  feet = meters * 3.28084
  if feet < 1000:
    return f"{int(round(feet / 50.0) * 50)} ft"
  return f"{meters / 1609.344:.1f} mi"


def format_eta(seconds):
  minutes = int(round(seconds / 60.0))
  if minutes < 60:
    return f"{minutes} min"
  return f"{minutes // 60} h {minutes % 60} min"


def maneuver_text(payload):
  """Human sentence for the current maneuver, e.g. 'Turn left onto Packard Street'."""
  kind = payload.get("maneuver", "")
  side = payload.get("modifier", "")
  street = payload.get("street", "")
  onto = f" onto {street}" if street else ""
  if kind == "turn":
    return f"Turn {side}{onto}"
  if kind == "slight":
    return f"Slight {side}{onto}"
  if kind == "keep":
    return f"Keep {side}{onto}"
  if kind == "exit":
    return f"Take the exit on the {side}" + (f" toward {street}" if street else "")
  if kind == "merge":
    return f"Merge{onto}"
  if kind == "uturn":
    return "Make a U-turn"
  if kind == "arrive":
    return f"Arrive at {payload.get('dest', 'destination')}"
  return ""


def maneuver_arrow(payload):
  kind = payload.get("maneuver", "")
  if kind == "arrive":
    return "◎"
  return MANEUVER_ARROWS.get((kind, payload.get("modifier", "")), "↑")


def status_text(payload):
  status = payload.get("status", "idle")
  dest = payload.get("dest", "")
  return {
    "no_gps": "Waiting for GPS",
    "no_route": f"No route to {dest}",
    "off_route": "Off route, re-routing",
    "arrived": f"Arrived at {dest}",
  }.get(status, "")
