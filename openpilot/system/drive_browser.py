# openpilot/system/drive_browser.py

"""Drive browser: dashcam footage over Wi-Fi, no comma connect needed.

A small web server on the device (port 8080) lists every recorded route with its
segments, preserved incidents first, and offers a Play and a Download button per
segment plus links to the raw files. Join the device's hotspot and open

  http://192.168.43.1:8080

or, when the device is on your home Wi-Fi, its address there. Nothing leaves the
device; the page is plain HTML served from this file and the browser talks only to
the device.

Playing a segment needs an MP4 the browser can decode. loggerd writes raw HEVC
(fcamera.hevc) and a tiny MPEG-TS preview (qcamera.ts), neither of which a browser
plays directly, so the first Play or Download of a segment transcodes it once with the
on-device clip encoder (`encoderd --clip`, hardware H.264, the same path comma connect
clips use) into a cache next to the log directory. On a PC ffmpeg is used instead.
The cache keeps the newest CACHE_KEEP clips and is outside realdata, so deleter never
sees it and it never counts against the log budget.

Route directories are `<route>--<segment>`; the route id carries no date, so times
shown are the segment directory's creation time in the map area's time zone.
"""

import datetime
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zoneinfo
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from openpilot.common.basedir import BASEDIR
from openpilot.common.hardware import PC
from openpilot.common.swaglog import cloudlog

PORT = 8080
SEGMENT_RE = re.compile(r"^([A-Za-z0-9_-]+?)--(\d+)$")
RAW_FILES = ("fcamera.hevc", "ecamera.hevc", "dcamera.hevc", "qcamera.ts", "rlog.zst", "qlog.zst")
CONTENT_TYPES = {".mp4": "video/mp4", ".ts": "video/mp2t", ".hevc": "application/octet-stream", ".zst": "application/zstd"}
PRESERVE_ATTR = "user.preserve"  # set by loggerd on a userBookmark, honoured by deleter
SEGMENT_LENGTH = 60               # s, mirrors system/loggerd/config.py without importing the hardware layer
CACHE_KEEP = 30                   # transcoded clips kept, newest first
CLIP_BITRATE = 3_000_000          # bps for the browser MP4, ~22 MB a minute
ENCODE_TIMEOUT = 300              # s before a stuck transcode is abandoned
DISPLAY_TZ = "America/Detroit"
CHUNK = 1 << 20


def is_preserved(path):
  """True when loggerd marked the segment directory as preserved (incident or bookmark)."""
  getxattr = getattr(os, "getxattr", None)
  if getxattr is None:
    return False
  try:
    return getxattr(path, PRESERVE_ATTR) == b"1"
  except OSError:
    return False


def display_tz():
  try:
    return zoneinfo.ZoneInfo(DISPLAY_TZ)
  except (zoneinfo.ZoneInfoNotFoundError, ValueError):
    return None  # falls back to the device's local time


def format_time(ts, tz):
  return datetime.datetime.fromtimestamp(ts, tz).strftime("%a %b %d, %H:%M")


def format_size(n):
  for unit in ("B", "KB", "MB", "GB"):
    if n < 1024 or unit == "GB":
      return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
    n /= 1024.0
  return f"{n:.1f} GB"


def segment_info(root, name):
  """Files, size, time and preserved flag of one segment directory, or None if it is not one."""
  m = SEGMENT_RE.match(name)
  path = os.path.join(root, name)
  if m is None or not os.path.isdir(path):
    return None
  files = {}
  for fn in RAW_FILES:
    try:
      files[fn] = os.path.getsize(os.path.join(path, fn))
    except OSError:
      continue
  try:
    mtime = os.stat(path).st_mtime
  except OSError:
    mtime = 0.0
  return {
    "name": name,
    "route": m.group(1),
    "index": int(m.group(2)),
    "files": files,
    "size": sum(files.values()),
    "mtime": mtime,
    "preserved": is_preserved(path),
    "playable": "fcamera.hevc" in files or "qcamera.ts" in files,
  }


