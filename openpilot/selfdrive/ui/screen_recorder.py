# openpilot/selfdrive/ui/screen_recorder.py

"""Screen recording for the dashcam: what the driver saw, next to what the cameras saw.

Only the UI process can see the framebuffer, so the recorder lives inside it. Every
SCREEN_FPS-th of a second the render loop shrinks its render texture to half size, reads
the pixels back once, and hands them here. A background thread pipes those frames to
ffmpeg, which writes `screen.mp4` into the segment directory loggerd is currently filling
(`<log_root>/<CurrentRoute>--<n>`), so the screen recording is rotated, kept, preserved
and deleted together with fcamera, dcamera and qcamera and shows up in the drive browser.

Timing is wall clock, not frame count: the writer thread emits exactly SCREEN_FPS frames
a second whatever the UI does, repeating the last frame when the render loop is slow and
sending black when the screen has been off for more than BLANK_AFTER seconds, so the
video stays in step with the camera files. The MP4 is fragmented so a segment cut short
by a power loss still plays. If ffmpeg is missing or has no usable encoder the recorder
logs once and does nothing.
"""

import os
import shutil
import subprocess
import threading
import time

from openpilot.common.swaglog import cloudlog

SCREEN_FPS = 5                  # frames a second, plenty for a UI and cheap on the CPU
SCREEN_SCALE = 0.5              # half of the 2160x1080 panel is still readable
BLANK_AFTER = 1.0               # s without a new frame before the recording shows black (screen off)
FILENAME = "screen.mp4"
ENCODERS = (                    # first available wins; AGNOS ffmpeg builds vary
  ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "28"]),
  ("h264_v4l2m2m", ["-c:v", "h264_v4l2m2m", "-b:v", "1M"]),
  ("mpeg4", ["-c:v", "mpeg4", "-q:v", "6"]),
)


def frame_size(width, height, scale=SCREEN_SCALE):
  """Recording resolution: the panel scaled down and rounded to even numbers for yuv420p."""
  w = max(2, int(width * scale))
  h = max(2, int(height * scale))
  return w + w % 2, h + h % 2


def pick_encoder(ffmpeg="ffmpeg", run=subprocess.run):
  """Name and arguments of the first encoder in ENCODERS that this ffmpeg has, or None."""
  try:
    out = run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
  except (OSError, subprocess.SubprocessError):
    return None
  for name, args in ENCODERS:
    if f" {name} " in out:
      return name, args
  return None


def ffmpeg_command(out_path, width, height, encoder_args, fps=SCREEN_FPS, ffmpeg="ffmpeg"):
  """ffmpeg invocation reading raw RGBA frames on stdin and writing a fragmented MP4."""
  return [
    ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin", "-y",
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
    "-vf", "vflip,format=yuv420p",        # render textures read back bottom-up
    *encoder_args,
    "-g", str(fps * 5),                   # a keyframe every 5 s so fragments stay small and seekable
    "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
    "-f", "mp4", out_path,
  ]


def find_segment(log_root, route, start=0):
  """Highest existing segment index for route at or above start, or None when none exists yet."""
  if not route:
    return None
  n = start
  found = None
  while os.path.isdir(os.path.join(log_root, f"{route}--{n}")):
    found = n
    n += 1
  return found


