import re
import threading


_diagnostic_state = threading.local()


class AutomationError(Exception):
    default_message = "Automation operation failed"

    def __init__(self, message=None, **context):
        super().__init__(message or self.default_message)
        self.context = {key: value for key, value in context.items() if value is not None}

    def to_dict(self):
        details = {
            "type": type(self).__name__,
            "message": str(self),
            "context": self.context,
        }
        cause = self.__cause__
        if cause is not None:
            if hasattr(cause, "to_dict"):
                details["cause"] = cause.to_dict()
            else:
                details["cause"] = {
                    "type": type(cause).__name__,
                    "message": str(cause),
                }
        return details


class TestExecutionError(AutomationError):
    default_message = "Test execution failed"


class InstrumentConnectionError(AutomationError):
    default_message = "Unable to connect to instrument"


class InstrumentCommandError(AutomationError):
    default_message = "Instrument command failed"


class InstrumentTimeoutError(InstrumentCommandError):
    default_message = "Instrument command timed out"


class MeasurementError(TestExecutionError):
    default_message = "Measurement processing failed"


class ReportGenerationError(TestExecutionError):
    default_message = "Report generation failed"


class CleanupError(AutomationError):
    default_message = "Cleanup operation failed"


def set_diagnostic_context(**context):
    _diagnostic_state.context = {
        key: value for key, value in context.items() if value is not None
    }


def clear_diagnostic_context():
    if hasattr(_diagnostic_state, "context"):
        del _diagnostic_state.context


def get_diagnostic_context():
    return dict(getattr(_diagnostic_state, "context", {}))


def build_instrument_context(address=None, command=None, operation=None, **context):
    details = get_diagnostic_context()
    details.update({key: value for key, value in context.items() if value is not None})
    if address is not None:
        details["address"] = str(address)
        instrument_roles = details.pop("instrument_roles", {})
        role = instrument_roles.get(str(address))
        if role:
            details["role"] = role
    if command is not None:
        command_text = str(command)
        details["command"] = command_text
        channel_match = re.search(
            r"(?:@\(?\s*|CHAN(?:NEL)?\s*)(\d+)",
            command_text,
            re.IGNORECASE,
        )
        if channel_match:
            details.setdefault("channel", channel_match.group(1))
    if operation is not None:
        details["operation"] = operation
    return details


def normalize_execution_error(exception, traceback_text, **context):
    if isinstance(exception, AutomationError):
        exception.context.update(
            {key: value for key, value in context.items() if value is not None}
        )
        return exception

    traceback_lower = traceback_text.lower()
    if "xlreport" in traceback_lower or "openpyxl" in traceback_lower:
        error_type = ReportGenerationError
    elif isinstance(exception, (TypeError, ValueError)) and "dut_test_scripts" in traceback_lower:
        error_type = MeasurementError
    else:
        error_type = TestExecutionError

    return error_type(
        f"{error_type.default_message}: {exception}",
        original_type=type(exception).__name__,
        **context,
    )
