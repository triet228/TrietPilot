# scripts/test_fork.py

"""Runs the fork's pure-Python tests on a dev machine without the native openpilot stack.

The real test suite needs capnp, msgq, acados and Linux xattrs, none of which exist on a
laptop that has not built openpilot. Everything TrietPilot adds is written so its logic
can be exercised with those modules stubbed out, which is what this does. Use it after
every upstream merge and before every push:

  python3 scripts/test_fork.py            run the fork's tests
  python3 scripts/test_fork.py -k curve   pass extra pytest arguments through

Tests that genuinely need the device (deleter xattrs, manager) are not in this list and
run in openpilot's own CI style on the device.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORK_TESTS = [
  "openpilot/selfdrive/controls/tests/test_longcontrol.py",
  "openpilot/selfdrive/controls/tests/test_longitudinal_planner.py",
  "openpilot/selfdrive/controls/tests/test_stop_profile.py",
  "openpilot/selfdrive/controls/tests/test_auto_lane_change.py",
  "openpilot/selfdrive/navd/tests/test_speedlimit.py",
  "openpilot/selfdrive/navd/tests/test_router.py",
  "openpilot/selfdrive/navd/tests/test_curve_speed.py",
  "openpilot/selfdrive/navd/tests/test_limit_ahead.py",
  "openpilot/selfdrive/navd/tests/test_geocoder.py",
  "openpilot/system/tests/test_self_update.py",
  "openpilot/selfdrive/car/tests/test_fork_tuning.py",
]


def stub(name, **attrs):
  m = types.ModuleType(name)
  for k, v in attrs.items():
    setattr(m, k, v)
  sys.modules[name] = m
  return m


def install_stubs():
  class LongControlState:
    off = "off"
    pid = "pid"
    stopping = "stopping"

  car = MagicMock()
  car.CarControl.Actuators.LongControlState = LongControlState
  stub("opendbc")
  stub("opendbc.car")
  stub("opendbc.car.structs", car=car)
  stub("opendbc.car.interfaces", ACCEL_MIN=-3.5, ACCEL_MAX=2.0)
  stub("setproctitle", getproctitle=lambda: "x", setproctitle=lambda *a: None)
  stub("openpilot.common.hardware", PC=True, COMMA_HARDWARE=False, HARDWARE=MagicMock())
  stub("openpilot.common.swaglog", cloudlog=MagicMock())
  stub("openpilot.cereal", log=MagicMock(), messaging=MagicMock())
  stub("openpilot.cereal.log")
  stub("openpilot.cereal.messaging")
  stub("acados")
  stub("acados.acados_template", AcadosModel=MagicMock(), AcadosOcp=MagicMock(), AcadosOcpSolver=MagicMock())
  stub("openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.c_generated_code")
  stub("openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.c_generated_code.acados_ocp_solver_pyx", AcadosOcpSolverCython=MagicMock())
  stub("casadi", SX=MagicMock(), vertcat=MagicMock())
  stub("openpilot.selfdrive.controls.radard", _LEAD_ACCEL_TAU=1.5)
  stub("openpilot.common.params", Params=MagicMock())
  stub("openpilot.common.basedir", BASEDIR=ROOT)
  stub("openpilot.common.prefix", OpenpilotPrefix=MagicMock())
  stub("openpilot.system.manager.manager")

  class OpenpilotTestCase:
    pass
  stub("openpilot.common.test", OpenpilotTestCase=OpenpilotTestCase)


def main():
  os.chdir(ROOT)
  sys.path.insert(0, ROOT)
  install_stubs()
  sys.exit(pytest.main(["-q", *FORK_TESTS, *sys.argv[1:]]))


if __name__ == "__main__":
  main()
