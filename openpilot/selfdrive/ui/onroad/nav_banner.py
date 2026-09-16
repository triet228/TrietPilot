# openpilot/selfdrive/ui/onroad/nav_banner.py

"""Onroad banner for offline navigation and the posted speed limit.

Drawn at the top centre of the road view by both the comma 3X and comma four HUDs.
Shows the next maneuver with an arrow and distance, the one after it, and the
remaining distance and time. When navigation is idle only the speed limit box is
drawn, and only when speedlimitd has a match.
"""

import pyray as rl

from openpilot.selfdrive.ui.lib.nav_helpers import (nav_payload, speed_limit_payload, maneuver_text, maneuver_arrow,
                                                    format_distance, format_eta, status_text)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BANNER_BG = rl.Color(0, 0, 0, 200)
BANNER_BORDER = rl.Color(255, 255, 255, 60)
TEXT = rl.WHITE
TEXT_DIM = rl.Color(255, 255, 255, 170)
ARROW_COLOR = rl.Color(120, 220, 120, 255)
LIMIT_BG = rl.Color(255, 255, 255, 235)
LIMIT_TEXT = rl.BLACK
LIMIT_BORDER = rl.Color(30, 30, 30, 255)

REFERENCE_WIDTH = 2160.0  # comma 3X screen, everything scales from here


class NavBanner(Widget):
  def __init__(self):
    super().__init__()
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._font_semi_bold = gui_app.font(FontWeight.SEMI_BOLD)
    self._nav = None
    self._limit = None

  def _update_state(self):
    self._nav = nav_payload()
    self._limit = speed_limit_payload()

  def _render(self, rect):
    scale = max(0.5, min(1.0, rect.width / REFERENCE_WIDTH))
    y = rect.y + int(40 * scale)
    if self._nav is not None and self._nav.get("active"):
      y = self._draw_nav(rect, y, scale)
    if self._limit is not None and self._limit.get("valid"):
      self._draw_limit(rect, y, scale)

  def _text_centered(self, font, text, cx, y, size, color):
    w = measure_text_cached(font, text, size).x
    rl.draw_text_ex(font, text, rl.Vector2(cx - w / 2, y), size, 0, color)
    return w

  def _draw_nav(self, rect, y, scale):
    nav = self._nav
    width = int(1000 * scale)
    x = rect.x + (rect.width - width) / 2
    cx = x + width / 2
    pad = int(24 * scale)

    status = status_text(nav)
    if status or "maneuver" not in nav:
      height = int(110 * scale)
      box = rl.Rectangle(x, y, width, height)
      rl.draw_rectangle_rounded(box, 0.3, 10, BANNER_BG)
      rl.draw_rectangle_rounded_lines_ex(box, 0.3, 10, 4, BANNER_BORDER)
      self._text_centered(self._font_semi_bold, status or f"Navigating to {nav.get('dest', '')}", cx, y + pad, int(56 * scale), TEXT)
      return y + height + int(16 * scale)

    height = int(230 * scale)
    box = rl.Rectangle(x, y, width, height)
    rl.draw_rectangle_rounded(box, 0.2, 10, BANNER_BG)
    rl.draw_rectangle_rounded_lines_ex(box, 0.2, 10, 4, BANNER_BORDER)

    # arrow and distance on the first line
    arrow = maneuver_arrow(nav)
    dist = format_distance(nav.get("distance_m", 0.0), ui_state.is_metric)
    arrow_size = int(110 * scale)
    dist_size = int(84 * scale)
    arrow_w = measure_text_cached(self._font_bold, arrow, arrow_size).x
    dist_w = measure_text_cached(self._font_bold, dist, dist_size).x
    line_w = arrow_w + int(30 * scale) + dist_w
    lx = cx - line_w / 2
    rl.draw_text_ex(self._font_bold, arrow, rl.Vector2(lx, y + pad - int(10 * scale)), arrow_size, 0, ARROW_COLOR)
    rl.draw_text_ex(self._font_bold, dist, rl.Vector2(lx + arrow_w + int(30 * scale), y + pad + int(8 * scale)), dist_size, 0, TEXT)

    # maneuver sentence
    self._text_centered(self._font_semi_bold, maneuver_text(nav), cx, y + int(120 * scale), int(50 * scale), TEXT)

    # then: next maneuver, remaining distance and time
    parts = []
    nxt = nav.get("next")
    if nxt:
      parts.append(f"then {maneuver_text({**nxt, 'dest': nav.get('dest', '')})}")
    if "remaining_m" in nav and "eta_s" in nav:
      parts.append(f"{format_distance(nav['remaining_m'], ui_state.is_metric)} · {format_eta(nav['eta_s'])} to {nav.get('dest', '')}")
    if parts:
      self._text_centered(self._font_medium, "   ".join(parts), cx, y + int(178 * scale), int(36 * scale), TEXT_DIM)

    return y + height + int(16 * scale)

  def _draw_limit(self, rect, y, scale):
    limit = self._limit
    width, height = int(150 * scale), int(160 * scale)
    x = rect.x + (rect.width - width) / 2
    box = rl.Rectangle(x, y, width, height)
    rl.draw_rectangle_rounded(box, 0.15, 10, LIMIT_BG)
    rl.draw_rectangle_rounded_lines_ex(box, 0.15, 10, 5, LIMIT_BORDER)
    cx = x + width / 2
    self._text_centered(self._font_semi_bold, "SPEED", cx, y + int(14 * scale), int(26 * scale), LIMIT_TEXT)
    self._text_centered(self._font_semi_bold, "LIMIT", cx, y + int(40 * scale), int(26 * scale), LIMIT_TEXT)
    mph = int(limit.get("limit_mph", 0))
    value = str(int(round(mph * 1.609344))) if ui_state.is_metric else str(mph)
    self._text_centered(self._font_bold, value, cx, y + int(72 * scale), int(74 * scale), LIMIT_TEXT)
