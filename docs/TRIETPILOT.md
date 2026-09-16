# TrietPilot fork guide

How this fork is organized, what it owns, and how to pull in new upstream openpilot
releases without losing anything. Read this before every upstream merge.

## The one rule

Every feature lives in its own new file or directory. Upstream files are touched only
where the feature has to plug in, and each of those touches is a few lines that call
into fork-owned code. When upstream changes a file we also changed, the conflict is
almost always in one of those small plug-in spots, and the fix is to re-apply the
same few lines in the new upstream shape.

## Syncing with upstream

```bash
scripts/upstream_sync.sh          # how far behind, and which files both sides touched
scripts/upstream_sync.sh --merge  # merge upstream/master
python3 scripts/test_fork.py      # the fork's tests, runs on a laptop with no native build
```

Merge, do not rebase. History is pushed and the device pulls with a hard reset, so
rewriting it would strand the device.

After a merge that touched anything under `selfdrive/controls`, drive a parking lot
before traffic. After a merge that touched the UI, look at the Navigation and Software
panels and the onroad banner on the device. Then push, and on the device use Software →
Check GitHub for updates → Update and reboot.

## Post-merge checklist

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

`scripts/upstream_sync.sh --files` prints the live list. Snapshot at the time of writing:

### New files (no upstream counterpart, never conflict)

| Feature | Files |
|---|---|
| Incident preservation | `openpilot/system/loggerd/incidentd.py`, `.../tests/test_incidentd.py` |
| Stop profile | `openpilot/selfdrive/controls/lib/stop_profile.py`, `.../tests/test_stop_profile.py`, `.../tests/test_longitudinal_planner.py` |
| Offline map, speed limit, curve speed, pre-slow for limit drops and school zones | `openpilot/selfdrive/navd/{offline_map,build_map,speedlimitd,curve_speed,limit_ahead,conditional_limit}.py`, `navd/data/annarbor_ypsilanti.json.gz`, `navd/tests/test_speedlimit.py`, `navd/tests/test_curve_speed.py`, `navd/tests/test_limit_ahead.py` |
| Navigation | `openpilot/selfdrive/navd/{router,navd,geocoder,build_addresses}.py`, `navd/data/annarbor_ypsilanti_addresses.json.gz`, `navd/tests/test_router.py`, `navd/tests/test_geocoder.py` |
| Navigation UI | `openpilot/selfdrive/ui/lib/nav_helpers.py`, `openpilot/selfdrive/ui/onroad/nav_banner.py`, `openpilot/selfdrive/ui/layouts/settings/navigation.py`, `openpilot/selfdrive/ui/mici/layouts/settings/navigation.py` |
| Nudgeless lane change | `openpilot/selfdrive/controls/lib/auto_lane_change.py`, `.../tests/test_auto_lane_change.py` |
| Self-update | `openpilot/system/self_update.py`, `openpilot/system/tests/test_self_update.py` |
| Per-car tuning | `openpilot/selfdrive/car/fork_tuning.py`, `openpilot/selfdrive/car/tests/test_fork_tuning.py`. All fork longitudinal constants come from here; add a car by adding a dict keyed by its fingerprint. |
| Fork tooling | `scripts/upstream_sync.sh`, `scripts/test_fork.py`, `scripts/update_now.sh`, `docs/TRIETPILOT.md` |

### Upstream files we modify, and exactly what to look for after a merge

