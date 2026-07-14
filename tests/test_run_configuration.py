import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from test_configuration import build_test_parameters, snapshot_parameters


class Parameters(dict):
    __getattr__ = dict.get


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.parameters = Parameters({
            "DUT": "Dolphin",
            "savelocation": "output",
            "Voltage_Rating": "20",
            "Current_Rating": "5",
            "Power_Rating": "100",
            "Power": "100",
            "estimatetime": 1,
            "updatedelay": 0,
            "readbackvoltage": True,
            "readbackcurrent": True,
            "noofloop": 1,
            "DMM_Instrument": "Keysight",
            "Programming_Error_Gain": 1,
            "Programming_Error_Offset": 0,
            "Readback_Error_Gain": 1,
            "Readback_Error_Offset": 0,
            "unit": "unit",
            "minCurrent": 0,
            "maxCurrent": 1,
            "current_step_size": 1,
            "minVoltage": 0,
            "maxVoltage": 1,
            "voltage_step_size": 1,
            "selected_text": "Dolphin",
            "PSU": "PSU",
            "DMM": "DMM",
            "ELoad": "ELoad",
            "ELoad_Channel": 1,
            "PSU_Channel": [1],
            "VoltageSense": "2-wire",
            "VoltageRes": 0.1,
            "setFunction": "Voltage",
            "SPOperationMode": "CV",
            "DMM_Model": "DMM",
            "ELoad_Model": "ELoad",
            "Range": "Auto",
            "Aperture": 1,
            "AutoZero": "ON",
            "inputZ": "Auto",
            "UpTime": 0,
            "DownTime": 0,
            "rshunt": 0.1,
            "DMM2": "DMM2",
        })

    def test_builds_base_configuration(self):
        result = build_test_parameters(self.parameters, {})

        self.assertEqual(result["DUT"], "Dolphin")
        self.assertEqual(result["InputZ"], "Auto")
        self.assertNotIn("DMM2", result)

    def test_adds_current_only_fields(self):
        result = build_test_parameters(self.parameters, {"Current_Test": True})

        self.assertEqual(result["DMM2"], "DMM2")
        self.assertEqual(result["rshunt"], 0.1)

    def test_snapshot_is_independent_from_gui_parameters(self):
        self.parameters["PSU_Channel"] = [1]

        snapshot = snapshot_parameters(self.parameters)
        snapshot.PSU_Channel.append(2)

        self.assertEqual(self.parameters.PSU_Channel, [1])
        self.assertEqual(snapshot.PSU_Channel, [1, 2])


if __name__ == "__main__":
    unittest.main()
