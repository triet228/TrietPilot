from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import button_item, text_item, ListItem
from openpilot.system.ui.widgets.scroller_tici import Scroller


class SoftwareLayout(Widget):
  """Version information only. TrietPilot has no over-the-air updater; the checkout is managed over SSH."""

  def __init__(self):
    super().__init__()

    params = ui_state.params
    self._scroller = Scroller([
      ListItem(lambda: tr("Software is updated by hand over SSH. There is no over-the-air updater.")),
      text_item(lambda: tr("Version"), params.get("Version") or "N/A"),
      text_item(lambda: tr("Branch"), params.get("GitBranch") or "N/A"),
      text_item(lambda: tr("Commit"), (params.get("GitCommit") or "N/A")[:12]),
      text_item(lambda: tr("Remote"), params.get("GitRemote") or "N/A"),
      button_item(lambda: tr("Uninstall"), lambda: tr("UNINSTALL"), callback=self._on_uninstall),
    ], line_separator=True, spacing=0)

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
