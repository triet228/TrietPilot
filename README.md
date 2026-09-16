# TrietPilot

This is Triet's fork of [openpilot](https://github.com/commaai/openpilot) fine tuned for 2021 Toyota Corolla LE and local area Ypsilanti/Ann Arbor, Michigan, USA. It basically lets AI drive the car.

## Features Triet added

- **Automatic incident preservation.** The dashcam keeps footage on its own when something happens: hard braking, an impact, a forward collision or AEB warning, or the panda dropping out. No need to press the bookmark button.
- **Per-axis driver override.** Turning the wheel pauses only steering while gas and brake stay automated. Pressing the gas pauses only gas and brake while steering stays automated. Let go and TrietPilot takes everything back. Pressing the brake still disengages fully because the panda safety firmware enforces that.
- **Offline navigation.** Turn-by-turn routing on the same bundled Ann Arbor / Ypsilanti map, running entirely on the device with no internet. Park at home or work once and press "Set Home here" or "Set Work here" in the Navigation settings panel. After that a single press on "Go Home" or "Go to Work" routes you there. The onroad banner shows the next turn with distance, the turn after it, and the remaining distance and time. It re-routes automatically if you leave the route and clears the destination on arrival. Driving outside the mapped area gives "No route".
- **Speed limit cruise.** An offline map of Ann Arbor and Ypsilanti, built from OpenStreetMap and stored in the repo, gives the posted limit for the road the car is on. When engaged, the set speed follows the limit plus 10 mph on local roads or plus 20 mph on freeways. No internet is used. This works on the 2021 Corolla because openpilot runs its own longitudinal control on Toyota Safety Sense 2.0 cars and therefore owns the set speed; it would not work on a car whose stock cruise control keeps the set speed. Turn it off with the `SpeedLimitCruise` param.
- **Automatic Experimental mode.** On local roads the car switches itself into Experimental mode so it stops for red lights and stop signs; when it gets onto a freeway it switches back to chill mode. It uses the same offline road classification as the speed limit cruise, only acts when the road type changes, so a manual toggle on the screen sticks until the next transition. Turn it off with the `AutoExperimentalMode` param.
- **Professional stop profile.** When a red light, stop sign, or stopped car is predicted ahead, TrietPilot lifts off the gas far out and coasts, blends the brake in gently, squeezes firmly through the middle, then eases off in the last few metres so the car settles without rocking before the brake hold takes over. Red lights and stop signs need Experimental mode, since only the end-to-end model sees them.
- **Smooth stop and go.** In traffic the car waits until the lead has actually moved before launching, eases into the throttle instead of lurching, settles into the brake hold gently, and tapers the final approach to a stop. The relaxed personality is now noticeably softer than standard.

## No comma servers, no over-the-air updates

This fork never talks to comma's servers. The device does not register, upload drives, sync with comma connect, poll for prime status, or fetch software or AGNOS updates. The Firehose panel is gone and the Software panel only shows the running version. Logs and dashcam clips stay on the device. The deleter removes the oldest footage when free space runs low or when everything under the log directory passes 80 GB, whichever comes first, so the storage never fills up. Incident-preserved segments go last.

To update, SSH into the device and pull this repo yourself, then reboot. If AGNOS ever needs a new version, flash it by hand; the launch script only prints a warning when the installed AGNOS does not match what the checkout expects.

## Upstream

Everything else is unchanged from openpilot. See the [openpilot docs](https://docs.comma.ai) for setup, supported cars, and safety information.