| File | What we changed | Marker to grep for |
|---|---|---|
| `openpilot/system/manager/process_config.py` | added `incidentd`, `speedlimitd`, `navd`; removed `manage_athenad`, `uploader`, `updated` | `speedlimitd` |
| `openpilot/system/manager/manager.py` | dongle id read locally, no `register()` call, no athena ignore list | `never talks to` |
| `openpilot/system/manager/test/test_manager.py` | blacklist without `manage_athenad` | `BLACKLIST_PROCS` |
| `openpilot/common/params_keys.h` | `SpeedLimitCruise`, `AutoExperimentalMode`, `NudgelessLaneChange`, `NavDestination`, `NavHome`, `NavWork` | `NavDestination` |
| `openpilot/cereal/services.py` | `customReservedRawData1` (5 Hz) and `customReservedRawData2` (2 Hz) | `customReservedRawData1` |
| `openpilot/selfdrive/controls/controlsd.py` | `latActive` also false on `overrideLateral` | `override_lateral` |
| `openpilot/selfdrive/controls/lib/desire_helper.py` | `auto_start` argument stands in for the steering nudge | `auto_start` |
| `openpilot/selfdrive/modeld/modeld.py` | subscribes `customReservedRawData1`, runs `AutoLaneChange`, reads `NudgelessLaneChange` | `AutoLaneChange` |
| `openpilot/selfdrive/controls/lib/longcontrol.py` | `STOPPING_DECEL_RATE`, jerk-limited start (`STARTING_JERK`, `starting_frames`) | `STARTING_JERK` |
| `openpilot/selfdrive/controls/lib/longitudinal_planner.py` | `hold_stop_for_lead`, `StopProfile` call, map speed caps (curve speed, limit ahead) from `customReservedRawData1`, `set_weights(..., v_ego=)` | `stop_profile` |
| `openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` | relaxed jerk factor 2.0, `get_low_speed_jerk_factor`, `set_weights` v_ego arg | `LOW_SPEED_JERK_FACTOR` |
| `openpilot/selfdrive/controls/plannerd.py` | subscribes to `customReservedRawData1` with ignore_alive/valid | `customReservedRawData1` |
| `openpilot/selfdrive/controls/tests/test_longcontrol.py` | tests for the stop/start changes | `TestLongControlSmoothStopGo` |
| `openpilot/selfdrive/car/cruise.py` | `parse_speed_limit_target`, `apply_speed_limit_target` | `apply_speed_limit_target` |
| `openpilot/selfdrive/car/card.py` | subscribes `customReservedRawData1`, calls `apply_speed_limit_target`, reads `SpeedLimitCruise` | `speed_limit_target_kph` |
| `openpilot/system/loggerd/deleter.py` | `MAX_LOG_BYTES` cap and `get_log_root_bytes` | `MAX_LOG_BYTES` |
| `openpilot/system/loggerd/tests/test_deleter.py` | cap test | `test_delete_when_over_cap` |
| `openpilot/selfdrive/ui/ui_state.py` | subscribes `gpsLocation`, `customReservedRawData1/2` | `customReservedRawData2` |
| `openpilot/selfdrive/ui/onroad/hud_renderer.py`, `.../mici/onroad/hud_renderer.py` | `NavBanner` created and rendered | `NavBanner` |
| `openpilot/selfdrive/ui/layouts/settings/settings.py`, `.../mici/layouts/settings/settings.py` | Navigation panel added, Firehose removed | `Navigation` |
| `openpilot/selfdrive/ui/layouts/settings/software.py`, `.../mici/layouts/settings/software.py` | rewritten: version info, GitHub self-update, uninstall. Take ours on conflict. | `self_update` |
| `openpilot/selfdrive/ui/lib/prime_state.py` | rewritten as an offline stub. Take ours on conflict. | `Offline stand-in` |
| `launch_chffrplus.sh` | no overlay update install, no AGNOS auto-update | `No overlay-based updates` |
| `README.md` | fork description. Take ours on conflict. | |

### Deleted upstream files

`openpilot/selfdrive/ui/layouts/settings/firehose.py` and the mici equivalent. If upstream
edits them the merge will say "deleted by us"; keep them deleted with `git rm`.

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

The map file is version 2: it carries the area's time zone and, per way, any
`maxspeed:conditional` school-zone rules parsed by `conditional_limit.py`. Version 1
files still load, with no conditional limits.

## Running the fork's tests

`scripts/test_fork.py` stubs the native openpilot modules (capnp, msgq, acados, the car
interface) so the fork's pure-Python logic runs on any machine with `pytest` and
`numpy`. Every new fork feature should keep its logic testable that way: keep the
messaging loop in `main()` thin and put the logic in classes and functions that take
plain values.
