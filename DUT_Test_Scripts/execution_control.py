import threading
import time


_thread_state = threading.local()


def set_execution_worker(worker):
    _thread_state.worker = worker


def clear_execution_worker():
    if hasattr(_thread_state, "worker"):
        del _thread_state.worker


def checkpoint():
    worker = getattr(_thread_state, "worker", None)
    if worker is not None:
        worker.checkpoint()


def sleep(seconds):
    worker = getattr(_thread_state, "worker", None)
    if worker is None:
        time.sleep(seconds)
        return

    worker.interruptible_sleep(seconds)
