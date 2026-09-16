from openpilot.selfdrive.ui.lib.nav_helpers import nav_payload, place_text, save_place_here, start_navigation, stop_navigation
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller


class GoButton(BigButton):
  """One press routes to a saved place. The value line shows where that place is."""

  def __init__(self, name):
    super().__init__(f"go {name.lower()}", "", scroll=True,
                     description=f"Route to {name} on the offline map. Save {name} first while parked there.")
    self._name = name
    self.set_click_callback(self._go)

  def _update_state(self):
    super()._update_state()
    value = place_text(self._name)
    if self.get_value() != value:
      self.set_value(value)

  def _go(self):
    if not start_navigation(self._name):
      gui_app.push_widget(BigDialog("", tr("{} is not set yet. Park there and press set.").format(self._name)))


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
      StopButton(),
      SetHereButton("Home"),
      SetHereButton("Work"),
    ])
