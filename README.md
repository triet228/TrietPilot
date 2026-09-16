# TrietPilot

TrietPilot is a fork of [openpilot](https://github.com/commaai/openpilot) created by Triet.

It runs on a [comma](https://comma.ai) device and lets AI drive the car.

## Features Triet added

- **Automatic incident preservation.** The dashcam keeps footage on its own when something happens: hard braking, an impact, a forward collision or AEB warning, or the panda dropping out. No need to press the bookmark button.
- **Per-axis driver override.** Turning the wheel pauses only steering while gas and brake stay automated. Pressing the gas pauses only gas and brake while steering stays automated. Let go and TrietPilot takes everything back. Pressing the brake still disengages fully because the panda safety firmware enforces that.
- **Professional stop profile.** When a red light, stop sign, or stopped car is predicted ahead, TrietPilot lifts off the gas far out and coasts, blends the brake in gently, squeezes firmly through the middle, then eases off in the last few metres so the car settles without rocking before the brake hold takes over. Red lights and stop signs need Experimental mode, since only the end-to-end model sees them.
- **Smooth stop and go.** In traffic the car waits until the lead has actually moved before launching, eases into the throttle instead of lurching, settles into the brake hold gently, and tapers the final approach to a stop. The relaxed personality is now noticeably softer than standard.

## Upstream

Everything else is unchanged from openpilot. See the [openpilot docs](https://docs.comma.ai) for setup, supported cars, and safety information.
