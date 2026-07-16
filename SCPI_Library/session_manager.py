import threading
import traceback
from dataclasses import dataclass

from SCPI_Library.simulation import create_resource_manager
from SCPI_Library.visa_config import configure_visa_resource, open_visa_resource


_session_state = threading.local()


@dataclass(frozen=True)
class SessionCloseFailure:
    address: str
    exception: Exception
    traceback_text: str

    def to_dict(self):
        details = {
            "address": self.address,
            "type": type(self.exception).__name__,
            "message": str(self.exception),
        }
        if hasattr(self.exception, "to_dict"):
            details["exception"] = self.exception.to_dict()
        return details


class SharedVisaResource:
    def __init__(self, resource):
        object.__setattr__(self, "_resource", resource)

    def __getattr__(self, name):
        return getattr(self._resource, name)

    def __setattr__(self, name, value):
        setattr(self._resource, name, value)

    def close(self):
        return None


class VisaSessionPool:
    def __init__(self, resource_manager_factory=None):
        factory = resource_manager_factory or create_resource_manager
        self.resource_manager = factory()
        self._resources = {}
        self._leases = {}

    def acquire(self, address, timeout_ms=None):
        key = str(address)
        if key not in self._resources:
            resource = open_visa_resource(
                self.resource_manager,
                address,
                timeout_ms,
            )
            self._resources[key] = resource
            self._leases[key] = SharedVisaResource(resource)
        else:
            configure_visa_resource(self._resources[key], timeout_ms)
        return self._leases[key]

    def close(self):
        failures = []
        for address, resource in reversed(tuple(self._resources.items())):
            try:
                resource.close()
            except Exception as exception:
                failures.append(
                    SessionCloseFailure(address, exception, traceback.format_exc())
                )
        try:
            self.resource_manager.close()
        except Exception as exception:
            failures.append(
                SessionCloseFailure(
                    "VISA ResourceManager", exception, traceback.format_exc()
                )
            )
        self._resources.clear()
        self._leases.clear()
        return tuple(failures)


def begin_visa_session_scope(resource_manager_factory=None):
    if getattr(_session_state, "pool", None) is not None:
        raise RuntimeError("A VISA session scope is already active in this thread")
    pool = VisaSessionPool(resource_manager_factory)
    _session_state.pool = pool
    return pool


def close_visa_session_scope():
    pool = getattr(_session_state, "pool", None)
    if pool is None:
        return ()
    try:
        return pool.close()
    finally:
        del _session_state.pool


def get_visa_resource(address, timeout_ms=None):
    pool = getattr(_session_state, "pool", None)
    if pool is not None:
        return pool.acquire(address, timeout_ms)

    resource_manager = create_resource_manager()
    return open_visa_resource(resource_manager, address, timeout_ms)
