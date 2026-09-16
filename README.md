# TrietPilot

This is Triet's fork of [openpilot](https://github.com/commaai/openpilot) fine tuned for 2021 Toyota Corolla LE and local area Ypsilanti/Ann Arbor, Michigan, USA. It basically lets AI drive the car.

## Features Triet added

- **Automatic incident preservation.** The dashcam keeps footage on its own when something happens: hard braking, an impact, a forward collision or AEB warning, or the panda dropping out. No need to press the bookmark button.
- **Per-axis driver override.** Turning the wheel pauses only steering while gas and brake stay automated. Pressing the gas pauses only gas and brake while steering stays automated. Let go and TrietPilot takes everything back. Pressing the brake still disengages fully because the panda safety firmware enforces that.
- **Offline navigation.** Turn-by-turn routing on the same bundled Ann Arbor / Ypsilanti map, running entirely on the device with no internet. Park at home or work once and press "Set Home here" or "Set Work here" in the Navigation settings panel. After that a single press on "Go Home" or "Go to Work" routes you there. The onroad banner shows the next turn with distance, the turn after it, and the remaining distance and time. It re-routes automatically if you leave the route and clears the destination on arrival. Driving outside the mapped area gives "No route". You can also type a destination: "Go to address" takes a house number and street like `1234 Packard St`, with or without a city, or a place name like `Zingerman's`. Lookup runs against a bundled offline address book of about 16,600 addresses and 3,200 named places from OpenStreetMap. Abbreviations and misspellings are tolerated, and the closest house number is used when the exact one is missing, marked as approximate. Home and Work can be saved by address the same way.
- **Slow down for navigation turns.** While a route is active the car eases off ahead of the next maneuver so it arrives at the corner already at a sensible speed: about 16 mph for a turn, 9 mph for a U-turn, 25 mph for a slight turn or fork, 29 mph for a freeway exit, and 11 mph approaching the destination. It uses the same gentle approach law as curve speed control, holds the speed through the node, then lets the target rise back slowly. You still steer the turn; openpilot does not take intersections on its own. Merges and lane keeps get no slowdown, nothing happens while off route, and it only ever lowers the target. Turn it off with the `NavTurnSlowdown` param.
- **Speed limit cruise.** An offline map of Ann Arbor and Ypsilanti, built from OpenStreetMap and stored in the repo, gives the posted limit for the road the car is on. When engaged, the set speed follows the limit plus 10 mph on local roads or plus 20 mph on freeways. No internet is used. This works on the 2021 Corolla because openpilot runs its own longitudinal control on Toyota Safety Sense 2.0 cars and therefore owns the set speed; it would not work on a car whose stock cruise control keeps the set speed. Turn it off with the `SpeedLimitCruise` param.
- **Pre-slow for speed limit drops.** Speed limit cruise on its own only changes the set speed once the car has crossed onto the slower road, so it used to brake after the sign. Now the car looks about 400 m ahead along the same road walk that curve speed control uses, finds the next road whose cruise target is lower, and eases off at about 0.7 m/s² so it arrives at the sign already at the new target, then the new set speed takes over seamlessly. School zones work too: the map keeps OpenStreetMap's time-conditional limits, such as 25 mph on weekdays 8:20 to 8:50 and 15:45 to 16:15, and evaluates them in the map's own local time, so the car eases into the zone during its hours and treats it as an ordinary road otherwise. Public and school holiday exemptions are ignored on purpose, since the device has no holiday calendar and slowing for an empty school costs little. Like curve speed control this only ever lowers the target and stops at ambiguous forks and turns, so a freeway exit or side street can never pull the speed down.
- **Curve speed control.** The car looks about 300 m ahead along the road geometry in the offline map, works out the comfortable speed for every bend from its curvature, and eases off early so it enters each curve already at that speed instead of braking in it. The set speed on the screen does not change; the car just does not fill it through the bend and picks back up gently afterwards. The lateral comfort limit follows the driving personality: aggressive 2.5, standard 2.0, relaxed 1.6 m/s². It only ever lowers the target, and it stops looking ahead at ambiguous forks, so a wrong branch can only cause a brief unnecessary slowdown, never a speedup.
- **Automatic Experimental mode.** On local roads the car switches itself into Experimental mode so it stops for red lights and stop signs; when it gets onto a freeway it switches back to chill mode. It uses the same offline road classification as the speed limit cruise, only acts when the road type changes, so a manual toggle on the screen sticks until the next transition. Turn it off with the `AutoExperimentalMode` param.
- **Nudgeless lane change on freeways.** On a motorway or trunk road, signal and the car moves over on its own about a second later; no steering nudge needed. In town, or anywhere the offline map does not call a freeway, the upstream nudge is still required, using the same road classification as the speed limit cruise. The usual guards stay: lateral control active, above 20 mph, and the blind spot check for cars that report one. The 2021 Corolla LE has no blind spot monitor, so you are the blind spot monitor: check the mirror before you signal, and cancel the signal to abort. Turn it off with the `NudgelessLaneChange` param.
- **Professional stop profile.** When a red light, stop sign, or stopped car is predicted ahead, TrietPilot lifts off the gas far out and coasts, blends the brake in gently, squeezes firmly through the middle, then eases off in the last few metres so the car settles without rocking before the brake hold takes over. Red lights and stop signs need Experimental mode, since only the end-to-end model sees them.
- **Per-car tuning, set for the 2021 Corolla LE.** Every fork longitudinal constant reads from one table in `openpilot/selfdrive/car/fork_tuning.py`, keyed by car. The Corolla entry launches with a quicker, shorter ramp because the Toyota PCM is laggy and soft off the line, builds brake-hold pressure faster so the hold lands in about three seconds instead of five, re-launches behind a stopped lead with tighter hysteresis since its radar tracks close leads well, and eases the end of a stop slightly less to avoid a rolling finish. These are starting points from the port's known character, not from logs of this exact car; adjust the table after a few drives.
- **Smooth stop and go.** In traffic the car waits until the lead has actually moved before launching, eases into the throttle instead of lurching, settles into the brake hold gently, and tapers the final approach to a stop. The relaxed personality is now noticeably softer than standard.

