# openpilot/selfdrive/navd/conditional_limit.py

"""Time-conditional speed limits, mainly school zones.

OSM tags them as maxspeed:conditional, for example

  25 mph @ (Mo-Fr 08:20-08:50,15:45-16:15; PH off; SH off)

build_map.py turns each such tag into a compact rule list stored on the way:

  [{"s": 25, "d": [0, 1, 2, 3, 4], "t": [[500, 530], [945, 975]]}, ...]

  s  limit in mph while the rule is active
  d  weekdays the rule applies to, Monday = 0 (all seven when the tag names none)
  t  [start, end] minute-of-day windows (one all-day window when the tag names none)

"PH off" and "SH off" (public and school holidays) are ignored on purpose: the
device has no holiday calendar, and applying the school-zone limit on a holiday
only costs a few mph for a few hundred metres, while missing it on a school day
would mean speeding past a school. Anything else that does not parse is dropped
so a strange tag can never activate a limit by accident.
"""

import re

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
ALL_DAYS = list(range(7))
ALL_DAY = [[0, 24 * 60]]

_RULE_RE = re.compile(r"([^@;()]+)@\s*(\([^)]*\)|[^;]+)")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_DAY_RE = re.compile(r"^([A-Z][a-z])(?:-([A-Z][a-z]))?$")


def _parse_days(token):
  """'Mo-Fr' or 'Sa,Su' -> sorted weekday indices, or None if the token is not a day spec."""
  days = set()
  for part in token.split(","):
    m = _DAY_RE.match(part)
    if not m or m.group(1) not in DAYS or (m.group(2) and m.group(2) not in DAYS):
      return None
    a = DAYS.index(m.group(1))
    b = DAYS.index(m.group(2)) if m.group(2) else a
    # Su-Tu style wrap-around
    i = a
    while True:
      days.add(i)
      if i == b:
        break
      i = (i + 1) % 7
  return sorted(days)


def _parse_times(token):
  """'08:20-08:50,15:45-16:15' -> [[500, 530], [945, 975]], or None if not a time spec."""
  windows = []
  for part in token.split(","):
    m = _TIME_RE.match(part)
    if not m:
      return None
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
      return None
    windows.append([h1 * 60 + m1, h2 * 60 + m2])
  return windows


def _parse_clause(clause):
  """One 'Mo-Fr 08:20-08:50,15:45-16:15' clause -> (days, windows), or None."""
  tokens = clause.split()
  if not tokens or len(tokens) > 2:
    return None
  days, windows = None, None
  for tok in tokens:
    if days is None and _parse_days(tok) is not None:
      days = _parse_days(tok)
    elif windows is None and _parse_times(tok) is not None:
      windows = _parse_times(tok)
    else:
      return None
  return (days if days is not None else ALL_DAYS, windows if windows is not None else ALL_DAY)


def parse_conditional(tag, parse_speed):
  """maxspeed:conditional tag -> list of rules as documented above. parse_speed turns '25 mph' into mph."""
  rules = []
  if not tag:
    return rules
  for m in _RULE_RE.finditer(tag):
    speed = parse_speed(m.group(1).strip())
    if speed is None:
      continue
    cond = m.group(2).strip()
    if cond.startswith("("):
      cond = cond[1:-1]
    for clause in cond.split(";"):
      clause = clause.strip()
      if not clause or clause.endswith(" off"):
        # holiday exemptions, deliberately ignored (see module docstring)
        continue
      parsed = _parse_clause(clause)
      if parsed is None:
        continue
      rules.append({"s": speed, "d": parsed[0], "t": parsed[1]})
  return rules


def active_limit(rules, when):
  """Lowest rule limit (mph) active at datetime `when`, or None if no rule applies."""
  if not rules or when is None:
    return None
  minute = when.hour * 60 + when.minute
  weekday = when.weekday()
  best = None
  for r in rules:
    if weekday not in r["d"]:
      continue
    for start, end in r["t"]:
      hit = start <= minute < end if start <= end else (minute >= start or minute < end)
      if hit and (best is None or r["s"] < best):
        best = r["s"]
  return best
