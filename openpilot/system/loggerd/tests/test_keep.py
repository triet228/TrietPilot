# openpilot/system/loggerd/tests/test_keep.py

from openpilot.common.test import OpenpilotTestCase
from openpilot.system.loggerd.keep import split_segment, keep_range, route_segments, protected_kept, KEEP_SPAN

GB = 1024 ** 3


class TestKeep(OpenpilotTestCase):
  def test_split_segment(self):
    assert split_segment("0000000a--1a2b3c4d5e--7") == ("0000000a--1a2b3c4d5e", 7)
    assert split_segment("boot") is None
    assert split_segment("r--x") is None
    assert split_segment("--3") is None

  def test_keep_range_is_ten_minutes_each_way_within_the_route(self):
    names = [f"r1--{i}" for i in range(40)] + ["r2--12", "boot", "crash"]
    got = keep_range(names, "r1", 15)
    assert got == [f"r1--{i}" for i in range(15 - KEEP_SPAN, 15 + KEEP_SPAN + 1)]
    # clipped at the start of the route and missing segments are simply absent
    assert keep_range(names, "r1", 2) == [f"r1--{i}" for i in range(13)]
    assert keep_range(["r1--0", "r1--5", "r1--30"], "r1", 4) == ["r1--0", "r1--5"]
    assert route_segments(names, "r2") == ["r2--12"]

  def test_budget_protects_newest_first(self):
    dirs = [f"r--{i}" for i in range(6)] + ["boot"]  # oldest first
    kept = {"r--0", "r--1", "r--3", "r--5"}
    sizes = dict.fromkeys(dirs, 6 * GB)
    protected, total = protected_kept(dirs, lambda n: n in kept, lambda n: sizes[n], budget=20 * GB)
    # newest kept first: 5, 3, 1 fit (18 GB); 0 would push it to 24 GB, so it is released
    assert protected == {"r--5", "r--3", "r--1"}
    assert total == 24 * GB

  def test_budget_ignores_unkept_and_non_segments(self):
    dirs = ["boot", "r--0", "r--1"]
    protected, total = protected_kept(dirs, lambda n: True, lambda n: 1 * GB, budget=20 * GB)
    assert protected == {"r--0", "r--1"} and total == 2 * GB
    protected, total = protected_kept(dirs, lambda n: False, lambda n: 1 * GB)
    assert protected == set() and total == 0
