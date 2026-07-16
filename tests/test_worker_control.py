import unittest
from unittest.mock import patch

import GUI
import test_worker
from DUT_Test_Scripts.instrument_shutdown import ShutdownResult
from SCPI_Library.instrument_errors import TestExecutionError as ExecutionFailure
from test_worker import TestCancelled, TestState, TestWorker


class Parameters(dict):
    __getattr__ = dict.get


def create_worker():
    return TestWorker(
        {},
        {},
        Parameters(DUT="Unknown", noofloop=1),
    )


class WorkerControlTests(unittest.TestCase):
    def test_gui_reexports_worker_types(self):
        self.assertIs(GUI.TestWorker, TestWorker)
        self.assertIs(GUI.TestState, TestState)
        self.assertIs(GUI.TestCancelled, TestCancelled)

    def test_dut_dispatch_selects_dolphin_runner(self):
        worker = create_worker()
        worker.params["DUT"] = "Dolphin"

        with patch.object(worker, "_run_dolphin_tests") as dolphin, patch.object(
            worker, "_run_hornbill_tests"
        ) as hornbill:
            worker._dispatch_dut_tests(2)

        dolphin.assert_called_once_with(2)
        hornbill.assert_not_called()

    def test_dut_dispatch_selects_hornbill_runner(self):
        worker = create_worker()
        worker.params["DUT"] = "Hornbill"

        with patch.object(worker, "_run_dolphin_tests") as dolphin, patch.object(
            worker, "_run_hornbill_tests"
        ) as hornbill:
            worker._dispatch_dut_tests(3)

        hornbill.assert_called_once_with(3)
        dolphin.assert_not_called()

    def test_unknown_dut_does_not_run_a_dut_handler(self):
        worker = create_worker()

        with patch.object(worker, "_run_dolphin_tests") as dolphin, patch.object(
            worker, "_run_hornbill_tests"
        ) as hornbill:
            worker._dispatch_dut_tests(0)

        dolphin.assert_not_called()
        hornbill.assert_not_called()

    def test_dolphin_mode_dispatch_selects_voltage_handler(self):
        worker = create_worker()
        worker.checkbox_states = {"Voltage_Test": True, "Current_Test": False}

        with patch.object(worker, "_run_dolphin_voltage_tests") as voltage, patch.object(
            worker, "_run_dolphin_current_tests"
        ) as current:
            worker._run_dolphin_tests(4)

        voltage.assert_called_once_with(4)
        current.assert_not_called()

    def test_hornbill_mode_dispatch_selects_current_handler(self):
        worker = create_worker()
        worker.checkbox_states = {"Voltage_Test": False, "Current_Test": True}

        with patch.object(worker, "_run_hornbill_voltage_tests") as voltage, patch.object(
            worker, "_run_hornbill_current_tests"
        ) as current:
            worker._run_hornbill_tests(5)

        current.assert_called_once_with(5)
        voltage.assert_not_called()

    def test_pause_resume_and_stop_checkpoint(self):
        worker = create_worker()
        worker.state = TestState.RUNNING

        worker.pause()
        self.assertTrue(worker.is_paused)
        self.assertEqual(worker.state, TestState.PAUSED)

        worker.resume()
        self.assertFalse(worker.is_paused)
        self.assertEqual(worker.state, TestState.RUNNING)

        worker.request_stop()
        self.assertEqual(worker.state, TestState.STOPPING)
        with self.assertRaises(TestCancelled):
            worker.checkpoint()

    def test_success_closes_sessions_before_hardware_shutdown(self):
        worker = create_worker()
        events = []
        terminal_signals = []
        worker.finished.connect(lambda: terminal_signals.append("finished"))
        worker.aborted.connect(lambda: terminal_signals.append("aborted"))
        worker.error.connect(lambda *_: terminal_signals.append("error"))

        with patch.object(
            test_worker, "begin_visa_session_scope", lambda: events.append("begin")
        ), patch.object(
            test_worker, "close_visa_session_scope", lambda: events.append("close") or ()
        ), patch.object(
            test_worker,
            "shutdown_instruments",
            lambda config: events.append("shutdown") or ShutdownResult((), ()),
        ):
            worker.run()

        self.assertEqual(events, ["begin", "close", "shutdown"])
        self.assertEqual(terminal_signals, ["finished"])
        self.assertEqual(worker.state, TestState.COMPLETED)

    def test_stop_emits_only_aborted_terminal_signal(self):
        worker = create_worker()
        terminal_signals = []
        worker.finished.connect(lambda: terminal_signals.append("finished"))
        worker.aborted.connect(lambda: terminal_signals.append("aborted"))
        worker.error.connect(lambda *_: terminal_signals.append("error"))
        worker.request_stop()

        with patch.object(test_worker, "begin_visa_session_scope", lambda: None), patch.object(
            test_worker, "close_visa_session_scope", lambda: ()
        ), patch.object(
            test_worker, "shutdown_instruments", lambda config: ShutdownResult((), ())
        ):
            worker.run()

        self.assertEqual(terminal_signals, ["aborted"])
        self.assertEqual(worker.state, TestState.ABORTED)

    def test_startup_failure_emits_contextual_error_and_still_shuts_down(self):
        worker = create_worker()
        events = []
        errors = []
        worker.error.connect(lambda error, trace: errors.append(error))

        def fail_startup():
            events.append("begin")
            raise RuntimeError("VISA startup failed")

        with patch.object(test_worker, "begin_visa_session_scope", fail_startup), patch.object(
            test_worker, "close_visa_session_scope", lambda: events.append("close") or ()
        ), patch.object(
            test_worker,
            "shutdown_instruments",
            lambda config: events.append("shutdown") or ShutdownResult((), ()),
        ):
            worker.run()

        self.assertEqual(events, ["begin", "close", "shutdown"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ExecutionFailure)
        self.assertEqual(worker.state, TestState.FAILED)


if __name__ == "__main__":
    unittest.main()
