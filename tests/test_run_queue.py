import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from test_run_controller import TestRunController


class DummySignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class DummyWorker:
    def __init__(self, checkbox_states, configuration, parameters):
        self.checkbox_states = checkbox_states
        self.configuration = configuration
        self.parameters = parameters
        self.finished = DummySignal()
        self.aborted = DummySignal()
        self.error = DummySignal()
        self.running = False
        self.pause_calls = 0
        self.resume_calls = 0
        self.stop_calls = 0

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


class TestRunQueueTests(unittest.TestCase):
    def setUp(self):
        self.workers = []

        def factory(*args):
            worker = DummyWorker(*args)
            self.workers.append(worker)
            return worker

        self.controller = TestRunController(worker_factory=factory)

    def test_start_creates_worker(self):
        self.controller.start({"Voltage_Test": True}, {"DUT": "Dolphin"}, {})

        self.assertEqual(len(self.workers), 1)
        self.assertTrue(self.controller.is_running)

    def test_start_rejects_duplicate_run(self):
        self.controller.start({}, {}, {})

        with self.assertRaises(RuntimeError):
            self.controller.start({}, {}, {})

    def test_queue_runs_requests_in_order(self):
        self.controller.start({"name": "first"}, {}, {})
        self.controller.enqueue({"name": "second"}, {}, {})

        self.assertEqual(self.controller.pending_count, 1)
        self.workers[0].running = False
        self.workers[0].finished.emit()
        self.controller._start_next()

        self.assertEqual(len(self.workers), 2)
        self.assertEqual(self.workers[1].checkbox_states["name"], "second")

    def test_pause_resume_and_stop_delegate_to_worker(self):
        self.controller.start({}, {}, {})
        worker = self.workers[0]

        self.controller.pause()
        self.controller.resume()
        self.controller.request_stop()

        self.assertEqual(worker.pause_calls, 1)
        self.assertEqual(worker.resume_calls, 1)
        self.assertEqual(worker.stop_calls, 1)

    def test_stop_clears_pending_requests(self):
        self.controller.start({}, {}, {})
        self.controller.enqueue({}, {"sequence": 2}, {})

        self.controller.request_stop()

        self.assertEqual(self.controller.pending_count, 0)

    def test_pending_requests_can_be_reordered_and_removed(self):
        first = self.controller.enqueue({}, {"sequence": 1}, {}, auto_start=False)
        second = self.controller.enqueue({}, {"sequence": 2}, {}, auto_start=False)
        third = self.controller.enqueue({}, {"sequence": 3}, {}, auto_start=False)

        self.assertTrue(self.controller.move_pending(third.run_id, -1))
        self.assertEqual(
            [request.configuration["sequence"] for request in self.controller.pending_requests],
            [1, 3, 2],
        )
        self.assertTrue(self.controller.remove_pending(first.run_id))
        self.assertEqual(self.controller.pending_count, 2)

    def test_duplicate_creates_an_independent_pending_snapshot(self):
        source = self.controller.enqueue(
            {"Voltage_Test": True},
            {"DUT": "Dolphin", "limits": {"maximum": 5}},
            {"noofloop": "1"},
            label="Voltage accuracy",
            auto_start=False,
        )

        duplicate = self.controller.duplicate(source.run_id)
        source.configuration["limits"]["maximum"] = 10

        self.assertIsNotNone(duplicate)
        self.assertNotEqual(duplicate.run_id, source.run_id)
        self.assertEqual(duplicate.label, "Voltage accuracy (Copy)")
        self.assertEqual(duplicate.configuration["limits"]["maximum"], 5)
        self.assertEqual(self.controller.pending_count, 2)

    def test_retry_accepts_only_failed_or_aborted_history(self):
        request = self.controller.start(
            {"Voltage_Test": True},
            {"DUT": "Dolphin"},
            {"noofloop": "1"},
            label="Failed voltage accuracy",
        )
        worker = self.workers[0]
        worker.running = False
        worker.error.emit(RuntimeError("failed"), "traceback")

        retry = self.controller.retry(request.run_id)

        self.assertIsNotNone(retry)
        self.assertEqual(retry.label, "Failed voltage accuracy (Retry)")
        self.assertEqual(self.controller.status_for(request.run_id), "Failed")
        self.assertIsNone(self.controller.retry(retry.run_id))

    def test_terminal_history_prunes_old_requests_at_configured_limit(self):
        workers = []

        def factory(*args):
            worker = DummyWorker(*args)
            workers.append(worker)
            return worker

        controller = TestRunController(worker_factory=factory, history_limit=2)
        pruned = []
        controller.request_history_pruned.connect(pruned.append)
        requests = []
        for sequence in range(3):
            request = controller.start({}, {"sequence": sequence}, {})
            requests.append(request)
            workers[-1].running = False
            workers[-1].finished.emit()

        self.assertEqual(controller.history_count, 2)
        self.assertEqual(pruned, [requests[0].run_id])
        self.assertIsNone(controller.request_for(requests[0].run_id))
        self.assertEqual(
            controller.status_for(requests[-1].run_id),
            "Completed",
        )

    def test_prepare_and_status_events_follow_each_request(self):
        prepared = []
        statuses = []
        self.controller.request_status_changed.connect(
            lambda request, status: statuses.append((request.label, status))
        )
        self.controller.enqueue(
            {}, {}, {}, label="first", prepare=lambda request: prepared.append(request.label),
            auto_start=False,
        )
        self.controller.enqueue(
            {}, {}, {}, label="second", prepare=lambda request: prepared.append(request.label),
            auto_start=False,
        )

        self.controller.start_queue()
        self.workers[0].running = False
        self.workers[0].finished.emit()
        self.controller._start_next()

        self.assertEqual(prepared, ["first", "second"])
        self.assertIn(("first", "Completed"), statuses)
        self.assertIn(("second", "Running"), statuses)

    def test_setup_failure_marks_request_failed_without_worker(self):
        statuses = []
        failures = []
        self.controller.request_status_changed.connect(
            lambda request, status: statuses.append(status)
        )
        self.controller.request_setup_failed.connect(
            lambda request, exception, trace: failures.append(exception)
        )
        self.controller.enqueue(
            {}, {}, {}, prepare=lambda request: (_ for _ in ()).throw(
                RuntimeError("setup failed")
            ), auto_start=False,
        )

        self.controller.start_queue()

        self.assertIn("Failed", statuses)
        self.assertEqual(len(failures), 1)
        self.assertEqual(self.workers, [])
        self.assertIsNone(self.controller.active_request)


if __name__ == "__main__":
    unittest.main()
