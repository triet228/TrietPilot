# TrietPilot fork guide

How this fork is organized, what it owns, and how to pull in new upstream openpilot
releases without losing anything. Read this before every upstream sync.

## The one rule

Every feature lives in its own new file or directory. Upstream files are touched only
where the feature has to plug in, and each of those touches is a few lines that call
into fork-owned code. When upstream changes a file we also changed, the conflict is
almost always in one of those small plug-in spots, and the fix is to re-apply the
same few lines in the new upstream shape.

## Syncing with upstream

```bash
scripts/upstream_sync.sh          # new upstream commits and likely conflicts
scripts/upstream_sync.sh --sync   # apply new upstream commits
python3 scripts/test_fork.py      # the fork's tests, runs on a laptop with no native build
```

The fork's history has rewritten commit IDs to remove Claude coauthor trailers.
`scripts/upstream_base.txt` records the last upstream commit applied. The sync helper
cherry-picks only later upstream commits and skips LFS downloads, so it does not
restore the old upstream history. If a pick conflicts, resolve it, run
`git cherry-pick --continue` until the sequence finishes, then run
`scripts/upstream_sync.sh --record`. Keep fork-specific offline behavior when
resolving conflicts. The pairing reminder from upstream commit `8abd13363` was
intentionally omitted because this fork never polls comma's pairing service.

After a sync that touched anything under `selfdrive/controls`, drive a parking lot
before traffic. After a sync that touched the UI, look at the Navigation and Software
panels and the onroad banner on the device. Then push, and on the device use Software →
Check GitHub for updates → Update and reboot.

## Post-sync checklist

- `python3 scripts/test_fork.py` is green.
- `ruff check` on the files listed below is clean.
- The plug-in lines in each **upstream file we modify** are still present (grep for the
  markers in the table, they are all distinctive names).
- `process_config.py` still has no `manage_athenad`, `uploader` or `updated` entries and
  still has `incidentd`, `speedlimitd`, `navd`.
- `params_keys.h` still has the fork's keys.
- `services.py` still has `customReservedRawData1` and `customReservedRawData2`.
- If upstream changed the model or the planner interface, re-read `stop_profile.py` and
  the `shape_stop_accel` / `hold_stop_for_lead` hook in the planner; those depend on
  `modelV2.velocity` / `position` and `radarState.leadOne`.
- If upstream changed `cereal/log.capnp` `GpsLocationData` or `OnroadEvent`, re-check
  `speedlimitd.latest_fix` and `incidentd`.

## Files the fork owns

`scripts/upstream_sync.sh --files` prints the current differences from upstream. Snapshot at the time of writing:

### New files (no upstream counterpart, never conflict)

| Feature | Files |
|---|---|
| Incident preservation | `openpilot/system/loggerd/incidentd.py`, `.../tests/test_incidentd.py` |
| Stop profile | `openpilot/selfdrive/controls/lib/stop_profile.py`, `.../tests/test_stop_profile.py`, `.../tests/test_longitudinal_planner.py` |
| Offline map, speed limit, curve speed, pre-slow for limit drops and school zones, speed bumps | `openpilot/selfdrive/navd/{offline_map,build_map,speedlimitd,curve_speed,limit_ahead,conditional_limit,bump_speed}.py`, `navd/data/annarbor_ypsilanti.json.gz`, `navd/tests/test_speedlimit.py`, `navd/tests/test_curve_speed.py`, `navd/tests/test_limit_ahead.py`, `navd/tests/test_bump_speed.py` |
| Navigation, turn slowdown, Home/Work guess | `openpilot/selfdrive/navd/{router,navd,geocoder,build_addresses,turn_speed,auto_destination}.py`, `navd/data/annarbor_ypsilanti_addresses.json.gz`, `navd/tests/test_router.py`, `navd/tests/test_geocoder.py`, `navd/tests/test_turn_speed.py`, `navd/tests/test_auto_destination.py` |
| Navigation UI | `openpilot/selfdrive/ui/lib/nav_helpers.py`, `openpilot/selfdrive/ui/onroad/nav_banner.py`, `openpilot/selfdrive/ui/layouts/settings/navigation.py`, `openpilot/selfdrive/ui/mici/layouts/settings/navigation.py` |
| Nudgeless lane change | `openpilot/selfdrive/controls/lib/auto_lane_change.py`, `.../tests/test_auto_lane_change.py` |
| Self-update | `openpilot/system/self_update.py`, `openpilot/system/tests/test_self_update.py` |
| Settings presets | `openpilot/system/fork_presets.py`, `openpilot/system/tests/test_fork_presets.py`. The table of every setting, applied by manager on each boot. |
| Drive browser, kept footage | `openpilot/system/drive_browser.py`, `openpilot/system/tests/test_drive_browser.py`, `openpilot/system/loggerd/keep.py`, `openpilot/system/loggerd/tests/test_keep.py` |
| Screen recording | `openpilot/selfdrive/ui/screen_recorder.py`, `openpilot/selfdrive/ui/tests/test_screen_recorder.py`. Pipes the UI framebuffer to ffmpeg as `screen.mp4` in the current segment. |
| Per-car tuning | `openpilot/selfdrive/car/fork_tuning.py`, `openpilot/selfdrive/car/tests/test_fork_tuning.py`. All fork longitudinal constants come from here; add a car by adding a dict keyed by its fingerprint. |
| Fork tooling | `scripts/upstream_sync.sh`, `scripts/upstream_base.txt`, `scripts/test_fork.py`, `scripts/update_now.sh`, `docs/TRIETPILOT.md` |

