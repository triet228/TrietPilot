#!/usr/bin/env bash
# Update this checkout from its GitHub remote over SSH and reboot.
# Same code path as the "Update and reboot" button in the Software settings panel.
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
python3 -m openpilot.system.self_update --apply "$@"
