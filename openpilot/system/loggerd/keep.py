# openpilot/system/loggerd/keep.py

"""Kept footage: segments the driver marked from the drive browser.

A Keep press marks the segment and the KEEP_SPAN segments on either side of it in
the same route, about ten minutes each way, with the user.keep extended attribute.
deleter treats kept segments as untouchable as long as everything kept together
stays under KEEP_BUDGET_BYTES; past that, the oldest kept segments lose their
protection first and are deleted like ordinary footage to make room, so the budget
is a rolling 20 GB of the most recent things worth keeping.

This is separate from user.preserve, which loggerd sets on incidents and bookmarks
and deleter protects with its own small count. Both marks live on the segment
directory, so nothing here touches the log files themselves.
"""

import os

KEEP_ATTR = "user.keep"
KEEP_VALUE = b"1"
KEEP_SPAN = 10                          # segments (minutes) kept on each side of the pressed one
KEEP_BUDGET_BYTES = 20 * 1024 ** 3      # kept footage protected up to this much, oldest released first


def split_segment(name):
  """'<route>--<n>' -> (route, n), or None for anything else (boot, crash, params...)."""
  route, sep, idx = name.rpartition("--")
  if not sep or not route:
    return None
  try:
    return route, int(idx)
  except ValueError:
    return None


def keep_range(names, route, index, span=KEEP_SPAN):
  """Segment names present in `names` that a Keep press on route/index covers, in order."""
  out = []
  for n in names:
    parts = split_segment(n)
    if parts is not None and parts[0] == route and abs(parts[1] - index) <= span:
      out.append((parts[1], n))
  return [n for _, n in sorted(out)]


def route_segments(names, route):
  out = [(p[1], n) for n in names if (p := split_segment(n)) is not None and p[0] == route]
  return [n for _, n in sorted(out)]


def supported():
  return hasattr(os, "setxattr") and hasattr(os, "removexattr")


def is_kept(path):
  getxattr = getattr(os, "getxattr", None)
  if getxattr is None:
    return False
  try:
    return getxattr(path, KEEP_ATTR) == KEEP_VALUE
  except OSError:
    return False


def set_kept(path, kept):
  """Marks or unmarks one segment directory. Returns True if the mark changed."""
  if not supported():
    return False
  try:
    if kept:
      if is_kept(path):
        return False
      os.setxattr(path, KEEP_ATTR, KEEP_VALUE)
    else:
      if not is_kept(path):
        return False
      os.removexattr(path, KEEP_ATTR)
    return True
  except OSError:
    return False


def dir_bytes(path):
  total = 0
  try:
    with os.scandir(path) as it:
      for e in it:
        try:
          total += e.stat().st_size
        except OSError:
          pass
  except OSError:
    pass
  return total


def protected_kept(dirs_by_creation, kept, size, budget=KEEP_BUDGET_BYTES):
  """Kept segment names that stay protected: newest first until the budget is spent.

  dirs_by_creation  directory names oldest first (uploader.listdir_by_creation)
  kept(name)        whether the segment carries the keep mark
  size(name)        its size in bytes
  Returns (protected set, total kept bytes).
  """
  protected = set()
  used = 0
  total = 0
  for name in reversed(dirs_by_creation):
    if split_segment(name) is None or not kept(name):
      continue
    b = size(name)
    total += b
    if used + b <= budget:
      protected.add(name)
      used += b
  return protected, total
