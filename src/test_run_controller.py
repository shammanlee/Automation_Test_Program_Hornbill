"""Lifecycle and queue orchestration for background test workers."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import traceback
from uuid import uuid4

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from test_worker import TestWorker


@dataclass
class TestRunRequest:
    checkbox_states: dict
    configuration: dict
    parameters: object
    label: str = "Test Run"
    prepare: object = None
    run_id: str = ""

    def __post_init__(self):
        if not self.run_id:
            self.run_id = uuid4().hex


class TestRunController(QObject):
    worker_created = pyqtSignal(object)
    queue_changed = pyqtSignal(int)
    queue_finished = pyqtSignal()
    request_queued = pyqtSignal(object)
    request_started = pyqtSignal(object)
    request_status_changed = pyqtSignal(object, str)
    request_setup_failed = pyqtSignal(object, object, str)

    def __init__(self, worker_factory=TestWorker, parent=None):
        super().__init__(parent)
        self._worker_factory = worker_factory
        self._queue = deque()
        self._requests_by_id = {}
        self._statuses_by_id = {}
        self.active_worker = None
        self.active_request = None

    @property
    def pending_count(self):
        return len(self._queue)

    @property
    def pending_requests(self):
        return tuple(self._queue)

    @property
    def is_running(self):
        return bool(self.active_worker and self.active_worker.isRunning())

    def start(self, checkbox_states, configuration, parameters, **request_options):
        if self.active_worker or self._queue:
            raise RuntimeError("A test run is already active")
        return self.enqueue(
            checkbox_states,
            configuration,
            parameters,
            auto_start=True,
            **request_options,
        )

    def enqueue(
        self,
        checkbox_states,
        configuration,
        parameters,
        *,
        label="Test Run",
        prepare=None,
        auto_start=True,
        run_id="",
    ):
        request = TestRunRequest(
            dict(checkbox_states),
            dict(configuration),
            parameters,
            label=label,
            prepare=prepare,
            run_id=run_id,
        )
        self._queue.append(request)
        self._requests_by_id[request.run_id] = request
        self.queue_changed.emit(len(self._queue))
        self.request_queued.emit(request)
        self._set_status(request, "Pending")
        if auto_start:
            self.start_queue()
        return request

    def start_queue(self):
        self._start_next()

    def remove_pending(self, run_id):
        requests = list(self._queue)
        for index, request in enumerate(requests):
            if request.run_id == run_id:
                requests.pop(index)
                self._queue = deque(requests)
                self.queue_changed.emit(len(self._queue))
                self._set_status(request, "Removed")
                return True
        return False

    def move_pending(self, run_id, offset):
        requests = list(self._queue)
        index = next(
            (i for i, request in enumerate(requests) if request.run_id == run_id),
            None,
        )
        if index is None:
            return False
        target = index + offset
        if target < 0 or target >= len(requests):
            return False
        requests[index], requests[target] = requests[target], requests[index]
        self._queue = deque(requests)
        self.queue_changed.emit(len(self._queue))
        return True

    def clear_pending(self):
        removed = tuple(self._queue)
        self._queue.clear()
        self.queue_changed.emit(0)
        for request in removed:
            self._set_status(request, "Removed")

    def request_for(self, run_id):
        return self._requests_by_id.get(run_id)

    def status_for(self, run_id):
        return self._statuses_by_id.get(run_id)

    def duplicate(self, run_id, auto_start=False):
        source = self.request_for(run_id)
        if source is None:
            return None
        return self.enqueue(
            deepcopy(source.checkbox_states),
            deepcopy(source.configuration),
            deepcopy(source.parameters),
            label=f"{source.label} (Copy)",
            prepare=source.prepare,
            auto_start=auto_start,
        )

    def retry(self, run_id, auto_start=False):
        if self.status_for(run_id) not in {"Failed", "Aborted"}:
            return None
        source = self.request_for(run_id)
        if source is None:
            return None
        return self.enqueue(
            deepcopy(source.checkbox_states),
            deepcopy(source.configuration),
            deepcopy(source.parameters),
            label=f"{source.label} (Retry)",
            prepare=source.prepare,
            auto_start=auto_start,
        )

    def pause(self):
        if self.is_running:
            self.active_worker.pause()

    def resume(self):
        if self.is_running:
            self.active_worker.resume()

    def request_stop(self, clear_pending=True):
        if clear_pending:
            self.clear_pending()
        if self.is_running:
            self.active_worker.request_stop()

    def _start_next(self):
        if self.active_worker is not None:
            return
        if not self._queue:
            self.queue_finished.emit()
            return

        request = self._queue.popleft()
        self.queue_changed.emit(len(self._queue))
        self.active_request = request
        try:
            if request.prepare:
                request.prepare(request)
        except Exception as exception:
            traceback_text = traceback.format_exc()
            self._set_status(request, "Failed")
            self.request_setup_failed.emit(request, exception, traceback_text)
            self.active_request = None
            QTimer.singleShot(0, self._start_next)
            return
        worker = self._worker_factory(
            request.checkbox_states,
            request.configuration,
            request.parameters,
        )
        self.active_worker = worker
        worker.finished.connect(lambda: self._worker_ended(request, "Completed"))
        worker.aborted.connect(lambda: self._worker_ended(request, "Aborted"))
        worker.error.connect(
            lambda *_: self._worker_ended(request, "Failed")
        )
        self.request_started.emit(request)
        self._set_status(request, "Running")
        self.worker_created.emit(worker)
        worker.start()

    def _worker_ended(self, request, status):
        if request is not self.active_request:
            return
        self._set_status(request, status)
        self.active_worker = None
        self.active_request = None
        QTimer.singleShot(0, self._start_next)

    def _set_status(self, request, status):
        self._statuses_by_id[request.run_id] = status
        self.request_status_changed.emit(request, status)
