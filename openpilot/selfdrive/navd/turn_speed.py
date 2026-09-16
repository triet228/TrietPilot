# openpilot/selfdrive/navd/turn_speed.py

"""Slow down ahead of navigation turns.

When a route is active, navd knows exactly where the next turn is and what kind it
is. This turns that into a speed cap the longitudinal planner honours, using the same
approach law as curve speed control and the speed limit pre-slow:

  v_now = sqrt(v_turn^2 + 2 * a_decel * dist)

so the car arrives at the corner already at a sensible speed and the driver only has
to steer it (openpilot does not take turns at intersections on its own). The cap is
held at v_turn until the car is a few metres past the node, then released, and navd
lets it rise back gently. Only ever lowers the target; merges and lane keeps get no
cap because they are not corners. Everything is in metres and m/s.
"""

import math

LOOKAHEAD_M = 300.0
A_DECEL = 0.8  # m/s^2, same gentle approach as curve speed control

# comfortable speed at the maneuver node by instruction type from router.build_instructions
TURN_SPEED = {
  "uturn": 4.0,    # ~9 mph
  "turn": 7.0,     # ~16 mph, a 90 degree intersection turn
  "slight": 11.0,  # ~25 mph, a bend or fork onto another road
  "exit": 13.0,    # ~29 mph, freeway exit ramp entry
  "arrive": 5.0,   # ~11 mph, about to stop at the destination
}


def turn_speed(instructions, dist_along, lookahead=LOOKAHEAD_M, a_decel=A_DECEL):
  """Speed (m/s) the car may hold now for the maneuvers ahead, or None when none is within reach.

  instructions   navd RouteTracker.upcoming(): dicts with "type" and "dist" (metres from route start)
  dist_along     the car's distance along the route
  """
  best = None
  for ins in instructions:
    v_turn = TURN_SPEED.get(ins.get("type"))
    if v_turn is None:
      continue
    dist = max(0.0, ins["dist"] - dist_along)
    if dist > lookahead:
      continue
    v_now = math.sqrt(v_turn ** 2 + 2.0 * a_decel * dist)
    if best is None or v_now < best:
      best = v_now
  return best
