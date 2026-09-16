# openpilot/selfdrive/navd/auto_destination.py

"""Zero-tap navigation between Home and Work.

At the start of a drive, when no destination is set, navd guesses one from where
the car is: within RADIUS_M of Home it routes to Work, within RADIUS_M of Work it
routes to Home. That gives the banner and the turn slowdown something to work with
on the two drives that make up most days, without pressing anything.

It is only a guess, so it is held loosely:
  * it is made once per drive, from the fixes in the first WINDOW_S after GPS comes up
  * it needs both places saved, and at least MIN_SEPARATION_M apart
  * if the car leaves the guessed route, navigation gives up and goes back to idle
    instead of re-routing, since a wrong guess should not nag for the whole drive
  * a destination the driver sets is never touched, and a manual destination replaces
    the guess at any time
Turn it off with NavAutoHomeWork in the presets file.
"""

from openpilot.selfdrive.navd.offline_map import haversine

RADIUS_M = 200.0          # how close to a saved place the car has to start
WINDOW_S = 90.0           # seconds after the first GPS fix in which the guess may be made
MIN_SEPARATION_M = 1000.0  # Home and Work closer than this are ambiguous, no guess


def auto_destination(lat, lon, home, work):
  """The place to route to from this position, as a {lat, lon, name} dict, or None."""
  if home is None or work is None:
    return None
  if haversine(home["lat"], home["lon"], work["lat"], work["lon"]) < MIN_SEPARATION_M:
    return None
  d_home = haversine(lat, lon, home["lat"], home["lon"])
  d_work = haversine(lat, lon, work["lat"], work["lon"])
  if d_home <= RADIUS_M and d_home <= d_work:
    return {"lat": work["lat"], "lon": work["lon"], "name": "Work"}
  if d_work <= RADIUS_M:
    return {"lat": home["lat"], "lon": home["lon"], "name": "Home"}
  return None
