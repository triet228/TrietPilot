# openpilot/system/tests/test_self_update.py

import pytest

from openpilot.common.test import OpenpilotTestCase
import openpilot.system.self_update as su


class FakeGit:
  """Answers git commands from a table, records the calls."""

  def __init__(self, answers):
    self.answers = answers
    self.calls = []

  def __call__(self, *args, timeout=None):
    self.calls.append(args)
    for prefix, out in self.answers:
      if args[:len(prefix)] == prefix:
        if isinstance(out, Exception):
          raise out
        return out
    raise AssertionError(f"unexpected git call {args}")


class TestSelfUpdate(OpenpilotTestCase):
  def test_parse_behind_ahead(self):
    assert su.parse_behind_ahead("3\t0") == (3, 0)
    assert su.parse_behind_ahead("0 2") == (0, 2)
    with pytest.raises(su.UpdateError):
      su.parse_behind_ahead("garbage")

  def test_check_reports_new_commits(self, monkeypatch):
    git = FakeGit([
      (("rev-parse", "--abbrev-ref"), "master"),
      (("fetch",), ""),
      (("rev-parse", "--short=8", "HEAD"), "aaaaaaaa"),
      (("rev-parse", "--short=8", "origin/master"), "bbbbbbbb"),
      (("rev-list",), "2\t0"),
      (("status",), ""),
    ])
    monkeypatch.setattr(su, "_git", git)
    info = su.check()
    assert info["behind"] == 2 and info["ahead"] == 0 and not info["dirty"]
    assert info["summary"] == "2 new commits"
    assert ("fetch", "--quiet", "origin", "master") in git.calls

  def test_check_up_to_date_and_dirty(self, monkeypatch):
    git = FakeGit([
      (("rev-parse", "--abbrev-ref"), "HEAD"),  # detached -> treated as master
      (("fetch",), ""),
      (("rev-parse", "--short=8"), "cccccccc"),
      (("rev-list",), "0\t0"),
      (("status",), " M some/file.py"),
    ])
    monkeypatch.setattr(su, "_git", git)
    info = su.check()
    assert info["branch"] == "master"
    assert info["behind"] == 0 and info["dirty"]
    assert info["summary"] == "up to date, local edits will be discarded"

  def test_apply_resets_syncs_submodules_and_reboots(self, monkeypatch):
    git = FakeGit([
      (("rev-parse", "--abbrev-ref"), "master"),
      (("fetch",), ""),
      (("reset",), ""),
      (("submodule",), ""),
      (("rev-parse", "--short=8", "HEAD"), "dddddddd"),
    ])
    monkeypatch.setattr(su, "_git", git)
    written = []

    class P:
      def put_bool(self, k, v, block=False):
        written.append((k, v))
    monkeypatch.setattr(su, "Params", P)
    assert su.apply() == "dddddddd"
    assert ("reset", "--hard", "origin/master") in git.calls
    assert ("submodule", "update", "--init", "--recursive") in git.calls
    assert written == [("DoReboot", True)]

  def test_apply_without_reboot(self, monkeypatch):
    git = FakeGit([
      (("rev-parse", "--abbrev-ref"), "master"),
      (("fetch",), ""), (("reset",), ""), (("submodule",), ""),
      (("rev-parse", "--short=8", "HEAD"), "eeeeeeee"),
    ])
    monkeypatch.setattr(su, "_git", git)
    monkeypatch.setattr(su, "Params", lambda: (_ for _ in ()).throw(AssertionError("should not touch params")))
    assert su.apply(reboot=False) == "eeeeeeee"

  def test_git_failure_surfaces(self, monkeypatch):
    git = FakeGit([(("rev-parse", "--abbrev-ref"), "master"), (("fetch",), su.UpdateError("could not resolve host"))])
    monkeypatch.setattr(su, "_git", git)
    with pytest.raises(su.UpdateError, match="resolve host"):
      su.check()
