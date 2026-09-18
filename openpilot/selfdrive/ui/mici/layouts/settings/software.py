# openpilot/selfdrive/ui/mici/layouts/settings/software.py

import threading

from openpilot.selfdrive.ui.mici.layouts.settings.device.device_layout import EngagedConfirmationButton
from openpilot.selfdrive.ui.mici.widgets.info import InfoLayoutMici
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.self_update import check as update_check, apply as update_apply, UpdateError
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller


class SoftwareInfoLayoutMici(InfoLayoutMici):
  """Show the running fork version, branch, and commit."""

  def __init__(self):
    super().__init__("version", "", "branch", "")

  def _update_state(self):
    params = ui_state.params
    commit = (params.get("GitCommit") or "")[:8]
    super()._update_state()
    self.subtext1.set_text(params.get("Version") or "N/A")
    branch = params.get("GitBranch") or "N/A"
    self.subtext2.set_text(f"{branch} ({commit})" if commit else branch)


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
