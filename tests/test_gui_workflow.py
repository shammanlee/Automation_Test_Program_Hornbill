import json
import sys
import tempfile
import unittest
from io import BytesIO, TextIOWrapper
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from PyQt5.QtWidgets import QApplication, QMessageBox

import GUI
import all_test_dialog
from queue_persistence import QueuePersistence
from run_storage import create_run_storage
from test_run_controller import TestRunRequest


class DummySignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class DummyWorker:
    def __init__(self, checkbox_states=None, configuration=None, parameters=None):
        self.checkbox_states = checkbox_states
        self.configuration = configuration
        self.parameters = parameters
        self.running = False
        self.pause_calls = 0
        self.resume_calls = 0
        self.stop_calls = 0
        self.deleted = False
        for signal_name in (
            "progress",
            "progress_value",
            "finished",
            "aborted",
            "error",
            "warning",
            "new_data",
            "popup_data",
            "state_changed",
        ):
            setattr(self, signal_name, DummySignal())

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def pause(self):
        self.pause_calls += 1

    def resume(self):
        self.resume_calls += 1

    def request_stop(self):
        self.stop_calls += 1

    def deleteLater(self):
        self.deleted = True


class DummyPlotWindow:
    def __init__(self, *_args):
        pass

    def show(self):
        return None

    def popup_plot(self, *args):
        return None


class DummyRunContext:
    def __init__(self, storage, output_root, parameters):
        self.storage = storage
        self.output_root = Path(output_root)
        self.parameters = parameters
        self.data_index = 0
        self.realtime_rows = []
        self.voltage_chart = storage.charts / "Chart.png"
        self.voltage_percentage_chart = storage.charts / "Chart2.png"

    def open_realtime_csv(self, timestamp):
        return self.storage.raw / f"realtime_voltage_data_{timestamp}.csv"

    def close(self):
        return None

    def write_realtime_row(self, values):
        self.data_index += 1
        self.realtime_rows.append(tuple(values))

    def restore_parameter_paths(self):
        self.parameters.savelocation = str(self.output_root)


class GuiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.queue_directory = tempfile.TemporaryDirectory()
        self.queue_file = Path(self.queue_directory.name) / "queue.json"
        self.dialog = GUI.AllTestMeasurement(queue_file=self.queue_file)
        self.dialog.QCheckBox_Image_Widget.setChecked(False)

    def tearDown(self):
        self.dialog.worker = None
        self.dialog.close()
        self.dialog.deleteLater()
        self.application.processEvents()
        self.queue_directory.cleanup()

    def test_console_output_replaces_unsupported_windows_characters(self):
        raw_stream = BytesIO()
        stream = TextIOWrapper(raw_stream, encoding="cp1252")

        GUI.print_console_safe("✅ Measurement complete", stream=stream)
        stream.flush()

        self.assertEqual(
            raw_stream.getvalue().decode("cp1252").strip(),
            "? Measurement complete",
        )

    def test_ui_builders_assemble_expected_sections(self):
        self.assertEqual(self.dialog.layout().count(), 4)
        self.assertIsNotNone(self.dialog.Connection_group.layout())

    def test_ocp_level_updates_parameters_and_output(self):
        self.dialog.OCP_Level_changed("2.5")

        self.assertEqual(self.dialog.params.OCP_Level, "2.5")
        self.assertIn("OCP Level Set to: 2.5", self.dialog.OutputBox.toPlainText())
        self.assertIsNotNone(self.dialog.General_group.layout())
        self.assertIsNotNone(self.dialog.Ratings_Widget.layout())
        self.assertIsNotNone(self.dialog.oscilloscope_settings_widget.layout())
        self.assertIsNotNone(self.dialog.collection_group.layout())
        self.assertIsNotNone(self.dialog.queue_widget.parent())

    def test_realtime_plot_accepts_complete_worker_measurement(self):
        context = DummyRunContext(
            create_run_storage(self.queue_directory.name, "REALTIME"),
            self.queue_directory.name,
            self.dialog.params,
        )
        self.dialog.active_run_context = context

        self.dialog.update_plot(
            5.0,
            1.0,
            5.1,
            5.05,
            1.0,
            0.1,
            0.05,
            2.0,
            1.0,
            0.5,
            -0.5,
            0.5,
            -0.5,
            100.0,
            -100.0,
        )

        self.assertEqual(self.dialog.realtime_plot_series.counter, 1)
        self.assertEqual(len(context.realtime_rows[0]), 15)
        self.assertIn("Pass", self.dialog.OutputBox.toPlainText())

    def test_dut_selection_loads_configuration_into_bound_widgets(self):
        self.dialog.params.savelocation = "preserved-output"

        self.dialog.QComboBox_DUT.setCurrentText("Hornbill")

        self.assertEqual(self.dialog.params.DUT, "Hornbill")
        self.assertEqual(self.dialog.params.savelocation, "preserved-output")
        self.assertEqual(self.dialog.QLineEdit_Programming_Error_Gain.text(), "0.0003")
        self.assertEqual(
            self.dialog.QLineEdit_Programming_Response_Up_NoLoad.text(), "80"
        )
        self.assertEqual(self.dialog.QLineEdit_OVP_Error_Gain.text(), "0.002")
        self.assertEqual(self.dialog.QLineEdit_maxVoltage.text(), "3000")
        self.assertEqual(self.dialog.QComboBox_Probe_Setting.currentText(), "X10")
        self.assertEqual(self.dialog.QComboBox_Voltage_Res.currentText(), "SLOW")
        self.assertEqual(
            self.dialog.QComboBox_set_Function.currentText(), "Voltage Priority"
        )
        self.assertEqual(self.dialog.QComboBox_Voltage_Sense.currentText(), "4 Wire")
        self.assertEqual(self.dialog.QLineEdit_OVP_Level.text(), "")

    def test_measurement_mode_updates_related_controls(self):
        self.dialog.QPushButton_Current_Widget.click()

        self.assertEqual(self.dialog.params.unit, "CURRENT")
        self.assertEqual(
            self.dialog.QComboBox_set_Function.currentText(), "Voltage Priority"
        )
        self.assertFalse(self.dialog.Current_Test_group.isHidden())
        self.assertTrue(self.dialog.Voltage_Test_group.isHidden())
        self.assertFalse(self.dialog.QLineEdit_DMM_VisaAddressforCurrent.isHidden())
        self.assertTrue(self.dialog.QLineEdit_rshunt.isEnabled())

        self.dialog.QPushButton_Voltage_Widget.click()

        self.assertEqual(self.dialog.params.unit, "VOLTAGE")
        self.assertFalse(self.dialog.Voltage_Test_group.isHidden())
        self.assertTrue(self.dialog.Current_Test_group.isHidden())
        self.assertTrue(self.dialog.QLineEdit_DMM_VisaAddressforCurrent.isHidden())
        self.assertFalse(self.dialog.QLineEdit_rshunt.isEnabled())

    def test_oscilloscope_visibility_combines_all_requiring_tests(self):
        scope_checkboxes = (
            self.dialog.QCheckBox_OCP_Test_Widget,
            self.dialog.QCheckBox_TransientRecovery_Widget,
            self.dialog.QCheckBox_ProgrammingSpeed_Widget,
        )
        for checkbox in scope_checkboxes:
            checkbox.setChecked(False)
        self.dialog.InteractiveAction()
        self.assertTrue(self.dialog.oscilloscope_settings_widget.isHidden())

        for checkbox in scope_checkboxes:
            checkbox.setChecked(True)
            self.assertFalse(self.dialog.oscilloscope_settings_widget.isHidden())
            checkbox.setChecked(False)

        self.assertTrue(self.dialog.oscilloscope_settings_widget.isHidden())

    def test_state_controls_follow_worker_state(self):
        self.dialog.set_test_state(GUI.TestState.RUNNING)
        self.assertFalse(self.dialog.QPushButton_Widget1.isEnabled())
        self.assertFalse(self.dialog.pause_button.isHidden())
        self.assertEqual(self.dialog.pause_button.text(), "Pause")

        self.dialog.set_test_state(GUI.TestState.PAUSING)
        self.assertEqual(self.dialog.pause_button.text(), "Pausing...")
        self.assertFalse(self.dialog.pause_button.isEnabled())
        self.assertTrue(self.dialog.abort_button.isEnabled())

        self.dialog.set_test_state(GUI.TestState.PAUSED)
        self.assertEqual(self.dialog.pause_button.text(), "Resume")

        self.dialog.set_test_state(GUI.TestState.COMPLETED)
        self.assertTrue(self.dialog.QPushButton_Widget1.isEnabled())
        self.assertTrue(self.dialog.pause_button.isHidden())

    def test_pause_resume_and_abort_controls_worker(self):
        worker = DummyWorker()
        worker.running = True
        self.dialog.worker = worker

        self.dialog.set_test_state(GUI.TestState.RUNNING)
        self.dialog.toggle_pause_test()
        self.assertEqual(worker.pause_calls, 1)

        self.dialog.set_test_state(GUI.TestState.PAUSED)
        self.dialog.toggle_pause_test()
        self.assertEqual(worker.resume_calls, 1)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.dialog.abort_test()

        self.assertEqual(worker.stop_calls, 1)
        self.assertEqual(self.dialog.test_state, GUI.TestState.STOPPING)
        self.assertEqual(self.dialog.abort_button.text(), "Stopping...")

    def test_discovery_populates_all_instrument_widgets_and_assigns_roles(self):
        result = GUI.DiscoveryResult(
            addresses=["USB0::PSU::INSTR", "USB0::DMM::INSTR"],
            identities=["VENDOR,PSU", "VENDOR,DMM"],
            roles={
                "PSU": "USB0::PSU::INSTR",
                "DMM": "USB0::DMM::INSTR",
            },
        )

        with patch.object(
            all_test_dialog, "ScanSelectedVisaResources", return_value=result
        ):
            self.dialog.QPushButton_Widget4.click()

        widgets = (
            self.dialog.QLineEdit_PSU_VisaAddress,
            self.dialog.QLineEdit_DMM_VisaAddressforVoltage,
            self.dialog.QLineEdit_DMM_VisaAddressforCurrent,
            self.dialog.QLineEdit_OSC_VisaAddress,
            self.dialog.QLineEdit_ELoad_VisaAddress,
        )
        for widget in widgets:
            self.assertEqual(widget.count(), 2)
        self.assertEqual(
            self.dialog.QLineEdit_PSU_VisaAddress.currentText(),
            "USB0::PSU::INSTR",
        )
        self.assertEqual(
            self.dialog.QLineEdit_DMM_VisaAddressforVoltage.currentText(),
            "USB0::DMM::INSTR",
        )

    def test_failure_termination_uses_safe_stop_state(self):
        class TerminateMessageBox:
            Warning = QMessageBox.Warning
            AcceptRole = QMessageBox.AcceptRole
            RejectRole = QMessageBox.RejectRole

            def __init__(self, _parent):
                self.terminate_button = None

            def setIcon(self, _icon):
                return None

            def setWindowTitle(self, _title):
                return None

            def setText(self, _text):
                return None

            def addButton(self, text, _role):
                button = object()
                if text == "Terminate Test":
                    self.terminate_button = button
                return button

            def exec_(self):
                return None

            def clickedButton(self):
                return self.terminate_button

        worker = DummyWorker()
        worker.running = True
        self.dialog.worker = worker
        self.dialog.set_test_state(GUI.TestState.PAUSED)

        with patch.object(all_test_dialog, "QMessageBox", TerminateMessageBox):
            self.dialog.handle_test_failure()

        self.assertTrue(self.dialog.was_aborted)
        self.assertEqual(self.dialog.test_state, GUI.TestState.STOPPING)
        self.assertEqual(worker.stop_calls, 1)

    def test_duplicate_start_is_rejected_before_preflight(self):
        worker = DummyWorker()
        worker.running = True
        self.dialog.worker = worker

        with patch.object(QMessageBox, "warning") as warning, patch.object(
            self.dialog, "pre_test_check"
        ) as preflight:
            self.dialog.executeTest()

        warning.assert_called_once()
        preflight.assert_not_called()
        self.assertIs(self.dialog.worker, worker)

    def test_invalid_configuration_prevents_execution(self):
        with patch.object(QMessageBox, "warning") as warning:
            result = self.dialog.pre_test_check({})

        self.assertFalse(result)
        warning.assert_called_once()
        self.assertIn("Preflight validation failed", self.dialog.OutputBox.toPlainText())

    def test_submission_uses_one_selection_snapshot_for_preflight(self):
        self.dialog.params.DUT = "Dolphin"
        selections = {
            "Voltage_Test": True,
            "VoltageAccuracy": True,
            "DataReport": True,
            "DataImage": False,
        }
        with patch.object(
            all_test_dialog,
            "collect_test_selections",
            return_value=selections,
        ), patch.object(
            self.dialog,
            "pre_test_check",
            return_value=False,
        ) as preflight:
            self.dialog.executeTest()

        preflight.assert_called_once()
        configuration, preflight_selections = preflight.call_args.args
        self.assertEqual(preflight_selections, selections)
        self.assertEqual(configuration["DUT"], self.dialog.params.DUT)
        self.assertTrue(self.dialog.isEnabled())

    def test_confirmed_start_creates_and_starts_worker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = create_run_storage(temporary_directory, "GUI_SIMULATION")

            def prepare_storage(configuration, run_parameters, run_id):
                self.dialog.run_storage = storage
                self.dialog._output_root = temporary_directory
                return DummyRunContext(storage, temporary_directory, run_parameters)

            self.dialog.checkbox_states = {
                "Voltage_Test": True,
                "VoltageAccuracy": True,
                "CurrentStatic(VoltageChange)": True,
                "DataImage": False,
            }
            self.dialog.params.DUT = "Dolphin"
            self.dialog.params.savelocation = temporary_directory
            with patch.object(
                self.dialog, "pre_test_check", return_value=True
            ), patch.object(
                self.dialog, "prepare_run_storage", side_effect=prepare_storage
            ), patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ), patch.object(
                all_test_dialog, "VoltageAccuracyPlotWindow", DummyPlotWindow
            ), patch.object(
                all_test_dialog, "TestWorker", DummyWorker
            ), patch.object(
                all_test_dialog, "show_error_dialog"
            ) as error_dialog:
                self.dialog.executeTest()

            error_dialog.assert_not_called()
            self.assertIsInstance(self.dialog.worker, DummyWorker)
            self.assertTrue(self.dialog.worker.isRunning())
            self.assertEqual(self.dialog.test_state, GUI.TestState.RUNNING)
            self.assertFalse(self.dialog.QPushButton_Widget1.isEnabled())
            self.dialog.worker.running = False
            self.dialog.cleanup_test("test")

    def test_queue_submission_snapshots_parameters_until_started(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = create_run_storage(temporary_directory, "QUEUE_SIMULATION")

            def prepare_storage(configuration, run_parameters, run_id):
                self.dialog.run_storage = storage
                self.dialog._output_root = temporary_directory
                return DummyRunContext(storage, temporary_directory, run_parameters)

            self.dialog.params.DUT = "Dolphin"
            self.dialog.params.savelocation = temporary_directory
            self.dialog.params.noofloop = "1"
            with patch.object(
                self.dialog, "pre_test_check", return_value=True
            ), patch.object(
                self.dialog, "prepare_run_storage", side_effect=prepare_storage
            ), patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ), patch.object(
                all_test_dialog, "VoltageAccuracyPlotWindow", DummyPlotWindow
            ), patch.object(
                all_test_dialog, "TestWorker", DummyWorker
            ):
                self.dialog.executeTest(queue_only=True)
                self.dialog.params.noofloop = "9"

                self.assertEqual(self.dialog.run_controller.pending_count, 1)
                self.assertEqual(self.dialog.queue_widget.table.rowCount(), 1)
                self.assertIsNone(self.dialog.worker)

                request = self.dialog.run_controller.pending_requests[0]
                self.assertEqual(request.parameters.noofloop, "1")
                self.dialog.run_controller.start_queue()

            self.assertIsInstance(self.dialog.worker, DummyWorker)
            self.assertEqual(self.dialog.worker.parameters.noofloop, "1")
            self.dialog.worker.running = False
            self.dialog.cleanup_test("queue-test")

    def test_queue_runs_two_items_with_separate_storage(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage_roots = []

            def prepare_storage(configuration, run_parameters, run_id):
                storage = create_run_storage(
                    temporary_directory,
                    f"QUEUE_{len(storage_roots) + 1}",
                )
                storage_roots.append(storage.root)
                self.dialog.run_storage = storage
                self.dialog._output_root = temporary_directory
                return DummyRunContext(storage, temporary_directory, run_parameters)

            self.dialog.params.DUT = "Dolphin"
            self.dialog.params.savelocation = temporary_directory
            with patch.object(
                self.dialog, "pre_test_check", return_value=True
            ), patch.object(
                self.dialog, "prepare_run_storage", side_effect=prepare_storage
            ), patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ), patch.object(
                all_test_dialog, "VoltageAccuracyPlotWindow", DummyPlotWindow
            ), patch.object(
                all_test_dialog, "TestWorker", DummyWorker
            ):
                self.dialog.params.noofloop = "1"
                self.dialog.executeTest(queue_only=True)
                self.dialog.params.noofloop = "2"
                self.dialog.executeTest(queue_only=True)
                self.dialog.run_controller.start_queue()

                first_worker = self.dialog.worker
                self.assertEqual(first_worker.parameters.noofloop, "1")
                self.dialog.realtime_plot_series.counter = 7
                self.dialog.last_Iset = 1.0
                self.dialog.fail_prompt_active = True
                first_worker.running = False
                first_worker.finished.emit()
                self.application.processEvents()

                self.assertIsNot(self.dialog.worker, first_worker)
                self.assertEqual(self.dialog.worker.parameters.noofloop, "2")
                self.assertEqual(self.dialog.realtime_plot_series.counter, 0)
                self.assertIsNone(self.dialog.last_Iset)
                self.assertFalse(self.dialog.fail_prompt_active)
                self.assertEqual(len(storage_roots), 2)
                self.assertNotEqual(storage_roots[0], storage_roots[1])

            self.dialog.worker.running = False
            self.dialog.cleanup_test("queue-sequence-test")

    def test_pending_queue_restores_in_new_dialog(self):
        self.dialog.run_controller.enqueue(
            {"Voltage_Test": True},
            {"DUT": "Dolphin"},
            GUI.ParameterSnapshot(noofloop="3", savelocation="output"),
            label="Restored voltage test",
            prepare=self.dialog._prepare_queued_run,
            auto_start=False,
        )

        restored_dialog = GUI.AllTestMeasurement(queue_file=self.queue_file)
        try:
            self.assertEqual(restored_dialog.run_controller.pending_count, 1)
            request = restored_dialog.run_controller.pending_requests[0]
            self.assertEqual(request.label, "Restored voltage test")
            self.assertEqual(request.parameters.noofloop, "3")
            self.assertEqual(restored_dialog.queue_widget.table.rowCount(), 1)
        finally:
            restored_dialog.close()
            restored_dialog.deleteLater()
            self.application.processEvents()

    def test_active_run_restores_as_interrupted_and_requires_retry(self):
        active = TestRunRequest(
            {"Voltage_Test": True},
            {"DUT": "Dolphin"},
            GUI.ParameterSnapshot(noofloop="3", savelocation="output"),
            label="Interrupted voltage test",
            run_id="interrupted-run",
            recovery_run_directory="output/previous-run",
        )
        QueuePersistence(self.queue_file).save([], active)

        restored_dialog = GUI.AllTestMeasurement(queue_file=self.queue_file)
        try:
            controller = restored_dialog.run_controller
            self.assertEqual(controller.pending_count, 0)
            self.assertIsNone(controller.active_worker)
            self.assertEqual(
                controller.status_for("interrupted-run"),
                "Interrupted",
            )
            self.assertEqual(restored_dialog.queue_widget.table.rowCount(), 1)
            self.assertEqual(
                restored_dialog.queue_widget.table.item(0, 3).text(),
                "Interrupted",
            )
            self.assertIn(
                "output/previous-run",
                restored_dialog.OutputBox.toPlainText(),
            )
            recovered_snapshot = QueuePersistence(self.queue_file).load_snapshot()
            self.assertIsNone(recovered_snapshot["active"])
            self.assertEqual(
                recovered_snapshot["interrupted"][0]["run_id"],
                "interrupted-run",
            )

            restored_dialog.queue_widget.table.selectRow(0)
            restored_dialog.queue_widget.retry_button.click()

            self.assertEqual(controller.pending_count, 1)
            self.assertEqual(
                controller.status_for("interrupted-run"),
                "Retried",
            )
            self.assertIsNone(controller.active_worker)
            retry_snapshot = QueuePersistence(self.queue_file).load_snapshot()
            self.assertEqual(retry_snapshot["interrupted"], [])
            self.assertEqual(len(retry_snapshot["pending"]), 1)
        finally:
            restored_dialog.close()
            restored_dialog.deleteLater()
            self.application.processEvents()

    def test_queue_template_save_and_load_appends_new_requests(self):
        template_path = Path(self.queue_directory.name) / "template.json"
        self.dialog.run_controller.enqueue(
            {"Voltage_Test": True},
            {"DUT": "Dolphin"},
            GUI.ParameterSnapshot(noofloop="4", savelocation="output"),
            label="Template voltage test",
            prepare=self.dialog._prepare_queued_run,
            auto_start=False,
        )
        with patch.object(
            GUI.QFileDialog,
            "getSaveFileName",
            return_value=(str(template_path), "Queue Template (*.json)"),
        ):
            self.dialog.queue_coordinator.save_template()

        self.dialog.run_controller.clear_pending()
        with patch.object(
            GUI.QFileDialog,
            "getOpenFileName",
            return_value=(str(template_path), "Queue Template (*.json)"),
        ):
            self.dialog.queue_coordinator.load_template()

        self.assertEqual(self.dialog.run_controller.pending_count, 1)
        loaded = self.dialog.run_controller.pending_requests[0]
        self.assertEqual(loaded.label, "Template voltage test")
        self.assertEqual(loaded.parameters.noofloop, "4")

    def test_terminal_handlers_cleanup_worker(self):
        completed_worker = DummyWorker()
        self.dialog.worker = completed_worker
        self.dialog.checkbox_states = {"DataImage": False}
        self.dialog.was_aborted = False
        self.dialog.test_finished()

        self.assertEqual(self.dialog.test_state, GUI.TestState.COMPLETED)
        self.assertTrue(completed_worker.deleted)
        self.assertIsNone(self.dialog.worker)

        aborted_worker = DummyWorker()
        self.dialog.worker = aborted_worker
        self.dialog._cleanup_done = False
        self.dialog.test_aborted()

        self.assertEqual(self.dialog.test_state, GUI.TestState.ABORTED)
        self.assertTrue(aborted_worker.deleted)
        self.assertIsNone(self.dialog.worker)

    def test_failure_writes_structured_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.dialog.run_storage = create_run_storage(
                temporary_directory, "FAILED_SIMULATION"
            )
            with patch.object(
                all_test_dialog, "show_error_dialog"
            ) as error_dialog:
                self.dialog.handle_test_error(
                    RuntimeError("simulated VISA timeout"), "simulated traceback"
                )

            error_dialog.assert_called_once()
            self.assertEqual(self.dialog.test_state, GUI.TestState.FAILED)
            entries = [
                json.loads(line)
                for line in self.dialog.run_storage.diagnostics_file.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line
            ]
            self.assertTrue(any(entry["event"] == "test_failed" for entry in entries))


if __name__ == "__main__":
    unittest.main()