class ScreenRecorder:
  """Owns the writer thread and the ffmpeg process for the current segment.

  get_route returns the CurrentRoute param (or None offroad); it is called from the writer
  thread once a second, never from the render loop. capture_due / submit are the render
  loop's only two calls and touch nothing but a timestamp and a bytes reference.
  """

  def __init__(self, log_root, get_route, width, height, popen=subprocess.Popen, encoder=None):
    self.log_root = log_root
    self.get_route = get_route
    self.width, self.height = frame_size(width, height)
    self.popen = popen
    self.encoder = encoder
    self.period = 1.0 / SCREEN_FPS
    self.blank = bytes(self.width * self.height * 4)
    self.latest = None
    self.latest_time = 0.0
    self.next_capture = 0.0
    self.proc = None
    self.segment = None            # (route, index) the open ffmpeg writes to
    self.segment_index = None      # last index seen for self.route, so the scan does not restart at 0
    self.route = None
    self.route_checked = float("-inf")   # so the first tick polls whatever the clock says
    self.stop_event = threading.Event()
    self.thread = None
    self.lock = threading.Lock()

  # ---- render loop side ----

  def capture_due(self, now=None):
    """True when the render loop should read back a frame for this recording tick."""
    now = time.monotonic() if now is None else now
    if now < self.next_capture:
      return False
    # keep the cadence when on time, resync instead of bursting when far behind
    self.next_capture = self.next_capture + self.period if now - self.next_capture < self.period else now + self.period
    return True

  def submit(self, data, now=None):
    with self.lock:
      self.latest = data
      self.latest_time = time.monotonic() if now is None else now

  def grab(self, texture):
    """Downscale texture into the recording resolution and return its RGBA bytes. GL thread only."""
    import pyray as rl
    if not hasattr(self, "_small"):
      self._small = rl.load_render_texture(self.width, self.height)
      rl.set_texture_filter(self._small.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.begin_texture_mode(self._small)
    src = rl.Rectangle(0, 0, float(texture.width), -float(texture.height))
    dst = rl.Rectangle(0, 0, float(self.width), float(self.height))
    rl.draw_texture_pro(texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_texture_mode()
    image = rl.load_image_from_texture(self._small.texture)
    data = bytes(rl.ffi.buffer(image.data, image.width * image.height * 4))
    rl.unload_image(image)
    return data

  def release_gl(self):
    small = getattr(self, "_small", None)
    if small is not None:
      import pyray as rl
      rl.unload_render_texture(small)
      del self._small

  # ---- writer thread side ----

  def start(self):
    if self.encoder is None:
      if shutil.which("ffmpeg") is None:
        cloudlog.warning("screen_recorder: ffmpeg not found, screen will not be recorded")
        return False
      self.encoder = pick_encoder()
      if self.encoder is None:
        cloudlog.warning("screen_recorder: ffmpeg has none of %s, screen will not be recorded", [e[0] for e in ENCODERS])
        return False
    self.thread = threading.Thread(target=self._run, name="screen_recorder", daemon=True)
    self.thread.start()
    return True

  def stop(self):
    self.stop_event.set()
    if self.thread is not None:
      self.thread.join(timeout=10)
    self._close()

  def target_segment(self, now):
    """(route, index) loggerd is writing right now, or None offroad. Polls the route param once a second."""
    if now - self.route_checked >= 1.0:
      self.route_checked = now
      route = self.get_route()
      if route != self.route:
        self.route = route
        self.segment_index = None
    if not self.route:
      return None
    idx = find_segment(self.log_root, self.route, self.segment_index or 0)
    if idx is None:
      return None
    self.segment_index = idx
    return self.route, idx

  def frame_to_write(self, now):
    with self.lock:
      if self.latest is None or now - self.latest_time > BLANK_AFTER:
        return self.blank
      return self.latest

  def _open(self, segment):
    route, idx = segment
    out = os.path.join(self.log_root, f"{route}--{idx}", FILENAME)
    cmd = ffmpeg_command(out, self.width, self.height, self.encoder[1])
    try:
      self.proc = self.popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      self.segment = segment
    except OSError as e:
      cloudlog.error(f"screen_recorder: could not start ffmpeg: {e}")
      self.proc = None
      self.segment = None

  def _close(self):
    proc, self.proc, self.segment = self.proc, None, None
    if proc is None:
      return
    try:
      proc.stdin.close()
      proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
      proc.kill()
      proc.wait()

  def tick(self, now):
    """One writer step: follow segment rotation, then push one frame. Returns True if a frame was written."""
    segment = self.target_segment(now)
    if segment != self.segment:
      self._close()
      if segment is not None:
        self._open(segment)
    if self.proc is None:
      return False
    try:
      self.proc.stdin.write(self.frame_to_write(now))
      return True
    except (OSError, ValueError) as e:
      cloudlog.error(f"screen_recorder: ffmpeg write failed: {e}")
      self._close()
      return False

  def _run(self):
    next_tick = time.monotonic()
    while not self.stop_event.is_set():
      now = time.monotonic()
      if now < next_tick:
        time.sleep(min(next_tick - now, 0.05))
        continue
      self.tick(now)
      next_tick += self.period
      if now - next_tick > 1.0:   # fell far behind (suspend); do not burst-write a second of frames
        next_tick = now + self.period
