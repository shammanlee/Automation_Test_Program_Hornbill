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
    get_visa_hostname_resources,
    get_visa_tcpip_resources,
    load_model_role_map,
)


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


class InstrumentDiscoveryTests(unittest.TestCase):
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
            ip_addresses, _, ip_roles = get_visa_tcpip_resources(factory, role_map)
            host_addresses, _, host_roles = get_visa_hostname_resources(
                factory, role_map
            )

        self.assertEqual(ip_addresses, ["TCPIP0::192.0.2.1::inst0::INSTR"])
        self.assertEqual(ip_roles, {"PSU": ip_addresses[0]})
        self.assertEqual(host_addresses, ["TCPIP0::scope-lab::inst0::INSTR"])
        self.assertEqual(host_roles, {"SCOPE": host_addresses[0]})
        self.assertTrue(all(manager.closed for manager in managers))
        self.assertTrue(
            all(
                resource.closed
                for manager in managers
                for resource in manager.resources.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