def list_routes(root):
  """Routes with their segments in order. Routes holding a preserved segment come first, then newest first."""
  by_route = {}
  try:
    names = os.listdir(root)
  except OSError:
    names = []
  for name in names:
    seg = segment_info(root, name)
    if seg is not None:
      by_route.setdefault(seg["route"], []).append(seg)
  routes = []
  for rid, segs in by_route.items():
    segs.sort(key=lambda s: s["index"])
    routes.append({
      "id": rid,
      "segments": segs,
      "preserved": any(s["preserved"] for s in segs),
      "start": min(s["mtime"] for s in segs),
      "size": sum(s["size"] for s in segs),
      "duration": len(segs) * SEGMENT_LENGTH,
    })
  routes.sort(key=lambda r: (not r["preserved"], -r["start"]))
  return routes


def encode_command(src, out):
  """Command that turns a segment's camera file into a browser MP4, or None when nothing on this machine can."""
  encoderd = os.path.join(BASEDIR, "openpilot/system/loggerd/encoderd")
  if src.endswith(".hevc") and not PC and os.path.exists(encoderd):
    return [encoderd, "--clip", out, "0", str(SEGMENT_LENGTH), "--bitrate", str(CLIP_BITRATE), "--", src]
  if shutil.which("ffmpeg"):
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if src.endswith(".ts"):
      # the qcamera preview is already H.264, so this is a remux and takes well under a second
      return base + ["-i", src, "-c", "copy", "-movflags", "+faststart", out]
    return base + ["-f", "hevc", "-r", "20", "-i", src, "-c:v", "libx264", "-preset", "veryfast",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
  return None


def pick_source(root, name):
  """Camera file to transcode: full-resolution fcamera on the device, qcamera on a PC (remux, no re-encode)."""
  order = ("qcamera.ts", "fcamera.hevc") if PC else ("fcamera.hevc", "qcamera.ts")
  for fn in order:
    p = os.path.join(root, name, fn)
    if os.path.exists(p):
      return p
  return None


class ClipCache:
  """Transcodes segments to MP4 on demand, one at a time, and keeps the newest CACHE_KEEP results."""

  def __init__(self, root, cache_dir):
    self.root = root
    self.cache_dir = cache_dir
    self.lock = threading.Lock()
    self.working = set()
    self.failed = {}

  def path(self, name):
    return os.path.join(self.cache_dir, name + ".mp4")

  def status(self, name):
    """ready, working, failed, unsupported, or missing."""
    if os.path.exists(self.path(name)):
      return "ready"
    with self.lock:
      if name in self.working:
        return "working"
      if name in self.failed:
        return self.failed[name]
    return "missing"

  def prepare(self, name):
    """Kicks off the transcode in the background if needed. Returns the status after doing so."""
    st = self.status(name)
    if st != "missing":
      return st
    src = pick_source(self.root, name)
    if src is None or encode_command(src, self.path(name)) is None:
      with self.lock:
        self.failed[name] = "unsupported"
      return "unsupported"
    with self.lock:
      self.working.add(name)
    threading.Thread(target=self._encode, args=(name, src), daemon=True).start()
    return "working"

  def _encode(self, name, src):
    out = self.path(name)
    tmp = out + ".part"
    try:
      os.makedirs(self.cache_dir, exist_ok=True)
      cmd = encode_command(src, tmp)
      t0 = time.monotonic()
      subprocess.run(cmd, check=True, timeout=ENCODE_TIMEOUT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
      os.replace(tmp, out)
      cloudlog.info(f"drive_browser: transcoded {name} in {time.monotonic() - t0:.1f}s")
      self.prune()
    except (OSError, subprocess.SubprocessError) as e:
      cloudlog.warning(f"drive_browser: transcode of {name} failed: {e}")
      with self.lock:
        self.failed[name] = "failed"
    finally:
      with self.lock:
        self.working.discard(name)
      try:
        os.unlink(tmp)
      except OSError:
        pass

  def prune(self):
    try:
      clips = [os.path.join(self.cache_dir, f) for f in os.listdir(self.cache_dir) if f.endswith(".mp4")]
    except OSError:
      return
    clips.sort(key=os.path.getmtime, reverse=True)
    for p in clips[CACHE_KEEP:]:
      try:
        os.unlink(p)
      except OSError:
        pass


# ---- page -------------------------------------------------------------------

PAGE_HEAD = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrietPilot drives</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}
header{padding:14px 18px;background:#000;position:sticky;top:0;display:flex;align-items:baseline;gap:14px}
h1{margin:0;font-size:18px} header span{color:#999;font-size:13px}
#player{width:100%;max-height:60vh;background:#000;display:none}
#status{padding:8px 18px;color:#bbb;font-size:14px;min-height:18px}
.route{margin:14px 18px;border:1px solid #333;border-radius:8px;overflow:hidden}
.route h2{margin:0;padding:10px 14px;background:#1c1c1c;font-size:15px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.route h2 small{color:#999;font-weight:normal}
.badge{background:#c0392b;color:#fff;border-radius:4px;padding:2px 6px;font-size:12px}
.badge.seg{background:#7a2a22}
table{width:100%;border-collapse:collapse} td{padding:7px 14px;border-top:1px solid #222;font-size:14px;vertical-align:middle}
td.n{color:#999;width:40px} td.t{white-space:nowrap} td.s{color:#999;white-space:nowrap}
td.a{text-align:right;white-space:nowrap}
button,a.btn{background:#2d6cdf;color:#fff;border:0;border-radius:5px;padding:6px 10px;font-size:13px;cursor:pointer;text-decoration:none;margin-left:4px}
button.alt,a.alt{background:#333} a.raw{color:#8ab4f8;font-size:12px;margin-left:6px;text-decoration:none}
tr.playing td{background:#182338}
.empty{padding:40px 18px;color:#999;text-align:center}
</style></head><body>
<header><h1>TrietPilot drives</h1><span>__SUMMARY__</span></header>
<video id="player" controls playsinline></video>
<div id="status"></div>
"""

PAGE_TAIL = """<script>
const player = document.getElementById('player'), status = document.getElementById('status');
let current = null;
async function prepare(name, onReady) {
  let t0 = Date.now();
  for (;;) {
    let st;
    try { st = (await (await fetch('/prepare/' + name)).json()).status; } catch (e) { st = 'failed'; }
    if (st === 'ready') { status.textContent = ''; onReady(); return; }
    if (st === 'failed' || st === 'unsupported' || st === 'missing') { status.textContent = name + ': cannot prepare video (' + st + ')'; return; }
    status.textContent = 'Preparing ' + name + '… ' + Math.round((Date.now() - t0) / 1000) + ' s';
    await new Promise(r => setTimeout(r, 1500));
  }
}
function play(name, row) {
  prepare(name, () => {
    document.querySelectorAll('tr.playing').forEach(r => r.classList.remove('playing'));
    row.classList.add('playing');
    player.style.display = 'block';
    player.src = '/video/' + name + '.mp4';
    player.play();
    window.scrollTo({top: 0, behavior: 'smooth'});
  });
}
function download(name) {
  prepare(name, () => { window.location.href = '/download/' + name + '.mp4'; });
}
</script></body></html>
"""


def render_index(routes, tz):
  total = sum(r["size"] for r in routes)
  summary = f"{len(routes)} routes, {format_size(total)}, {sum(r['preserved'] for r in routes)} preserved"
  out = [PAGE_HEAD.replace("__SUMMARY__", html.escape(summary))]
  if not routes:
    out.append('<div class="empty">No drives recorded yet.</div>')
  for r in routes:
    rid = html.escape(r["id"])
    badge = '<span class="badge">PRESERVED</span>' if r["preserved"] else ""
    meta = f'{r["duration"] // 60} min, {format_size(r["size"])}, {len(r["segments"])} segments'
    out.append(f'<div class="route"><h2>{html.escape(format_time(r["start"], tz))} {badge}<small>{meta}</small><small>{rid}</small></h2><table>')
    for s in r["segments"]:
      name = html.escape(s["name"])
      seg_badge = ' <span class="badge seg">kept</span>' if s["preserved"] else ""
      raw = "".join(f'<a class="raw" href="/file/{name}/{fn}" download>{fn.split(".")[0]}</a>' for fn in s["files"])
      if s["playable"]:
        play = f'<button onclick="play(\'{name}\', this.closest(\'tr\'))">Play</button>'
        actions = play + f'<button class="alt" onclick="download(\'{name}\')">Download MP4</button>'
      else:
        actions = '<span class="s">no video</span>'
      when = html.escape(format_time(s["mtime"], tz))
      out.append(f'<tr><td class="n">{s["index"]}</td><td class="t">{when}{seg_badge}</td>')
      out.append(f'<td class="s">{format_size(s["size"])}{raw}</td><td class="a">{actions}</td></tr>')
    out.append("</table></div>")
  out.append(PAGE_TAIL)
  return "".join(out)


# ---- server -----------------------------------------------------------------

class Site:
  def __init__(self, root, cache_dir):
    self.root = root
    self.clips = ClipCache(root, cache_dir)
    self.tz = display_tz()

  def segment_dir(self, name):
    """Absolute segment directory for a validated name, or None."""
    if SEGMENT_RE.match(name) is None:
      return None
    p = os.path.join(self.root, name)
    return p if os.path.isdir(p) else None


def make_handler(site):
  class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
      pass

    def do_GET(self):
      path = self.path.split("?", 1)[0]
      parts = [p for p in path.split("/") if p]
      try:
        if not parts:
          body = render_index(list_routes(site.root), site.tz).encode()
          return self.send_bytes(200, body, "text/html; charset=utf-8")
        if parts[0] == "prepare" and len(parts) == 2 and site.segment_dir(parts[1]):
          st = site.clips.prepare(parts[1])
          return self.send_bytes(200, json.dumps({"status": st}).encode(), "application/json")
        if parts[0] in ("video", "download") and len(parts) == 2 and parts[1].endswith(".mp4"):
          name = parts[1][:-4]
          if site.segment_dir(name) and site.clips.status(name) == "ready":
            return self.send_file(site.clips.path(name), attachment=(parts[0] == "download"))
        if parts[0] == "file" and len(parts) == 3 and parts[2] in RAW_FILES:
          d = site.segment_dir(parts[1])
          if d and os.path.exists(os.path.join(d, parts[2])):
            return self.send_file(os.path.join(d, parts[2]), attachment=True, name=f"{parts[1]}--{parts[2]}")
        self.send_bytes(404, b"not found", "text/plain")
      except (BrokenPipeError, ConnectionResetError):
        pass

    def send_bytes(self, code, body, ctype):
      self.send_response(code)
      self.send_header("Content-Type", ctype)
      self.send_header("Content-Length", str(len(body)))
      self.send_header("Cache-Control", "no-store")
      self.end_headers()
      self.wfile.write(body)

    def send_file(self, path, attachment=False, name=None):
      """Streams a file with byte-range support, which video seeking in the browser needs."""
      size = os.path.getsize(path)
      start, end = 0, size - 1
      rng = self.headers.get("Range", "")
      partial = False
      if rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        try:
          start = int(a) if a else max(0, size - int(b))
          end = int(b) if a and b else end
          partial = True
        except ValueError:
          start, end, partial = 0, size - 1, False
        if start > end or start >= size:
          self.send_response(416)
          self.send_header("Content-Range", f"bytes */{size}")
          self.send_header("Content-Length", "0")
          self.end_headers()
          return
      self.send_response(206 if partial else 200)
      self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))
      self.send_header("Content-Length", str(end - start + 1))
      self.send_header("Accept-Ranges", "bytes")
      if partial:
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
      if attachment:
        self.send_header("Content-Disposition", f'attachment; filename="{name or os.path.basename(path)}"')
      self.end_headers()
      with open(path, "rb") as f:
        f.seek(start)
        left = end - start + 1
        while left > 0:
          chunk = f.read(min(CHUNK, left))
          if not chunk:
            break
          self.wfile.write(chunk)
          left -= len(chunk)

  return Handler


def serve(root, cache_dir, port=PORT, host=""):
  """Blocks serving the drive browser. Returns only if the socket cannot be bound."""
  server = ThreadingHTTPServer((host, port), make_handler(Site(root, cache_dir)))
  server.daemon_threads = True
  cloudlog.info(f"drive_browser: serving {root} on port {server.server_address[1]}")
  server.serve_forever()


def default_paths():
  from openpilot.common.hardware.hw import Paths
  root = Paths.log_root()
  # next to realdata, so deleter (which only walks realdata) never touches the cache
  cache = os.path.join(os.path.dirname(root.rstrip("/")), "drive_browser")
  return root, cache


def main():
  root, cache = default_paths()
  while True:
    try:
      serve(root, cache)
    except OSError as e:
      cloudlog.warning(f"drive_browser: bind failed ({e}), retrying")
      time.sleep(10)


if __name__ == "__main__":
  main()
