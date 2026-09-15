# TrietPilot

TrietPilot is a fork of [openpilot](https://github.com/commaai/openpilot) created by Triet.

It runs on a [comma](https://comma.ai) device and lets AI drive the car.

## Features Triet added

- **Automatic incident preservation.** The dashcam keeps footage on its own when something happens: hard braking, an impact, a forward collision or AEB warning, or the panda dropping out. No need to press the bookmark button.
- **Smooth stop and go.** In traffic the car waits until the lead has actually moved before launching, eases into the throttle instead of lurching, settles into the brake hold gently, and tapers the final approach to a stop. The relaxed personality is now noticeably softer than standard.

## Upstream

Everything else is unchanged from openpilot. See the [openpilot docs](https://docs.comma.ai) for setup, supported cars, and safety information.
