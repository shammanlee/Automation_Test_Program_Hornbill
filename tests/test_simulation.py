import os
import unittest
from unittest.mock import patch

import GUI
from SCPI_Library.session_manager import (
    begin_visa_session_scope,
    close_visa_session_scope,
    get_visa_resource,
)
from SCPI_Library.simulation import (
    SIMULATED_INSTRUMENTS,
    SimulatedVisaResourceManager,
    create_resource_manager,
    reset_simulation,
    is_simulation_mode,
)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        reset_simulation()

    def tearDown(self):
        close_visa_session_scope()

    def test_simulation_mode_is_explicitly_enabled(self):
        with patch.dict(os.environ, {"AUTOMATION_SIMULATION": "1"}, clear=False):
            self.assertTrue(is_simulation_mode())
            self.assertIsInstance(create_resource_manager(), SimulatedVisaResourceManager)

    def test_simulated_manager_exposes_expected_instrument_roles(self):
        with patch.dict(os.environ, {"AUTOMATION_SIMULATION": "1"}, clear=False):
            addresses, identities, roles = GUI.NewGetVisaSCPIResources()

        self.assertEqual(set(addresses), set(SIMULATED_INSTRUMENTS))
        self.assertEqual(len(identities), len(SIMULATED_INSTRUMENTS))
        self.assertEqual(roles["PSU"], "USB0::SIM::PSU::INSTR")
        self.assertEqual(roles["DMM"], "USB0::SIM::DMM::INSTR")
        self.assertEqual(roles["DMM2"], "USB0::SIM::DMM2::INSTR")
        self.assertEqual(roles["ELOAD"], "USB0::SIM::ELOAD::INSTR")
        self.assertEqual(roles["SCOPE"], "USB0::SIM::SCOPE::INSTR")
        self.assertEqual(roles["ACSource"], "USB0::SIM::ACSOURCE::INSTR")

    def test_session_pool_uses_shared_simulated_measurement_state(self):
        with patch.dict(os.environ, {"AUTOMATION_SIMULATION": "1"}, clear=False):
            begin_visa_session_scope()
            psu = get_visa_resource("USB0::SIM::PSU::INSTR")
            dmm = get_visa_resource("USB0::SIM::DMM::INSTR")

            psu.write("VOLT 12.5, (@1)")
            psu.write("OUTP ON")

            self.assertEqual(float(dmm.query("MEAS:VOLT:DC?")), 12.5)

    def test_simulated_output_off_returns_zero_measurement(self):
        manager = SimulatedVisaResourceManager()
        psu = manager.open_resource("USB0::SIM::PSU::INSTR")
        dmm = manager.open_resource("USB0::SIM::DMM::INSTR")

        psu.write("VOLT 8")
        psu.write("OUTP ON")
        psu.write("OUTP OFF")

        self.assertEqual(float(dmm.query("MEAS:VOLT:DC?")), 0.0)


if __name__ == "__main__":
    unittest.main()
