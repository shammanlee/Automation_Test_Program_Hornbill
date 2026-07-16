import os

import pyvisa

from SCPI_Library.instrument_errors import (
    InstrumentCommandError,
    InstrumentConnectionError,
    InstrumentTimeoutError,
    build_instrument_context,
)


DEFAULT_VISA_TIMEOUT_MS = 15000


def get_visa_timeout_ms():
    raw_value = os.getenv("VISA_TIMEOUT_MS")
    if raw_value is None:
        return DEFAULT_VISA_TIMEOUT_MS

    try:
        timeout_ms = int(raw_value)
    except ValueError:
        return DEFAULT_VISA_TIMEOUT_MS

    return timeout_ms if timeout_ms > 0 else DEFAULT_VISA_TIMEOUT_MS


def _resource_address(resource):
    return getattr(resource, "resource_name", None) or getattr(
        resource, "resource_info", None
    )


def _is_timeout(exception):
    return getattr(exception, "error_code", None) == pyvisa.constants.StatusCode.error_timeout


class VisaResourceProxy:
    _COMMAND_METHODS = {
        "write",
        "query",
        "read",
        "read_raw",
        "read_bytes",
        "write_raw",
        "query_ascii_values",
        "query_binary_values",
        "read_ascii_values",
        "read_binary_values",
        "write_ascii_values",
        "write_binary_values",
    }

    def __init__(self, resource):
        object.__setattr__(self, "_resource", resource)

    def __getattr__(self, name):
        attribute = getattr(self._resource, name)
        if name not in self._COMMAND_METHODS or not callable(attribute):
            return attribute

        def guarded_command(*args, **kwargs):
            command = args[0] if args else kwargs.get("message")
            try:
                return attribute(*args, **kwargs)
            except pyvisa.VisaIOError as exception:
                context = build_instrument_context(
                    address=_resource_address(self._resource),
                    command=command,
                    operation=name,
                )
                error_type = InstrumentTimeoutError if _is_timeout(exception) else InstrumentCommandError
                raise error_type(**context) from exception

        return guarded_command

    def __setattr__(self, name, value):
        setattr(self._resource, name, value)

    def __enter__(self):
        self._resource.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._resource.__exit__(exc_type, exc_value, traceback)


def configure_visa_resource(resource, timeout_ms=None):
    resource.timeout = timeout_ms or get_visa_timeout_ms()
    if isinstance(resource, VisaResourceProxy):
        return resource
    return VisaResourceProxy(resource)


def open_visa_resource(resource_manager, address, timeout_ms=None, **open_kwargs):
    try:
        resource = resource_manager.open_resource(address, **open_kwargs)
    except pyvisa.VisaIOError as exception:
        context = build_instrument_context(address=address, operation="connect")
        raise InstrumentConnectionError(**context) from exception
    return configure_visa_resource(resource, timeout_ms)
