import pyray as rl

from openpilot.selfdrive.ui.mici.layouts.settings.device import EngagedConfirmationButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import NavScroller


class SoftwareInfoLayoutMici(Widget):
  """Version and branch of the running checkout. Updates happen over SSH, so there is nothing to poll."""

  def __init__(self):
    super().__init__()

    self.set_rect(rl.Rectangle(0, 0, 360, 180))

    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self._version_label = UnifiedLabel("version", 48, max_width=max_width, font_weight=FontWeight.DISPLAY, wrap_text=False)
    self._version_text_label = UnifiedLabel("", 32, max_width=max_width, text_color=subheader_color,
                                            font_weight=FontWeight.ROMAN, wrap_text=False)

    self._branch_label = UnifiedLabel("branch", 48, max_width=max_width, font_weight=FontWeight.DISPLAY, wrap_text=False)
    self._branch_text_label = UnifiedLabel("", 32, max_width=max_width, text_color=subheader_color,
                                           font_weight=FontWeight.ROMAN, wrap_text=False, scroll=True)

  def _update_state(self):
    params = ui_state.params
    commit = (params.get("GitCommit") or "")[:8]
    self._version_text_label.set_text(params.get("Version") or "N/A")
    self._branch_text_label.set_text(f"{params.get('GitBranch') or 'N/A'} ({commit})" if commit else params.get("GitBranch") or "N/A")

  def _render(self, _):
    self._version_label.set_position(self._rect.x + 20, self._rect.y - 10)
    self._version_label.render()

    self._version_text_label.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self._version_text_label.render()

    self._branch_label.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self._branch_label.render()

    self._branch_text_label.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self._branch_text_label.render()


class SoftwareLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    def uninstall_openpilot_callback():
      ui_state.params.put_bool("DoUninstall", True, block=True)

    uninstall_openpilot_btn = EngagedConfirmationButton("uninstall openpilot", "uninstall",
                                                        gui_app.texture("icons_mici/settings/device/uninstall.png", 64, 64),
                                                        uninstall_openpilot_callback, exit_on_confirm=False,
                                                        description="Remove openpilot from this device.",
                                                        description_icon=gui_app.texture("icons_mici/setup/factory_reset.png", 64, 64))

    self._scroller.add_widgets([
      SoftwareInfoLayoutMici(),
      uninstall_openpilot_btn,
    ])
