#!/usr/bin/env python3
import os
import time

from openpilot.cereal import messaging
from openpilot.common.hardware import COMMA_HARDWARE
from openpilot.common.realtime import Priority, config_realtime_process, set_core_affinity
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.main import MainLayout
from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.screen_recorder import ScreenRecorder

BIG_UI = gui_app.big_ui()


def make_screen_recorder():
  """TrietPilot: record the screen into the current segment when RecordScreen is set."""
  from openpilot.common.params import Params
  from openpilot.common.hardware.hw import Paths
  params = Params()
  if not params.get_bool("RecordScreen"):
    return None

  def current_route():
    return params.get("CurrentRoute") if params.get_bool("IsOnroad") else None
  return ScreenRecorder(Paths.log_root(), current_route, gui_app.width, gui_app.height)


def main():
  cores = {5, }
  # above plannerd and radard
  config_realtime_process(0, Priority.CTRL_HIGH)

  screen_recorder = make_screen_recorder()
  if screen_recorder is not None:
    gui_app.set_screen_recorder(screen_recorder)
  gui_app.init_window("UI")
  if screen_recorder is not None and not screen_recorder.start():
    gui_app.set_screen_recorder(None)
  if BIG_UI:
    MainLayout()
  else:
    MiciMainLayout()

  pm = messaging.PubMaster(['uiDebug'])
  for should_render, frame_time, cpu_time in gui_app.render():
    extra_start = time.monotonic()
    ui_state.update()

    if should_render:
      # reaffine after power save offlines our core
      if COMMA_HARDWARE and os.sched_getaffinity(0) != cores:
        try:
          set_core_affinity(list(cores))
        except OSError:
          pass

      extra_cpu = time.monotonic() - extra_start
      msg = messaging.new_message('uiDebug')
      msg.uiDebug.cpuTimeMillis = (cpu_time + extra_cpu) * 1000
      msg.uiDebug.frameTimeMillis = frame_time * 1000
      pm.send('uiDebug', msg)


if __name__ == "__main__":
  main()
