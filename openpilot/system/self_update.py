# openpilot/system/self_update.py

"""Self-update straight from the TrietPilot GitHub repo.

The only network peer is the git remote of this checkout (GitHub). Nothing here
knows about comma's servers. The flow the UI drives is:

  check()  -> git fetch, then report how many commits behind origin/<branch> we are
  apply()  -> git reset --hard to the fetched branch, sync submodules, then reboot;
              the launch script rebuilds on the way back up

Both are blocking git calls, so the UI runs them in a thread. Can also be run
over SSH:  python -m openpilot.system.self_update [--check | --apply]
"""

import os
import subprocess
import sys

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

GIT_TIMEOUT = 120  # s, a fetch over slow Wi-Fi should still finish well inside this


class UpdateError(Exception):
  pass


def _git(*args, timeout=GIT_TIMEOUT):
  try:
    out = subprocess.run(["git", *args], cwd=BASEDIR, capture_output=True, text=True, timeout=timeout,
                         env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
  except (OSError, subprocess.TimeoutExpired) as e:
    raise UpdateError(str(e)) from e
  if out.returncode != 0:
    raise UpdateError((out.stderr or out.stdout).strip() or f"git {' '.join(args)} failed")
  return out.stdout.strip()


def current_branch():
  branch = _git("rev-parse", "--abbrev-ref", "HEAD")
  return "master" if branch == "HEAD" else branch


def parse_behind_ahead(counts):
  """'3\\t0' from rev-list --left-right --count origin/x...HEAD -> (behind, ahead)."""
  parts = counts.split()
  if len(parts) != 2:
    raise UpdateError(f"unexpected rev-list output: {counts!r}")
  return int(parts[0]), int(parts[1])


def check():
  """Fetch and compare. Returns a dict with branch, local, remote, behind, ahead, dirty, summary."""
  branch = current_branch()
  _git("fetch", "--quiet", "origin", branch)
  local = _git("rev-parse", "--short=8", "HEAD")
  remote = _git("rev-parse", "--short=8", f"origin/{branch}")
  behind, ahead = parse_behind_ahead(_git("rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"))
  dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
  if behind == 0:
    summary = "up to date"
  else:
    summary = f"{behind} new commit{'s' if behind != 1 else ''}"
  if dirty:
    summary += ", local edits will be discarded"
  return {"branch": branch, "local": local, "remote": remote, "behind": behind, "ahead": ahead, "dirty": dirty, "summary": summary}


def apply(reboot=True):
  """Move this checkout to origin/<branch>, sync submodules, and reboot so the launch script rebuilds."""
  branch = current_branch()
  _git("fetch", "--quiet", "origin", branch)
  _git("reset", "--hard", f"origin/{branch}")
  _git("submodule", "sync", "--recursive")
  _git("submodule", "update", "--init", "--recursive", timeout=GIT_TIMEOUT * 5)
  new = _git("rev-parse", "--short=8", "HEAD")
  cloudlog.warning(f"self_update: now at {new} on {branch}")
  if reboot:
    Params().put_bool("DoReboot", True, block=True)
  return new


def main():
  if "--apply" in sys.argv:
    print("updated to", apply(reboot="--no-reboot" not in sys.argv))
    return
  info = check()
  print(f"{info['branch']}: local {info['local']}, remote {info['remote']}, {info['summary']}")


if __name__ == "__main__":
  main()
