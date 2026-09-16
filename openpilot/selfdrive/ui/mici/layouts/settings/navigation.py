from openpilot.selfdrive.ui.lib.nav_helpers import (nav_payload, place_text, save_place_here, start_navigation, stop_navigation,
                                                    navigate_to_address, save_place_from_address)
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigInputDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

HINT = "1234 Packard St, or a place name..."


class GoButton(BigButton):
  """One press routes to a saved place. The value line shows where that place is."""

  def __init__(self, name):
    super().__init__(f"go {name.lower()}", "", scroll=True,
                     description=f"Route to {name} on the offline map. Save {name} first, from here or by address.")
    self._name = name
    self.set_click_callback(self._go)

  def _update_state(self):
    super()._update_state()
    value = place_text(self._name)
    if self.get_value() != value:
      self.set_value(value)

  def _go(self):
    if not start_navigation(self._name):
      gui_app.push_widget(BigDialog("", tr("{} is not set yet.").format(self._name)))


class GoToAddressButton(BigButton):
  def __init__(self):
    super().__init__("go to address", "", description="Type a house number and street, or a place name. Lookup is offline.")
    self.set_click_callback(self._ask)

  def _ask(self):
    def on_text(text):
      hit = navigate_to_address(text)
      if hit is None:
        gui_app.push_widget(BigDialog("", tr("Could not find '{}' in the offline address book.").format(text)))
      elif hit["approx"]:
        gui_app.push_widget(BigDialog("", tr("Closest match: {}. Routing there.").format(hit["label"])))

    gui_app.push_widget(BigInputDialog(HINT, confirm_callback=on_text))


class SetHereButton(BigButton):
  def __init__(self, name):
    super().__init__(f"set {name.lower()} here", "", description=f"Save the current GPS position as {name}.")
    self._name = name
    self.set_click_callback(self._set)

  def _set(self):
    if save_place_here(self._name):
      gui_app.push_widget(BigDialog("", tr("{} saved at the current location.").format(self._name)))
    else:
      gui_app.push_widget(BigDialog("", tr("No GPS fix yet. Try again in a moment.")))


class SetByAddressButton(BigButton):
  def __init__(self, name):
    super().__init__(f"set {name.lower()} by address", "", description=f"Type the address to save as {name}.")
    self._name = name
    self.set_click_callback(self._ask)

  def _ask(self):
    def on_text(text):
      hit = save_place_from_address(self._name, text)
      if hit is None:
        gui_app.push_widget(BigDialog("", tr("Could not find '{}' in the offline address book.").format(text)))
      else:
        gui_app.push_widget(BigDialog("", tr("{} set to {}.").format(self._name, hit["label"])))

    gui_app.push_widget(BigInputDialog(HINT, confirm_callback=on_text))


class StopButton(BigButton):
  def __init__(self):
    super().__init__("stop navigation", "", description="Clear the current destination.")
    self.set_click_callback(stop_navigation)

  def _update_state(self):
    super()._update_state()
    nav = nav_payload()
    if nav is None:
      value = "navd not running"
    elif not nav.get("active"):
      value = "idle"
    elif nav.get("status") == "routing":
      value = f"to {nav.get('dest', '')}"
    else:
      value = nav.get("status", "").replace("_", " ")
    if self.get_value() != value:
      self.set_value(value)


class NavigationLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._scroller.add_widgets([
      GoButton("Home"),
      GoButton("Work"),
      GoToAddressButton(),
      StopButton(),
      SetHereButton("Home"),
      SetByAddressButton("Home"),
      SetHereButton("Work"),
      SetByAddressButton("Work"),
    ])
