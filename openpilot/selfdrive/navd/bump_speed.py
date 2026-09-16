# openpilot/selfdrive/navd/bump_speed.py

"""Slow down for mapped speed bumps.

The driving model does not react to speed bumps, so the car takes them at the set
speed and pitches hard. OpenStreetMap tags them as traffic_calming nodes on the road
(bump, hump, table, cushion), build_map.py keeps those that sit on a mapped road, and
this turns the ones in the look-ahead into a speed cap with the same approach law as
curve speed control, but a firmer deceleration:

  v_now = sqrt(v_bump^2 + 2 * a_decel * dist)

Bumps apply to both directions, so unlike stop signs there is no direction question.
The cap is released once the node is behind the car and speedlimitd lets the target
rise back gently. Only ever lowers the target. Metres and m/s throughout.
"""

import math

LOOKAHEAD_M = 200.0
A_DECEL = 1.0  # m/s^2, firmer than curves: a bump is a hard edge, not a gentle bend

# comfortable crossing speed by traffic_calming kind
BUMP_SPEED = {
  "bump": 4.5,     # ~10 mph, short and abrupt
  "hump": 6.7,     # ~15 mph, longer and gentler
  "table": 6.7,    # ~15 mph, flat-topped, often at crosswalks
  "cushion": 6.7,  # ~15 mph
}


def bump_speed(nodes_ahead, kind_at, lookahead=LOOKAHEAD_M, a_decel=A_DECEL):
  """Speed (m/s) the car may hold now for the bumps ahead, or None when none is within reach.

  nodes_ahead  [(node_idx, dist_m), ...] from curve_speed.lookahead(), nearest first
  kind_at      callable(node_idx) -> traffic_calming kind or None
  """
  best = None
  for node, dist in nodes_ahead:
    if dist > lookahead:
      break
    v_bump = BUMP_SPEED.get(kind_at(node))
    if v_bump is None:
      continue
    v_now = math.sqrt(v_bump ** 2 + 2.0 * a_decel * dist)
    if best is None or v_now < best:
      best = v_now
  return best
