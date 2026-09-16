import threading

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.self_update import check as update_check, apply as update_apply, UpdateError
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import button_item, text_item, ListItem
from openpilot.system.ui.widgets.scroller_tici import Scroller


class SoftwareLayout(Widget):
  """Version info plus a self-updater that only talks to this repo's GitHub remote."""

  def __init__(self):
    super().__init__()

    params = ui_state.params
    self._busy = False
    self._status = tr("Connect to Wi-Fi, then press CHECK.")
    self._update_available = False

    self._check_btn = button_item(lambda: tr("Check GitHub for updates"), lambda: tr("CHECK"), lambda: self._status,
                                  callback=self._on_check, enabled=lambda: not self._busy and ui_state.is_offroad())
    self._apply_btn = button_item(lambda: tr("Update and reboot"), lambda: tr("UPDATE"),
                                  lambda: tr("Resets this checkout to the latest commit on GitHub, then reboots to rebuild. Local edits are discarded."),
                                  callback=self._on_apply, enabled=lambda: not self._busy and ui_state.is_offroad())
    self._apply_btn.set_visible(lambda: self._update_available)

    self._scroller = Scroller([
      ListItem(lambda: tr("Updates come only from this repo on GitHub. Nothing talks to comma's servers. The car must be off.")),
      self._check_btn,
      self._apply_btn,
      text_item(lambda: tr("Version"), params.get("Version") or "N/A"),
      text_item(lambda: tr("Branch"), params.get("GitBranch") or "N/A"),
      text_item(lambda: tr("Commit"), (params.get("GitCommit") or "N/A")[:12]),
      text_item(lambda: tr("Remote"), params.get("GitRemote") or "N/A"),
      button_item(lambda: tr("Uninstall"), lambda: tr("UNINSTALL"), callback=self._on_uninstall),
    ], line_separator=True, spacing=0)

  def _run(self, fn):
    self._busy = True

    def worker():
      try:
        fn()
      except UpdateError as e:
        self._status = tr("Failed: {}").format(str(e).splitlines()[-1] if str(e) else "git error")
      finally:
        self._busy = False

    threading.Thread(target=worker, daemon=True).start()

  def _on_check(self):
    self._status = tr("Checking GitHub...")

    def do():
      info = update_check()
      self._update_available = info["behind"] > 0
      self._status = f"{info['branch']}: {info['local']} -> {info['remote']}, {info['summary']}"

    self._run(do)

  def _on_apply(self):
    def handle(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._status = tr("Updating, the device will reboot...")
        self._run(update_apply)

    gui_app.push_widget(ConfirmDialog(tr("Update to the latest GitHub commit and reboot?"), tr("Update"), callback=handle))

  def show_event(self):
    super().show_event()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)

  def _on_uninstall(self):
    def handle_uninstall_confirmation(result: DialogResult):
      if result == DialogResult.CONFIRM:
        ui_state.params.put_bool("DoUninstall", True, block=True)

    dialog = ConfirmDialog(tr("Are you sure you want to uninstall?"), tr("Uninstall"), callback=handle_uninstall_confirmation)
    gui_app.push_widget(dialog)
