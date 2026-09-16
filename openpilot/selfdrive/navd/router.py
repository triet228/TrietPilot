# openpilot/selfdrive/navd/router.py

"""Offline routing and turn instructions on the OfflineMap graph.

A* over road nodes with travel-time edge costs. Residential streets and links
cost extra so routes prefer arterials the way a human would, and a turn penalty
discourages zig-zag paths through neighbourhoods. Everything runs locally on the
device in well under a second for a cross-town route.

Instructions are derived purely from geometry and OSM tags: heading change at
each node, road class transitions for freeway exits and merges, and road names.
"""

import heapq
import math

from openpilot.selfdrive.navd.offline_map import bearing_deg, angle_diff

# routing cost tuning
MAX_SPEED_MS = 70 * 0.44704          # heuristic must never overestimate remaining time
CLASS_TIME_FACTOR = {                # multiplied into edge travel time
  "residential": 1.4, "living_street": 2.0, "unclassified": 1.2,
  "motorway_link": 1.1, "trunk_link": 1.1, "primary_link": 1.1, "secondary_link": 1.1, "tertiary_link": 1.1,
}
TURN_PENALTY_S = 8.0                 # for heading changes above TURN_PENALTY_DEG between consecutive edges
TURN_PENALTY_DEG = 45.0
SNAP_DIST = 120.0                    # m, how far a start/destination may be from the nearest road
SNAP_DIST_FAR = 400.0                # m, second attempt for destinations set in a parking lot or driveway

# instruction geometry thresholds, degrees of heading change
SLIGHT_DEG = 25.0
TURN_DEG = 60.0
UTURN_DEG = 150.0
MERGE_INSTRUCTIONS_M = 40.0          # a slight/keep this close after another instruction is an artifact

LINK_CLASSES = ("motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link")
FREEWAY_CLASSES = ("motorway", "trunk")


class Route:
  def __init__(self, nodes, ways, dists, times, coords):
    self.nodes = nodes      # node indices along the route, None for the virtual start vertex
    self.ways = ways        # way index for each edge, len(nodes) - 1
    self.cum_dist = dists   # cumulative metres at each vertex
    self.cum_time = times   # cumulative seconds at each vertex
    self.coords = coords    # (x, y) metres for each vertex, this is the polyline the tracker follows
    self.instructions = []

  @property
  def total_dist(self):
    return self.cum_dist[-1] if self.cum_dist else 0.0

  @property
  def total_time(self):
    return self.cum_time[-1] if self.cum_time else 0.0


def snap(m, lat, lon, bearing=None):
  """(node, way) nearest to a point, preferring the node ahead in the travel direction. None if off the map."""
  match = m.match(lat, lon, bearing, max_dist=SNAP_DIST)
  if match is None:
    match = m.match(lat, lon, None, max_dist=SNAP_DIST_FAR)
  if match is None:
    return None
  n = m.ways[match.way_idx]["n"]
  a, b = n[match.seg_idx], n[match.seg_idx + 1]
  if bearing is not None:
    node = b if match.forward else a
  else:
    node = b if match.frac >= 0.5 else a
  return node, match.way_idx


def _edge_cost(m, way_idx, length):
  speed = m.segment_speed_ms(way_idx)
  factor = CLASS_TIME_FACTOR.get(m.road_class(way_idx), 1.0)
  return length / max(speed, 1.0) * factor


def _heading(m, a, b):
  return bearing_deg(*m.node_latlon(a), *m.node_latlon(b))


def _heading_xy(p, q):
  """Bearing from p to q in local metres, degrees clockwise from north."""
  return math.degrees(math.atan2(q[0] - p[0], q[1] - p[1])) % 360.0


