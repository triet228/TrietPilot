# openpilot/selfdrive/ui/tests/test_screen_recorder.py

import io
import os
import shutil
import tempfile

from openpilot.common.test import OpenpilotTestCase
import openpilot.selfdrive.ui.screen_recorder as sr


class FakeProc:
  """Stands in for the ffmpeg Popen: records the frames written and whether it was closed."""
  instances = []

  def __init__(self, cmd, **kw):
    self.cmd = cmd
    self.out = cmd[-1]
    self.stdin = io.BytesIO()
    self.closed = False
    self.killed = False
    FakeProc.instances.append(self)

  def wait(self, timeout=None):
    self.closed = True
    return 0

  def kill(self):
    self.killed = True


class TestScreenRecorder(OpenpilotTestCase):
  def setup_method(self):
    self.root = tempfile.mkdtemp()
    self.route = None
    FakeProc.instances = []
    self.rec = sr.ScreenRecorder(self.root, lambda: self.route, 2160, 1080, popen=FakeProc, encoder=("libx264", ["-c:v", "libx264"]))

  def teardown_method(self):
    shutil.rmtree(self.root, ignore_errors=True)

  def seg(self, n, route="r1"):
    os.makedirs(os.path.join(self.root, f"{route}--{n}"), exist_ok=True)

  def test_frame_size_is_half_and_even(self):
    assert sr.frame_size(2160, 1080) == (1080, 540)
    assert sr.frame_size(1001, 501) == (500, 250)
    assert sr.frame_size(3, 3) == (2, 2)

  def test_ffmpeg_command_shape(self):
    cmd = sr.ffmpeg_command("/x/screen.mp4", 1080, 540, ["-c:v", "libx264"])
    assert cmd[0] == "ffmpeg" and cmd[-1] == "/x/screen.mp4"
    assert "1080x540" in cmd and "rgba" in cmd and "vflip,format=yuv420p" in cmd
    assert "+frag_keyframe+empty_moov+default_base_moof" in cmd  # playable when cut short

  def test_pick_encoder_prefers_x264_and_falls_back(self):
    class R:
      def __init__(self, s):
        self.stdout = s
    assert sr.pick_encoder(run=lambda *a, **k: R(" V..... libx264  x264\n V..... mpeg4 \n"))[0] == "libx264"
    assert sr.pick_encoder(run=lambda *a, **k: R(" V..... mpeg4 \n"))[0] == "mpeg4"
    assert sr.pick_encoder(run=lambda *a, **k: R(" V..... libx265 \n")) is None

    def boom(*a, **k):
      raise OSError("no ffmpeg")
    assert sr.pick_encoder(run=boom) is None

  def test_find_segment(self):
    assert sr.find_segment(self.root, "r1") is None
    assert sr.find_segment(self.root, None) is None
    self.seg(0)
    self.seg(1)
    assert sr.find_segment(self.root, "r1") == 1
    assert sr.find_segment(self.root, "r1", start=1) == 1
    self.seg(2)
    assert sr.find_segment(self.root, "r1", start=1) == 2

  def test_capture_due_paces_at_fps(self):
    r = self.rec
    assert r.capture_due(now=10.0)
    assert not r.capture_due(now=10.1)
    assert r.capture_due(now=10.2)
    assert not r.capture_due(now=10.3)
    assert r.capture_due(now=11.0)  # far behind: resync, no burst
    assert not r.capture_due(now=11.1)

  def test_offroad_writes_nothing(self):
    assert self.rec.tick(0.0) is False
    assert FakeProc.instances == []

  def test_follows_segment_rotation_and_blanks_when_screen_off(self):
    r = self.rec
    self.route = "r1"
    self.seg(0)
    r.submit(b"\x01" * (r.width * r.height * 4), now=0.0)
    assert r.tick(0.0) is True
    p0 = FakeProc.instances[-1]
    assert p0.out == os.path.join(self.root, "r1--0", "screen.mp4")
    assert p0.stdin.getvalue()[:1] == b"\x01"

    # screen off for longer than BLANK_AFTER: black frames, same file
    assert r.tick(0.0 + sr.BLANK_AFTER + 0.5) is True
    assert p0.stdin.getvalue()[-1:] == b"\x00"

    # loggerd rotates: old ffmpeg finished, new one on the new segment
    self.seg(1)
    assert r.tick(2.0) is True
    p1 = FakeProc.instances[-1]
    assert p0.closed and p1 is not p0
    assert p1.out == os.path.join(self.root, "r1--1", "screen.mp4")

    # going offroad closes the recording; a new route starts at its own segment 0
    self.route = None
    assert r.tick(3.5) is False
    assert p1.closed
    self.route = "r2"
    self.seg(0, route="r2")
    assert r.tick(5.0) is True
    assert FakeProc.instances[-1].out == os.path.join(self.root, "r2--0", "screen.mp4")

  def test_write_failure_closes_and_recovers(self):
    r = self.rec
    self.route = "r1"
    self.seg(0)
    assert r.tick(0.0)
    p0 = FakeProc.instances[-1]
    p0.stdin.close()  # ffmpeg died
    assert r.tick(0.2) is False
    assert r.proc is None
    assert r.tick(0.4) is True  # reopened on the same segment
    assert FakeProc.instances[-1] is not p0
