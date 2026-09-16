# openpilot/system/fork_presets.py

"""Every setting TrietPilot cares about, preset here in the repo.

Nothing has to be toggled on the device. manager applies this table on every boot,
after upstream has filled in its own defaults, so a fresh install, a factory reset,
or a stray tap on the Toggles panel all end up in the same known state after the
next start. To change a setting, edit this file, commit, and update the device.

PRESETS   params written on every boot. Bools become put_bool, everything else is
          written with the param's own type (LongitudinalPersonality is an int).
PLACES    saved navigation destinations for the one-press Go Home / Go to Work
          buttons. A value is either an address or place name resolved with the
          offline address book ("1234 Packard St", "Zingerman's"), a dict with
          lat, lon and an optional name, or None to leave whatever is on the
          device untouched.

ExperimentalMode is deliberately absent: speedlimitd flips it by road type when
AutoExperimentalMode is on, so writing it here would fight that.
"""

from openpilot.common.swaglog import cloudlog

PRESETS = {
  # fork features (see README)
  "SpeedLimitCruise": True,       # set speed follows the posted limit plus offset
  "AutoExperimentalMode": True,   # Experimental on local roads, chill on freeways
  "NudgelessLaneChange": True,    # signal-only lane change on freeways
  "NavTurnSlowdown": True,        # slow ahead of navigation turns

  # upstream toggles, as they appear in the Toggles panel
  "OpenpilotEnabledToggle": True,
  "DisengageOnAccelerator": False,  # per-axis override handles the gas pedal instead
  "IsLdwEnabled": True,             # lane departure warnings while disengaged
  "AlwaysOnDM": False,              # driver monitoring only while engaged
  "IsMetric": False,                # mph
  "RecordFront": False,             # no driver camera recording
  "RecordAudio": False,             # no microphone in the dashcam
  "LongitudinalPersonality": 1,     # 0 aggressive, 1 standard, 2 relaxed
}

PLACES = {
  "NavHome": None,   # e.g. "1234 Packard St" or {"lat": 42.2808, "lon": -83.7430, "name": "Home"}
  "NavWork": None,   # e.g. "1320 Beal Ave" (FXB, University of Michigan)
}


def resolve_place(key, value, resolve):
  """Turns a PLACES entry into the {lat, lon, name} dict navd expects, or None."""
  if value is None:
    return None
  if isinstance(value, dict):
    return {"lat": float(value["lat"]), "lon": float(value["lon"]), "name": str(value.get("name", key[3:]))}
  hit = resolve(str(value))
  if hit is None:
    cloudlog.warning(f"fork_presets: could not resolve {key} address {value!r}")
    return None
  return {"lat": float(hit["lat"]), "lon": float(hit["lon"]), "name": key[3:]}


def _offline_resolve(text):
  from openpilot.selfdrive.navd.geocoder import Geocoder
  return Geocoder().lookup(text)


def apply_presets(params, presets=PRESETS, places=PLACES, resolve=_offline_resolve):
  """Writes the preset table to params. Returns the list of keys written."""
  written = []
  for key, value in presets.items():
    if isinstance(value, bool):
      params.put_bool(key, value)
    else:
      params.put(key, value)
    written.append(key)
  for key, value in places.items():
    place = resolve_place(key, value, resolve)
    if place is not None:
      params.put(key, place)
      written.append(key)
  return written
