import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import measurement_report_exporter
from test_worker import TestWorker


class Parameters(dict):
    __getattr__ = dict.get


def create_worker(params=None):
    return TestWorker({}, {}, params or Parameters(noofloop=1))


class MeasurementReportExporterTests(unittest.TestCase):
    def test_config_csv_uses_active_run_storage(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_directory = Path(temporary_directory)
            worker = create_worker()
            worker.dict = {"PSU": "SIM::PSU", "Voltage": 5.0}
            worker.run_context = SimpleNamespace(
                storage=SimpleNamespace(raw=raw_directory)
            )

            worker.report_exporter.write_config_csv("config.csv")

            config_frame = pd.read_csv(raw_directory / "config.csv", index_col=0)

        self.assertEqual(config_frame.loc["PSU", "Value"], "SIM::PSU")
        self.assertEqual(float(config_frame.loc["Voltage", "Value"]), 5.0)

    def test_voltage_report_uses_simulation_prefix(self):
        worker = create_worker(
            Parameters(
                noofloop=1,
                unit="VOLTAGE",
                savelocation="reports",
            )
        )
        report_instances = []

        class Report:
            def __init__(self, save_directory, file_name):
                self.save_directory = save_directory
                self.file_name = file_name
                self.was_run = False
                report_instances.append(self)

            def run(self):
                self.was_run = True

        with patch.object(
            measurement_report_exporter,
            "is_simulation_mode",
            return_value=True,
        ), patch.object(measurement_report_exporter, "xlreport", Report):
            worker.report_exporter.save_voltage_report()

        self.assertEqual(len(report_instances), 1)
        self.assertEqual(report_instances[0].save_directory, "reports")
        self.assertEqual(report_instances[0].file_name, "SIMULATED_VOLTAGE")
        self.assertTrue(report_instances[0].was_run)

    def test_executor_exports_delegate_to_shared_exporter(self):
        worker = create_worker()
        measurement = (["info"], ["measured"], ["readback"])

        with patch.object(
            worker.report_exporter,
            "export_voltage_accuracy",
        ) as voltage_export, patch.object(
            worker.report_exporter,
            "export_current_accuracy",
        ) as current_export, patch.object(
            worker.report_exporter,
            "export_power_accuracy",
        ) as power_export:
            worker._export_voltage_accuracy(*measurement)
            worker._export_current_accuracy(*measurement)
            worker._export_power_accuracy(*measurement)

        voltage_export.assert_called_once_with(*measurement)
        current_export.assert_called_once_with(*measurement)
        power_export.assert_called_once_with(*measurement)


if __name__ == "__main__":
    unittest.main()
