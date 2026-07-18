import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from instrument_discovery import (
    DiscoveryResult,
    get_all_visa_resources,
    get_visa_hostname_resources,
    get_visa_tcpip_resources,
    load_model_role_map,
    _query_identity,
)
from SCPI_Library.instrument_errors import InstrumentTimeoutError


class DiscoveryResource:
    def __init__(self, identity):
        self.identity = identity
        self.closed = False

    def query(self, _command):
        return self.identity

    def close(self):
        self.closed = True


class DiscoveryManager:
    def __init__(self, identities):
        self.identities = identities
        self.resources = {}
        self.closed = False

    def list_resources(self):
        return tuple(self.identities)

    def open_resource(self, address, **_options):
        resource = DiscoveryResource(self.identities[address])
        self.resources[address] = resource
        return resource

    def close(self):
        self.closed = True


class LegacyGpibResource:
    def __init__(self):
        self.commands = []

    def query(self, command):
        self.commands.append(command)
        raise InstrumentTimeoutError()

    def clear(self):
        self.commands.append("clear")

    def write(self, command):
        self.commands.append(command)

    def read_raw(self):
        return b"HP3458A\r\n"


class InstrumentDiscoveryTests(unittest.TestCase):
    def test_discovery_result_combines_scans(self):
        result = DiscoveryResult(
            addresses=["USB0::MODEL::INSTR"],
            identities=["VENDOR,MODEL-USB,SERIAL,1.0"],
            roles={"PSU": "USB0::MODEL::INSTR"},
        )

        result.extend(
            DiscoveryResult(
                addresses=["TCPIP0::scope-lab::inst0::INSTR"],
                identities=["VENDOR,MODEL-HOST,SERIAL,1.0"],
                roles={"SCOPE": "TCPIP0::scope-lab::inst0::INSTR"},
            )
        )

        self.assertEqual(len(result.addresses), 2)
        self.assertEqual(len(result.identities), 2)
        self.assertEqual(set(result.roles), {"PSU", "SCOPE"})

    def test_load_model_role_map_ignores_comments_and_normalizes_models(self):
        with tempfile.TemporaryDirectory() as directory:
            role_map = Path(directory) / "roles.txt"
            role_map.write_text(
                "# comment\n// comment\nmodel-a: PSU\ninvalid line\n",
                encoding="utf-8",
            )
            roles = load_model_role_map(role_map)

        self.assertEqual(roles, {"MODEL-A": "PSU"})

    def test_tcpip_scans_classify_addresses_and_close_resources(self):
        identities = {
            "TCPIP0::192.0.2.1::inst0::INSTR": "VENDOR,MODEL-IP,SERIAL,1.0",
            "TCPIP0::scope-lab::inst0::INSTR": "VENDOR,MODEL-HOST,SERIAL,1.0",
            "USB0::MODEL::INSTR": "VENDOR,MODEL-USB,SERIAL,1.0",
        }
        managers = []

        def factory():
            manager = DiscoveryManager(identities)
            managers.append(manager)
            return manager

        with tempfile.TemporaryDirectory() as directory:
            role_map = Path(directory) / "roles.txt"
            role_map.write_text(
                "MODEL-IP: PSU\nMODEL-HOST: SCOPE\n",
                encoding="utf-8",
            )
            ip_result = get_visa_tcpip_resources(factory, role_map)
            host_result = get_visa_hostname_resources(factory, role_map)

        self.assertEqual(
            ip_result.addresses, ["TCPIP0::192.0.2.1::inst0::INSTR"]
        )
        self.assertEqual(ip_result.roles, {"PSU": ip_result.addresses[0]})
        self.assertEqual(
            host_result.addresses, ["TCPIP0::scope-lab::inst0::INSTR"]
        )
        self.assertEqual(host_result.roles, {"SCOPE": host_result.addresses[0]})
        self.assertTrue(all(manager.closed for manager in managers))
        self.assertTrue(
            all(
                resource.closed
                for manager in managers
                for resource in manager.resources.values()
            )
        )

    def test_serial_specific_role_overrides_generic_duplicate_model(self):
        identities = {
            "USB0::OTHER::INSTR": "KEYSIGHT,E36731A,MY62100065,1.0",
            "USB0::ELOAD::INSTR": "KEYSIGHT,E36731A,MY62100043,1.0",
        }
        with tempfile.TemporaryDirectory() as directory:
            role_map = Path(directory) / "roles.txt"
            role_map.write_text(
                "E36731A: ELOAD\nMY62100043: ELOAD\n",
                encoding="utf-8",
            )
            result = get_all_visa_resources(
                lambda: DiscoveryManager(identities),
                role_map,
            )

        self.assertEqual(result.roles["ELOAD"], "USB0::ELOAD::INSTR")

    def test_gpib_identity_uses_legacy_fallback_after_guarded_timeout(self):
        resource = LegacyGpibResource()

        identity = _query_identity(
            resource,
            "GPIB0::22::INSTR",
            gpib_fallback=True,
        )

        self.assertEqual(identity, "HP3458A")
        self.assertEqual(resource.commands, ["*IDN?", "clear", "ID?"])


if __name__ == "__main__":
    unittest.main()