## Getting footage off the device

With comma connect gone, the device serves its own drive browser over Wi-Fi. Enable tethering in the Network panel, join the hotspot, and open `http://192.168.43.1:8080` on your phone or laptop. When the device is on your home Wi-Fi instead, use its address there. The page lists every route with its segments, routes holding a preserved incident first, then newest first. Each segment has **Play**, **Download MP4**, and links to the raw files (`fcamera`, `qcamera`, `rlog`). The first Play or Download of a segment transcodes it once with the on-device hardware encoder, which takes a few seconds; the result is cached outside the log directory so the deleter never touches it, and the newest 30 clips are kept. Nothing leaves the device and no internet is used. Times shown are Detroit local time.

## No comma servers, no over-the-air updates

This fork never talks to comma's servers. The device does not register, upload drives, sync with comma connect, poll for prime status, or fetch software or AGNOS updates. The Firehose panel is gone and the Software panel only shows the running version. Logs and dashcam clips stay on the device, see the drive browser above. The deleter removes the oldest footage when free space runs low or when everything under the log directory passes 80 GB, whichever comes first, so the storage never fills up. Incident-preserved segments go last.

## Updating from GitHub

Updates come from this repo on GitHub and nowhere else. Connect the device to Wi-Fi in the Network panel, open the Software panel, and press **Check GitHub for updates**. It fetches and reports how many commits you are behind. Press **Update and reboot** to reset the checkout to the latest commit, sync submodules, and reboot; the launch script rebuilds on the way back up. Local edits on the device are discarded by an update, and the check tells you if there are any. The car must be off.

The same thing over SSH:

```bash
./scripts/update_now.sh
```

Add `--no-reboot` to update without rebooting, or run `python3 -m openpilot.system.self_update` to only check. If AGNOS ever needs a new version, flash it by hand; the launch script only prints a warning when the installed AGNOS does not match what the checkout expects.

## Keeping up with upstream openpilot

Every feature above lives in its own file or directory, and upstream files are touched only at a few small plug-in lines. [docs/TRIETPILOT.md](docs/TRIETPILOT.md) lists every file the fork owns, every upstream file it modifies with a grep marker for each change, and a conflict playbook.

```bash
scripts/upstream_sync.sh          # how far behind commaai/openpilot, and which files both sides touched
scripts/upstream_sync.sh --merge  # merge upstream/master
python3 scripts/test_fork.py      # run the fork's tests on any laptop, no native build needed
```

## Upstream

Everything else is unchanged from openpilot. See the [openpilot docs](https://docs.comma.ai) for setup, supported cars, and safety information.
