import threading
import pyray as rl

from openpilot.selfdrive.ui.mici.layouts.settings.device import EngagedConfirmationButton
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.self_update import check as update_check, apply as update_apply, UpdateError
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import NavScroller


class SoftwareInfoLayoutMici(Widget):
  """Version and branch of the running checkout."""

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


class GitHubUpdateButton(BigButton):
  """First press fetches from GitHub and shows what is new; second press applies it and reboots."""

  def __init__(self):
    description = ("Connect to Wi-Fi first. Only this repo's GitHub remote is contacted, never comma's servers. "
                   + "Applying resets the checkout to the latest commit and reboots to rebuild.")
    super().__init__("update from github", "", gui_app.texture("icons_mici/settings/device/update.png", 64, 75),
                     description=description)
    self._busy = False
    self._update_available = False
    self.set_enabled(lambda: not self._busy and ui_state.is_offroad())

  def _run(self, fn):
    self._busy = True
    self.set_rotate_icon(True)

    def worker():
      try:
        fn()
      except UpdateError as e:
        self.set_value("failed: " + (str(e).splitlines()[-1] if str(e) else "git error")[:40])
      finally:
        self._busy = False
        self.set_rotate_icon(False)

    threading.Thread(target=worker, daemon=True).start()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._busy:
      return
    if self._update_available:
      self.set_value("updating, rebooting soon")
      self._run(update_apply)
      return

    self.set_value("checking github...")

    def do():
      info = update_check()
      self._update_available = info["behind"] > 0
      if self._update_available:
        self.set_value(f"{info['summary']}, press to install")
      else:
        self.set_value(f"up to date ({info['local']})")
        if info["dirty"]:
          gui_app.push_widget(BigDialog("", tr("Local edits on the device would be discarded by an update.")))

    self._run(do)


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
      GitHubUpdateButton(),
      uninstall_openpilot_btn,
    ])