### Upstream files we modify, and exactly what to look for after a sync

| File | What we changed | Marker to grep for |
|---|---|---|
| `openpilot/system/manager/process_config.py` | added `incidentd`, `drivebrowserd`, `speedlimitd`, `navd`; removed `manage_athenad`, `uploader`, `updated` | `speedlimitd` |
| `openpilot/system/manager/manager.py` | dongle id read locally, no `register()` call, no athena ignore list, `apply_presets` after the defaults loop | `never talks to` |
| `openpilot/system/manager/test/test_manager.py` | blacklist without `manage_athenad` | `BLACKLIST_PROCS` |
| `openpilot/common/params_keys.h` | `SpeedLimitCruise`, `AutoExperimentalMode`, `NudgelessLaneChange`, `NavTurnSlowdown`, `NavAutoHomeWork`, `RecordScreen`, `NavDestination`, `NavHome`, `NavWork` | `NavDestination` |
| `openpilot/cereal/services.py` | `customReservedRawData1` (5 Hz) and `customReservedRawData2` (2 Hz) | `customReservedRawData1` |
| `openpilot/selfdrive/controls/controlsd.py` | `latActive` also false on `overrideLateral` | `override_lateral` |
| `openpilot/selfdrive/controls/lib/desire_helper.py` | `auto_start` argument stands in for the steering nudge | `auto_start` |
| `openpilot/selfdrive/modeld/modeld.py` | subscribes `customReservedRawData1`, runs `AutoLaneChange`, reads `NudgelessLaneChange` | `AutoLaneChange` |
| `openpilot/selfdrive/controls/lib/longcontrol.py` | `STOPPING_DECEL_RATE`, jerk-limited start (`STARTING_JERK`, `starting_frames`) | `STARTING_JERK` |
| `openpilot/selfdrive/controls/lib/longitudinal_planner.py` | `hold_stop_for_lead`, `StopProfile` call, map speed caps (curve speed, limit ahead) from `customReservedRawData1`, nav turn cap from `customReservedRawData2`, `set_weights(..., v_ego=)` | `stop_profile` |
| `openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` | relaxed jerk factor 2.0, `get_low_speed_jerk_factor`, `set_weights` v_ego arg | `LOW_SPEED_JERK_FACTOR` |
| `openpilot/selfdrive/controls/plannerd.py` | subscribes to `customReservedRawData1/2` with ignore_alive/valid | `customReservedRawData1` |
| `openpilot/selfdrive/controls/tests/test_longcontrol.py` | tests for the stop/start changes | `TestLongControlSmoothStopGo` |
| `openpilot/selfdrive/car/cruise.py` | `parse_speed_limit_target`, `apply_speed_limit_target` | `apply_speed_limit_target` |
| `openpilot/selfdrive/car/card.py` | subscribes `customReservedRawData1`, calls `apply_speed_limit_target`, reads `SpeedLimitCruise` | `speed_limit_target_kph` |
| `openpilot/system/loggerd/deleter.py` | `MAX_LOG_BYTES` cap, `get_log_root_bytes`, kept segments (`keep.protected_kept`) deleted last | `MAX_LOG_BYTES` |
| `openpilot/system/loggerd/tests/test_deleter.py` | cap test | `test_delete_when_over_cap` |
| `openpilot/selfdrive/ui/ui.py` | `make_screen_recorder`, handed to `gui_app` before `init_window` | `make_screen_recorder` |
| `openpilot/system/ui/lib/application.py` | `set_screen_recorder`; render texture forced on, one `grab` per recorder tick after `end_drawing`, `stop` in `close` | `_screen_recorder` |
| `openpilot/selfdrive/ui/ui_state.py` | subscribes `gpsLocation`, `customReservedRawData1/2` | `customReservedRawData2` |
| `openpilot/selfdrive/ui/onroad/hud_renderer.py`, `.../mici/onroad/hud_renderer.py` | `NavBanner` created and rendered | `NavBanner` |
| `openpilot/selfdrive/ui/layouts/settings/settings.py`, `.../mici/layouts/settings/settings.py` | Navigation panel added, Firehose removed | `Navigation` |
| `openpilot/selfdrive/ui/layouts/settings/software.py`, `.../mici/layouts/settings/software.py` | rewritten: version info, GitHub self-update, uninstall. Take ours on conflict. | `self_update` |
| `openpilot/selfdrive/ui/lib/prime_state.py` | rewritten as an offline stub. Take ours on conflict. | `Offline stand-in` |
| `launch_chffrplus.sh` | no overlay update install, no AGNOS auto-update | `No overlay-based updates` |
| `README.md` | fork description. Take ours on conflict. | |

