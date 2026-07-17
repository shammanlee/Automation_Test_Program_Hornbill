import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from instrument_discovery import DiscoveryResult
from instrument_discovery_ui import present_discovery_result


class FakeAddressWidget:
    def __init__(self):
        self.items = ["stale"]
        self.current_index = -1

    def clear(self):
        self.items.clear()
        self.current_index = -1

    def addItem(self, value):
        self.items.append(value)

    def setCurrentIndex(self, index):
        self.current_index = index


class FakeOutputWidget:
    def __init__(self):
        self.lines = ["stale"]

    def clear(self):
        self.lines.clear()

    def append(self, value):
        self.lines.append(value)


class InstrumentDiscoveryUiTests(unittest.TestCase):
    def test_present_discovery_populates_widgets_and_selects_roles(self):
        result = DiscoveryResult(
            addresses=["USB0::PSU::INSTR", "USB0::DMM::INSTR"],
            identities=["VENDOR,PSU", "VENDOR,DMM"],
            roles={
                "PSU": "USB0::PSU::INSTR",
                "DMM": "USB0::DMM::INSTR",
            },
        )
        psu_widget = FakeAddressWidget()
        dmm_widget = FakeAddressWidget()
        output_widget = FakeOutputWidget()

        present_discovery_result(
            result,
            address_widgets=(psu_widget, dmm_widget),
            role_widgets={"PSU": psu_widget, "DMM": dmm_widget},
            output_widget=output_widget,
        )

        self.assertEqual(psu_widget.items, result.addresses)
        self.assertEqual(dmm_widget.items, result.addresses)
        self.assertEqual(psu_widget.current_index, 0)
        self.assertEqual(dmm_widget.current_index, 1)
        self.assertEqual(
            output_widget.lines,
            ["VENDOR,PSU  USB0::PSU::INSTR", "VENDOR,DMM  USB0::DMM::INSTR"],
        )

    def test_present_discovery_ignores_role_address_not_in_results(self):
        result = DiscoveryResult(roles={"PSU": "USB0::MISSING::INSTR"})
        psu_widget = FakeAddressWidget()

        present_discovery_result(
            result,
            address_widgets=(psu_widget,),
            role_widgets={"PSU": psu_widget},
        )

        self.assertEqual(psu_widget.items, [])
        self.assertEqual(psu_widget.current_index, -1)


if __name__ == "__main__":
    unittest.main()