def find_route(m, start_node, goal_node, start_xy=None, start_way=None):
  """A* from start_node to goal_node. Returns a Route or None if unreachable.

  start_xy is the car's actual position in map metres; when given (with the way it is on)
  it becomes the first vertex so the route begins under the car, not at the next node.
  """
  if start_node is None or goal_node is None:
    return None
  if start_node == goal_node:
    coords = [(float(m.x[start_node]), float(m.y[start_node]))]
    return Route([start_node], [], [0.0], [0.0], coords)

  adj = m.adjacency()
  gx, gy = m.x[goal_node], m.y[goal_node]

  def h(n):
    return math.hypot(m.x[n] - gx, m.y[n] - gy) / MAX_SPEED_MS

  g = {start_node: 0.0}
  came_from = {}
  open_heap = [(h(start_node), 0.0, start_node)]
  closed = set()

  while open_heap:
    _, cost, node = heapq.heappop(open_heap)
    if node in closed:
      continue
    if node == goal_node:
      break
    closed.add(node)

    prev = came_from.get(node)
    prev_heading = _heading(m, prev[0], node) if prev is not None else None

    for nxt, length, wi in adj.get(node, ()):
      if nxt in closed:
        continue
      step = _edge_cost(m, wi, length)
      if prev_heading is not None:
        turn = angle_diff(prev_heading, _heading(m, node, nxt))
        if turn > TURN_PENALTY_DEG:
          step += TURN_PENALTY_S
      new_cost = cost + step
      if new_cost < g.get(nxt, float("inf")):
        g[nxt] = new_cost
        came_from[nxt] = (node, wi, length, step)
        heapq.heappush(open_heap, (new_cost + h(nxt), new_cost, nxt))

  if goal_node not in came_from:
    return None

  nodes, ways, lengths, steps = [goal_node], [], [], []
  node = goal_node
  while node != start_node:
    prev, wi, length, step = came_from[node]
    nodes.append(prev)
    ways.append(wi)
    lengths.append(length)
    steps.append(step)
    node = prev
  nodes.reverse()
  ways.reverse()
  lengths.reverse()
  steps.reverse()

  coords = [(float(m.x[n]), float(m.y[n])) for n in nodes]
  if start_xy is not None and start_way is not None:
    prefix = math.hypot(coords[0][0] - start_xy[0], coords[0][1] - start_xy[1])
    if prefix > 1.0:
      nodes.insert(0, None)
      ways.insert(0, start_way)
      lengths.insert(0, prefix)
      steps.insert(0, _edge_cost(m, start_way, prefix))
      coords.insert(0, (float(start_xy[0]), float(start_xy[1])))

  dists = [0.0]
  times = [0.0]
  for length, step in zip(lengths, steps, strict=True):
    dists.append(dists[-1] + length)
    times.append(times[-1] + step)

  route = Route(nodes, ways, dists, times, coords)
  route.instructions = build_instructions(m, route)
  return route


def _signed_turn(heading_in, heading_out):
  """Positive is a right turn, negative left, degrees in (-180, 180]."""
  d = (heading_out - heading_in + 180.0) % 360.0 - 180.0
  return d if d != -180.0 else 180.0


def build_instructions(m, route):
  """List of maneuvers along the route, each with the distance from the route start."""
  out = []
  nodes, ways = route.nodes, route.ways
  adj = m.adjacency()

  for i in range(1, len(ways)):
    node = nodes[i]
    way_in, way_out = ways[i - 1], ways[i]
    h_in = _heading_xy(route.coords[i - 1], route.coords[i])
    h_out = _heading_xy(route.coords[i], route.coords[i + 1])
    turn = _signed_turn(h_in, h_out)
    mag = abs(turn)
    side = "right" if turn > 0 else "left"
    cls_in, cls_out = m.road_class(way_in), m.road_class(way_out)
    name_in, name_out = m.road_name(way_in), m.road_name(way_out)
    choices = len(adj.get(node, ())) if node is not None else 0

    kind = None
    if mag >= UTURN_DEG:
      kind = "uturn"
    elif cls_in in FREEWAY_CLASSES and cls_out in LINK_CLASSES:
      kind = "exit"
    elif cls_in in LINK_CLASSES and cls_out in FREEWAY_CLASSES:
      kind = "merge"
    elif mag >= TURN_DEG:
      kind = "turn"
    elif mag >= SLIGHT_DEG:
      kind = "slight"
    elif choices > 2 and name_out and name_out != name_in and mag >= 10.0:
      # a fork or a bend onto a differently named road where a wrong choice is possible
      kind = "slight"
    elif cls_in in LINK_CLASSES and cls_out in LINK_CLASSES and choices > 2 and mag >= 10.0:
      kind = "keep"

    if kind is None:
      continue

    # divided roads and channelized intersections produce a slight-left/slight-right pair a
    # few metres apart; the first one is the real instruction, drop the echo
    if out and kind in ("slight", "keep") and route.cum_dist[i] - out[-1]["dist"] < MERGE_INSTRUCTIONS_M:
      continue

    out.append({
      "type": kind,
      "modifier": side,
      "street": name_out,
      "dist": route.cum_dist[i],
      "node": i,
    })

  out.append({"type": "arrive", "modifier": "", "street": "", "dist": route.total_dist, "node": len(nodes) - 1})
  return out