### Deleted upstream files

`openpilot/selfdrive/ui/layouts/settings/firehose.py` and the mici equivalent. If upstream
edits them a cherry-pick may report a deletion conflict; keep them deleted with `git rm`.

## Conflict playbook

- **A plug-in line moved or its surroundings changed**: keep the upstream version of the
  file, then re-add our lines using the marker table. Every plug-in is a handful of
  lines calling into fork-owned code.
- **Upstream added a process we do not want** (an uploader, a new athena daemon): drop it
  from `process_config.py`. Search for anything importing `openpilot.system.athena` or
  `system.updated` in `process_config.py` and `manager.py`.
- **Upstream changed `LongControl` or the planner structurally**: port the ideas, not the
  lines. The ideas are in each file's docstring and in the README feature list.
- **Upstream changed a UI widget API** (`Button`, `BigButton`, `Keyboard`, `NavScroller`):
  fix the fork-owned UI files to the new API; the panels are small.
- **Files marked "take ours"** above: `git checkout --ours <file>` then re-check they
  still import cleanly.

## Regenerating the map and address data

Both files under `openpilot/selfdrive/navd/data/` come from OpenStreetMap through the
Overpass API. The queries and the bounding box are in the docstrings of
`build_map.py` and `build_addresses.py`. Widen the box there to cover more area, run
the two scripts, and commit the regenerated `.json.gz` files. Nothing on the device
ever fetches map data.

The public Overpass servers reject requests without a User-Agent and are often busy;
`overpass.kumi.systems` tends to answer when `overpass-api.de` does not:

```bash
curl -A "TrietPilot-build-map/1.0" -o overpass.json --data-urlencode 'data=<query from build_map.py>' https://overpass.kumi.systems/api/interpreter
python3 openpilot/selfdrive/navd/build_map.py overpass.json openpilot/selfdrive/navd/data/annarbor_ypsilanti.json.gz
```

The map file is version 3: it carries the area's time zone, per way any
`maxspeed:conditional` school-zone rules parsed by `conditional_limit.py`, and the
traffic calming nodes (speed bumps) on the roads. Older files still load, without
whatever they lack.

## Running the fork's tests

`scripts/test_fork.py` stubs the native openpilot modules (capnp, msgq, acados, the car
interface) so the fork's pure-Python logic runs on any machine with `pytest` and
`numpy`. Every new fork feature should keep its logic testable that way: keep the
messaging loop in `main()` thin and put the logic in classes and functions that take
plain values.
