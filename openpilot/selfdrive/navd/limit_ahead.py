# openpilot/selfdrive/navd/limit_ahead.py

"""Pre-slow for speed limit drops.

Speed limit cruise changes the set speed when the car crosses onto a road with a
different limit, which means the car only starts slowing after it has passed the
sign. This looks along the same road-ahead walk that curve speed control uses,
finds every upcoming way whose cruise target is lower than the current one, and
works back to the speed the car may hold right now so it reaches the new target at
the sign instead of after it:

  v_now = sqrt(v_target_ahead^2 + 2 * a_decel * dist)

Only lower targets count, so this never speeds the car up, and it uses the same
straightest-continuation walk as curve speed, which stops at ambiguous forks and
turns; a freeway exit or a side street can therefore never pull the target down.
Conditional limits (school zones) are evaluated at the map's local time, so the
car also eases into a school zone during its hours. Everything is in metres and
m/s; the caller converts.
"""

import math

LOOKAHEAD_M = 400.0
A_DECEL = 0.7  # m/s^2, gentle: a 45 -> 25 mph drop starts about 200 m before the sign


def limit_ahead_speed(ways_ahead, target_now_ms, target_for, when=None, a_decel=A_DECEL):
  """Speed (m/s) the car may hold now so it is at each lower target when it reaches it, or None.

  ways_ahead     [(way_idx, dist_m), ...] from curve_speed.lookahead()
  target_now_ms  cruise target (m/s) of the road the car is on
  target_for     callable(way_idx, when) -> cruise target (m/s) of that way
  """
  best = None
  for wi, dist in ways_ahead:
    v_target = target_for(wi, when)
    if v_target >= target_now_ms:
      continue
    v_now = math.sqrt(v_target ** 2 + 2.0 * a_decel * dist)
    if best is None or v_now < best:
      best = v_now
  return best
