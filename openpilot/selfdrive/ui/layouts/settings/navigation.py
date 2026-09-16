from openpilot.selfdrive.ui.lib.nav_helpers import (nav_payload, place_text, save_place_here, start_navigation,
                                                    stop_navigation, load_place)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.list_view import button_item, text_item, ListItem
from openpilot.system.ui.widgets.scroller_tici import Scroller


class NavigationLayout(Widget):
  """Offline navigation: one press to route Home or to Work, and save either from the current position."""

  def __init__(self):
    super().__init__()

    self._status_item = text_item(lambda: tr("Navigation"), self._status_value)
    self._home_item = text_item(lambda: tr("Home"), lambda: place_text("Home"))
    self._work_item = text_item(lambda: tr("Work"), lambda: place_text("Work"))

    self._scroller = Scroller([
      ListItem(lambda: tr("Routing is fully offline on the bundled Ann Arbor / Ypsilanti map. Save a place while parked there, then press GO.")),
      self._status_item,
      button_item(lambda: tr("Go Home"), lambda: tr("GO"), callback=lambda: self._go("Home"),
                  enabled=lambda: load_place("Home") is not None),
      button_item(lambda: tr("Go to Work"), lambda: tr("GO"), callback=lambda: self._go("Work"),
                  enabled=lambda: load_place("Work") is not None),
      button_item(lambda: tr("Stop Navigation"), lambda: tr("STOP"), callback=stop_navigation),
      self._home_item,
      button_item(lambda: tr("Set Home to current location"), lambda: tr("SET"), callback=lambda: self._set_here("Home")),
      self._work_item,
      button_item(lambda: tr("Set Work to current location"), lambda: tr("SET"), callback=lambda: self._set_here("Work")),
    ], line_separator=True, spacing=0)

  def _status_value(self):
    nav = nav_payload()
    if nav is None:
      return tr("navd not running")
    if not nav.get("active"):
      return tr("idle")
    status = nav.get("status", "")
    dest = nav.get("dest", "")
    if status == "routing":
      return tr("to {}").format(dest)
    return f"{status.replace('_', ' ')} ({dest})"

  def _go(self, name):
    if not start_navigation(name):
      gui_app.push_widget(alert_dialog(tr("{} is not set yet. Park there and press SET.").format(name)))

  def _set_here(self, name):
    if save_place_here(name):
      gui_app.push_widget(alert_dialog(tr("{} saved at the current location.").format(name)))
    else:
      gui_app.push_widget(alert_dialog(tr("No GPS fix yet. Try again in a moment.")))

  def show_event(self):
    super().show_event()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)
