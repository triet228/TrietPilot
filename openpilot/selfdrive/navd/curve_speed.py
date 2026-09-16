# openpilot/selfdrive/navd/curve_speed.py

"""Map-based curve speed control.

Looks a few hundred metres ahead along the road geometry, works out the
comfortable speed for every bend from its curvature, and brings that back to a
single speed the car may be doing right now so it eases off before the curve
instead of braking in it.

  v_curve = sqrt(a_lat_max / curvature)             comfortable speed in the bend
  v_now   = sqrt(v_curve^2 + 2 * a_decel * dist)    what we may do now and still get there

The result only ever lowers the cruise target, never raises it. Everything is in
metres and m/s; the caller converts.
"""

import math

from openpilot.selfdrive.navd.offline_map import angle_diff

LOOKAHEAD_M = 300.0
LOOKAHEAD_S = 12.0
# comfortable lateral acceleration per longitudinal personality (aggressive, standard, relaxed)
A_LAT_MAX = {0: 2.5, 1: 2.0, 2: 1.6}
A_DECEL = 0.8            # m/s^2 used to approach a curve, gentle on purpose
MIN_CURVE_SPEED = 4.0    # m/s, never ask for slower than this for geometry alone
# curvature below this is treated as straight; 1/1500 m is a barely perceptible bend
MIN_CURVATURE = 1.0 / 1500.0
# continuation choice at way ends: the straightest option wins unless a second option is
# nearly as straight (ambiguous fork) or the best one is itself a turn
FORK_AMBIGUOUS_DEG = 30.0
CONTINUE_MAX_DEG = 60.0
# how fast the curve speed may come back up after a bend, m/s per second
RISE_RATE = 1.5


def _heading(ax, ay, bx, by):
  return math.degrees(math.atan2(bx - ax, by - ay)) % 360.0


def lookahead_points(m, match, max_dist=LOOKAHEAD_M):
  """(x, y, dist) along the road ahead of the matched position, starting at the car.

  Follows the current way in the travel direction, then the straightest continuation
  at each way end. Stops at ambiguous forks, at turns, and at max_dist.
  """
  way = m.ways[match.way_idx]
  n = way["n"]
  a, b = n[match.seg_idx], n[match.seg_idx + 1]
  ax, ay, bx, by = m.x[a], m.y[a], m.x[b], m.y[b]
  # car position projected onto the segment
  px, py = ax + match.frac * (bx - ax), ay + match.frac * (by - ay)
  pts = [(float(px), float(py), 0.0)]

  # remaining nodes of this way in travel direction
  if match.forward:
    seq = n[match.seg_idx + 1:]
  else:
    seq = list(reversed(n[:match.seg_idx + 1]))
  prev_node = a if match.forward else b
  used_ways = {match.way_idx}

  dist = 0.0
  while dist < max_dist:
    for node in seq:
      x, y = float(m.x[node]), float(m.y[node])
      dist += math.hypot(x - pts[-1][0], y - pts[-1][1])
      pts.append((x, y, dist))
      prev_node = node
      if dist >= max_dist:
        return pts
    if len(pts) < 2:
      return pts

    # pick the straightest way onward from the last node
    hx, hy = pts[-2][0], pts[-2][1]
    heading = _heading(hx, hy, pts[-1][0], pts[-1][1])
    options = []
    for nxt, _, wi in m.adjacency().get(prev_node, ()):
      if wi in used_ways or nxt == prev_node:
        continue
      diff = angle_diff(heading, _heading(pts[-1][0], pts[-1][1], float(m.x[nxt]), float(m.y[nxt])))
      options.append((diff, wi, nxt))
    if not options:
      return pts
    options.sort()
    best = options[0]
    if best[0] > CONTINUE_MAX_DEG:
      return pts
    if len(options) > 1 and options[1][0] - best[0] < FORK_AMBIGUOUS_DEG:
      return pts
    wi, nxt = best[1], best[2]
    used_ways.add(wi)
    wn = m.ways[wi]["n"]
    # continue along the new way from prev_node toward nxt
    i = wn.index(prev_node)
    if i + 1 < len(wn) and wn[i + 1] == nxt:
      seq = wn[i + 1:]
    else:
      seq = list(reversed(wn[:i]))
  return pts


def curvatures(pts):
  """Curvature (1/m) at each interior point from the circumcircle of it and its neighbours, smoothed."""
  k = [0.0] * len(pts)
  for i in range(1, len(pts) - 1):
    (x1, y1, _), (x2, y2, _), (x3, y3, _) = pts[i - 1], pts[i], pts[i + 1]
    a = math.hypot(x2 - x1, y2 - y1)
    b = math.hypot(x3 - x2, y3 - y2)
    c = math.hypot(x3 - x1, y3 - y1)
    if a < 1e-3 or b < 1e-3 or c < 1e-3:
      continue
    cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    k[i] = abs(2.0 * cross / (a * b * c))
  # 3-point mean so sparse or jittery nodes do not spike
  sm = list(k)
  for i in range(1, len(k) - 1):
    sm[i] = (k[i - 1] + k[i] + k[i + 1]) / 3.0
  return sm


def curve_speed(pts, personality=1, a_decel=A_DECEL):
  """Speed (m/s) the car may hold now so every bend ahead is entered at its comfortable speed, or None if all straight."""
  a_lat = A_LAT_MAX.get(personality, A_LAT_MAX[1])
  ks = curvatures(pts)
  best = None
  for (_, _, dist), k in zip(pts, ks, strict=True):
    if k < MIN_CURVATURE:
      continue
    v_curve = max(MIN_CURVE_SPEED, math.sqrt(a_lat / k))
    v_now = math.sqrt(v_curve ** 2 + 2.0 * a_decel * dist)
    if best is None or v_now < best:
      best = v_now
  return best


class CurveSpeedFilter:
  """Lets the target drop instantly but rise only at RISE_RATE, so the throttle does not surge after a bend."""

  def __init__(self, dt):
    self.dt = dt
    self.v = None

  def update(self, v_target):
    if v_target is None:
      self.v = None
      return None
    if self.v is None or v_target <= self.v:
      self.v = v_target
    else:
      self.v = min(v_target, self.v + RISE_RATE * self.dt)
    return self.v
