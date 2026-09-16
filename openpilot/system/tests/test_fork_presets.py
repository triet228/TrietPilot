# openpilot/system/tests/test_fork_presets.py

from openpilot.common.test import OpenpilotTestCase
import openpilot.system.fork_presets as fp


class FakeParams:
  def __init__(self):
    self.bools = {}
    self.values = {}

  def put_bool(self, key, value):
    self.bools[key] = value

  def put(self, key, value):
    self.values[key] = value


class TestForkPresets(OpenpilotTestCase):
  def test_table_covers_every_fork_param(self):
    for key in ("SpeedLimitCruise", "AutoExperimentalMode", "NudgelessLaneChange", "NavTurnSlowdown"):
      assert fp.PRESETS[key] is True
    assert "ExperimentalMode" not in fp.PRESETS  # managed by speedlimitd

  def test_apply_writes_by_type(self):
    p = FakeParams()
    written = fp.apply_presets(p, presets={"A": True, "B": False, "LongitudinalPersonality": 2}, places={})
    assert p.bools == {"A": True, "B": False}
    assert p.values == {"LongitudinalPersonality": 2}
    assert written == ["A", "B", "LongitudinalPersonality"]

  def test_places_by_address_and_by_coordinates(self):
    calls = []

    def resolve(text):
      calls.append(text)
      return {"lat": 42.28, "lon": -83.74, "label": "1234 Packard St"} if "Packard" in text else None

    p = FakeParams()
    places = {"NavHome": "1234 Packard St", "NavWork": {"lat": 42.29, "lon": -83.71}, "NavGym": "nowhere", "NavSkip": None}
    written = fp.apply_presets(p, presets={}, places=places, resolve=resolve)
    assert p.values["NavHome"] == {"lat": 42.28, "lon": -83.74, "name": "Home"}
    assert p.values["NavWork"] == {"lat": 42.29, "lon": -83.71, "name": "Work"}
    assert "NavGym" not in p.values and "NavSkip" not in p.values
    assert calls == ["1234 Packard St", "nowhere"]
    assert written == ["NavHome", "NavWork"]

  def test_defaults_leave_places_alone(self):
    p = FakeParams()
    fp.apply_presets(p, places=fp.PLACES, resolve=lambda t: None)
    assert not any(k.startswith("Nav") for k in p.values)
