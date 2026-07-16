"""VISA instrument discovery and model-to-role assignment."""

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

import pyvisa

from output_logging import print_console_safe
from SCPI_Library.simulation import create_resource_manager
from SCPI_Library.visa_config import configure_visa_resource


IGNORED_VISA_ERROR_CODES = {-1073807343, -1073807339, -1073807298}
DEFAULT_ROLE_MAP = (
    Path(__file__).resolve().parent.parent
    / "Instrument_Config_Files"
    / "instrument_role.txt"
)


@dataclass
class DiscoveryResult:
    addresses: list[str] = field(default_factory=list)
    identities: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)

    def extend(self, other: "DiscoveryResult") -> None:
        self.addresses.extend(other.addresses)
        self.identities.extend(other.identities)
        self.roles.update(other.roles)


def load_model_role_map(path=None):
    role_map_path = Path(path) if path else DEFAULT_ROLE_MAP
    model_roles = {}
    try:
        for line in role_map_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            model, role = (value.strip() for value in line.split(":", 1))
            model_roles[model.upper()] = role
    except OSError as exception:
        print_console_safe(f"Error reading {role_map_path}: {exception}")
    return model_roles


def get_visa_scpi_resources(resource_manager_factory=None, role_map_path=None):
    return _discover_resources(
        resource_manager_factory,
        role_map_path,
        prefixes=("USB", "GPIB"),
        timeout_ms=5000,
        gpib_fallback=True,
    )


def get_all_visa_resources(resource_manager_factory=None, role_map_path=None):
    return _discover_resources(
        resource_manager_factory,
        role_map_path,
        timeout_ms=2000,
        serial_access=True,
    )


def get_visa_tcpip_resources(resource_manager_factory=None, role_map_path=None):
    return _discover_resources(
        resource_manager_factory,
        role_map_path,
        prefixes=("TCPIP",),
        timeout_ms=10000,
        address_kind="ip",
        require_comma=True,
    )


def get_visa_hostname_resources(resource_manager_factory=None, role_map_path=None):
    return _discover_resources(
        resource_manager_factory,
        role_map_path,
        prefixes=("TCPIP",),
        timeout_ms=10000,
        address_kind="hostname",
        require_comma=True,
    )


def _discover_resources(
    resource_manager_factory,
    role_map_path,
    *,
    prefixes=None,
    timeout_ms=15000,
    address_kind=None,
    gpib_fallback=False,
    serial_access=False,
    require_comma=False,
):
    factory = resource_manager_factory or create_resource_manager
    manager = factory()
    result = DiscoveryResult()
    model_roles = load_model_role_map(role_map_path)
    try:
        for address in manager.list_resources():
            if prefixes and not str(address).startswith(prefixes):
                continue
            if not _matches_address_kind(address, address_kind):
                continue
            instrument = None
            try:
                open_options = {}
                if serial_access and str(address).startswith("ASRL"):
                    open_options = {"timeout": timeout_ms, "access_mode": 1}
                instrument = configure_visa_resource(
                    manager.open_resource(address, **open_options),
                    timeout_ms,
                )
                identity = _query_identity(
                    instrument,
                    address,
                    gpib_fallback=gpib_fallback,
                )
                if not identity or (require_comma and "," not in identity):
                    continue
                result.addresses.append(address)
                result.identities.append(identity)
                _assign_role(result.roles, model_roles, identity, address)
            except pyvisa.errors.VisaIOError as exception:
                if exception.error_code not in IGNORED_VISA_ERROR_CODES:
                    print_console_safe(f"VISA error on {address}: {exception}")
            except Exception as exception:
                print_console_safe(f"Unexpected error on {address}: {exception}")
            finally:
                if instrument is not None:
                    try:
                        instrument.close()
                    except Exception:
                        pass
    finally:
        try:
            manager.close()
        except Exception:
            pass
    return result


def _query_identity(instrument, address, *, gpib_fallback):
    try:
        return instrument.query("*IDN?").strip().upper()
    except pyvisa.errors.VisaIOError:
        if not gpib_fallback or not str(address).startswith("GPIB"):
            raise
        instrument.clear()
        instrument.write("ID?")
        return instrument.read_raw().decode(errors="ignore").strip().upper()


def _matches_address_kind(address, address_kind):
    if address_kind is None:
        return True
    parts = str(address).split("::")
    if len(parts) < 2:
        return False
    try:
        ipaddress.ip_address(parts[1])
        actual_kind = "ip"
    except ValueError:
        actual_kind = "hostname"
    return actual_kind == address_kind


def _assign_role(roles, model_roles, identity, address):
    for model, role in model_roles.items():
        if model in identity:
            roles[role] = address
            return
