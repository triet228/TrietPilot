# openpilot/system/tests/test_drive_browser.py

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from openpilot.common.test import OpenpilotTestCase
import openpilot.system.drive_browser as db


def make_segment(root, name, files=("fcamera.hevc", "qcamera.ts", "rlog.zst"), size=1000, mtime=None):
  d = os.path.join(root, name)
  os.makedirs(d, exist_ok=True)
  for fn in files:
    with open(os.path.join(d, fn), "wb") as f:
      f.write(bytes(range(256)) * (size // 256) + bytes(size % 256))
  if mtime is not None:
    os.utime(d, (mtime, mtime))
  return d


class TestListing(OpenpilotTestCase):
  def setup_method(self):
    self.root = tempfile.mkdtemp()
    self.orig_preserved = db.is_preserved

  def teardown_method(self):
    db.is_preserved = self.orig_preserved
    shutil.rmtree(self.root, ignore_errors=True)

  def test_segment_info(self):
    make_segment(self.root, "0000000a--1a2b3c4d5e--3", size=512)
    s = db.segment_info(self.root, "0000000a--1a2b3c4d5e--3")
    assert s["route"] == "0000000a--1a2b3c4d5e" and s["index"] == 3
    assert s["size"] == 3 * 512 and s["playable"] and not s["preserved"]
    assert db.segment_info(self.root, "not-a-segment") is None
    os.makedirs(os.path.join(self.root, "clips"))
    assert db.segment_info(self.root, "clips") is None

  def test_routes_preserved_first_then_newest(self):
    now = 1_800_000_000.0  # any fixed epoch, only the ordering matters
    make_segment(self.root, "r1--0", mtime=now - 3000)
    make_segment(self.root, "r1--1", mtime=now - 2940)
    make_segment(self.root, "r2--0", mtime=now - 1000)
    make_segment(self.root, "r3--0", mtime=now - 9000)
    make_segment(self.root, "r3--2", mtime=now - 8880)
    db.is_preserved = lambda path: path.endswith("r3--2")
    routes = db.list_routes(self.root)
    assert [r["id"] for r in routes] == ["r3", "r2", "r1"]
    assert routes[0]["preserved"] and not routes[1]["preserved"]
    assert [s["index"] for s in routes[2]["segments"]] == [0, 1]
    assert routes[2]["duration"] == 2 * db.SEGMENT_LENGTH

  def test_render_index(self):
    make_segment(self.root, "r1--0")
    make_segment(self.root, "r1--1", files=("rlog.zst",))
    page = db.render_index(db.list_routes(self.root), None)
    assert "r1--0" in page and "play('r1--0'" in page
    assert "/file/r1--0/rlog.zst" in page
    assert "no video" in page  # a segment without camera files gets no Play button
    assert "No drives" not in page
    assert "No drives recorded yet" in db.render_index([], None)

  def test_format_size(self):
    assert db.format_size(500) == "500 B"
    assert db.format_size(3 * 1024 * 1024) == "3.0 MB"
    assert db.format_size(2.5 * 1024 ** 3) == "2.5 GB"


class TestServer(OpenpilotTestCase):
  def setup_method(self):
    self.root = tempfile.mkdtemp()
    self.cache = os.path.join(self.root, "cache")
    make_segment(self.root, "r1--0", size=3000)
    self.site = db.Site(self.root, self.cache)
    self.server = ThreadingHTTPServer(("127.0.0.1", 0), db.make_handler(self.site))
    self.server.daemon_threads = True
    threading.Thread(target=self.server.serve_forever, daemon=True).start()
    self.port = self.server.server_address[1]
    self.orig_encode = db.encode_command

  def teardown_method(self):
    db.encode_command = self.orig_encode
    self.server.shutdown()
    self.server.server_close()
    shutil.rmtree(self.root, ignore_errors=True)

  def get(self, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r, body

  def test_index_and_404(self):
    r, body = self.get("/")
    assert r.status == 200 and b"r1--0" in body
    r, _ = self.get("/nothing/here")
    assert r.status == 404
    r, _ = self.get("/file/r1--0/../../etc/passwd")
    assert r.status == 404
    r, _ = self.get("/file/r1--0/secret.txt")
    assert r.status == 404

  def test_raw_download_with_ranges(self):
    r, body = self.get("/file/r1--0/rlog.zst")
    assert r.status == 200 and len(body) == 3000
    assert "attachment" in r.getheader("Content-Disposition") and "r1--0--rlog.zst" in r.getheader("Content-Disposition")
    assert r.getheader("Accept-Ranges") == "bytes"
    r, body = self.get("/file/r1--0/qcamera.ts", {"Range": "bytes=100-199"})
    assert r.status == 206 and len(body) == 100
    assert r.getheader("Content-Range") == "bytes 100-199/3000"
    assert body == (bytes(range(256)) * 12)[100:200]
    r, body = self.get("/file/r1--0/qcamera.ts", {"Range": "bytes=2900-"})
    assert r.status == 206 and len(body) == 100
    r, _ = self.get("/file/r1--0/qcamera.ts", {"Range": "bytes=5000-6000"})
    assert r.status == 416

  def test_prepare_then_video(self):
    # stand in for encoderd/ffmpeg: copy the source to the output with python
    db.encode_command = lambda src, out: [sys.executable, "-c", "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])", src, out]
    r, body = self.get("/video/r1--0.mp4")
    assert r.status == 404  # not prepared yet
    r, body = self.get("/prepare/r1--0")
    assert r.status == 200 and json.loads(body)["status"] in ("working", "ready")
    for _ in range(100):
      r, body = self.get("/prepare/r1--0")
      if json.loads(body)["status"] == "ready":
        break
      time.sleep(0.1)
    assert json.loads(body)["status"] == "ready"
    assert os.path.exists(os.path.join(self.cache, "r1--0.mp4"))
    r, body = self.get("/video/r1--0.mp4", {"Range": "bytes=0-9"})
    assert r.status == 206 and len(body) == 10 and r.getheader("Content-Type") == "video/mp4"
    r, _ = self.get("/download/r1--0.mp4")
    assert r.status == 200 and "attachment" in r.getheader("Content-Disposition")

  def test_prepare_failures(self):
    db.encode_command = lambda src, out: None
    r, body = self.get("/prepare/r1--0")
    assert json.loads(body)["status"] == "unsupported"
    make_segment(self.root, "r1--1", size=100)
    db.encode_command = lambda src, out: [sys.executable, "-c", "import sys; sys.exit(3)"]
    self.get("/prepare/r1--1")
    for _ in range(100):
      r, body = self.get("/prepare/r1--1")
      if json.loads(body)["status"] != "working":
        break
      time.sleep(0.1)
    assert json.loads(body)["status"] == "failed"
    r, _ = self.get("/prepare/does-not-exist--0")
    assert r.status == 404

  def post(self, path):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
    conn.request("POST", path)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r, json.loads(body)

  def test_keep_buttons(self):
    store = set()
    orig = (db.keep.supported, db.keep.is_kept, db.keep.set_kept)
    db.keep.supported = lambda: True
    db.keep.is_kept = lambda p: p in store

    def set_kept(p, kept):
      before = p in store
      (store.add if kept else store.discard)(p)
      return before != kept
    db.keep.set_kept = set_kept
    try:
      for i in range(1, 30):
        make_segment(self.root, f"r1--{i}", size=100)
      make_segment(self.root, "r2--0", size=100)
      r, j = self.post("/keep/r1--15")
      assert r.status == 200 and j["changed"] == 21
      assert all(os.path.join(self.root, f"r1--{i}") in store for i in range(5, 26))
      assert os.path.join(self.root, "r1--4") not in store and os.path.join(self.root, "r2--0") not in store
      r, body = self.get("/")
      assert b"KEPT" in body and b"/unkeep/r1--15" in body and b"/keep/r1--3" in body
      assert b"/keep_route/r1" in body  # not every segment of r1 is kept yet
      r, j = self.post("/keep_route/r1")
      assert r.status == 200 and j["changed"] == 30 - 21
      r, body = self.get("/")
      assert b"/unkeep_route/r1" in body
      r, j = self.post("/unkeep/r1--0")
      assert r.status == 200 and j["changed"] == 11
      r, j = self.post("/unkeep_route/r1")
      assert r.status == 200 and not any("r1--" in p for p in store)
      r, j = self.post("/keep/nope--0")
      assert r.status == 404
      r, j = self.post("/keep_route/../etc")
      assert r.status == 404
      db.keep.supported = lambda: False
      r, j = self.post("/keep/r1--1")
      assert r.status == 501 and "extended attributes" in j["error"]
    finally:
      db.keep.supported, db.keep.is_kept, db.keep.set_kept = orig

  def test_prune_keeps_newest(self):
    os.makedirs(self.cache)
    for i in range(db.CACHE_KEEP + 5):
      p = os.path.join(self.cache, f"r--{i}.mp4")
      with open(p, "wb") as f:
        f.write(b"x")
      os.utime(p, (i, i))
    self.site.clips.prune()
    left = sorted(os.listdir(self.cache))
    assert len(left) == db.CACHE_KEEP
    assert "r--0.mp4" not in left and f"r--{db.CACHE_KEEP + 4}.mp4" in left
