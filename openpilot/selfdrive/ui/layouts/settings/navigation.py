from openpilot.selfdrive.ui.lib.nav_helpers import (nav_payload, place_text, save_place_here, start_navigation, stop_navigation,
                                                    load_place, navigate_to_address, save_place_from_address)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import button_item, text_item, ListItem
from openpilot.system.ui.widgets.scroller_tici import Scroller


class NavigationLayout(Widget):
  """Offline navigation: one press to route Home or to Work, typed addresses, and saving either place."""

  def __init__(self):
    super().__init__()

    self._keyboard = Keyboard(min_text_size=1, max_text_size=80)
    self._status_item = text_item(lambda: tr("Navigation"), self._status_value)

    self._scroller = Scroller([
      ListItem(lambda: tr("Routing and address lookup are fully offline on the bundled Ann Arbor / Ypsilanti data.")),
      self._status_item,
      button_item(lambda: tr("Go Home"), lambda: tr("GO"), lambda: place_text("Home"), callback=lambda: self._go("Home"),
                  enabled=lambda: load_place("Home") is not None),
      button_item(lambda: tr("Go to Work"), lambda: tr("GO"), lambda: place_text("Work"), callback=lambda: self._go("Work"),
                  enabled=lambda: load_place("Work") is not None),
      button_item(lambda: tr("Go to address"), lambda: tr("TYPE"), lambda: tr("Type a house number and street, or a place name."),
                  callback=self._ask_destination),
      button_item(lambda: tr("Stop Navigation"), lambda: tr("STOP"), callback=stop_navigation),
      button_item(lambda: tr("Set Home to current location"), lambda: tr("SET"), callback=lambda: self._set_here("Home")),
      button_item(lambda: tr("Set Home by address"), lambda: tr("TYPE"), callback=lambda: self._ask_place("Home")),
      button_item(lambda: tr("Set Work to current location"), lambda: tr("SET"), callback=lambda: self._set_here("Work")),
      button_item(lambda: tr("Set Work by address"), lambda: tr("TYPE"), callback=lambda: self._ask_place("Work")),
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
      gui_app.push_widget(alert_dialog(tr("{} is not set yet.").format(name)))

  def _set_here(self, name):
    if save_place_here(name):
      gui_app.push_widget(alert_dialog(tr("{} saved at the current location.").format(name)))
    else:
      gui_app.push_widget(alert_dialog(tr("No GPS fix yet. Try again in a moment.")))

  def _open_keyboard(self, title, on_text):
    def done(result: DialogResult):
      text = self._keyboard.text.strip()
      self._keyboard.clear()
      if result == DialogResult.CONFIRM and text:
        on_text(text)

    self._keyboard.clear()
    self._keyboard.set_title(title, tr("e.g. 1234 Packard St, or a place name"))
    self._keyboard.set_callback(done)
    gui_app.push_widget(self._keyboard)

  def _ask_destination(self):
    def on_text(text):
      hit = navigate_to_address(text)
      if hit is None:
        gui_app.push_widget(alert_dialog(tr("Could not find '{}' in the offline address book.").format(text)))
      elif hit["approx"]:
        gui_app.push_widget(alert_dialog(tr("Closest match: {}. Routing there.").format(hit["label"])))

    self._open_keyboard(tr("Where to?"), on_text)

  def _ask_place(self, name):
    def on_text(text):
      hit = save_place_from_address(name, text)
      if hit is None:
        gui_app.push_widget(alert_dialog(tr("Could not find '{}' in the offline address book.").format(text)))
      else:
        gui_app.push_widget(alert_dialog(tr("{} set to {}.").format(name, hit["label"])))

    self._open_keyboard(tr("Address for {}").format(name), on_text)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)
