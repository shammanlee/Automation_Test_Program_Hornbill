import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from queue_persistence import QueuePersistence, QueuePersistenceError
from test_configuration import ParameterSnapshot
from test_run_controller import TestRunRequest


class QueuePersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_pending_request(self):
        with tempfile.TemporaryDirectory() as directory:
            persistence = QueuePersistence(Path(directory) / "queue.json")
            request = TestRunRequest(
                {"Voltage_Test": True},
                {"DUT": "Dolphin"},
                ParameterSnapshot(noofloop="2"),
                label="Dolphin voltage",
                run_id="run-1",
            )

            persistence.save([request])
            restored = persistence.load()

        self.assertEqual(restored[0]["run_id"], "run-1")
        self.assertEqual(restored[0]["parameters"]["noofloop"], "2")

    def test_save_replaces_previous_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            persistence = QueuePersistence(path)
            persistence.save([])
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["pending"], [])

    def test_invalid_json_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            path.write_text("not-json", encoding="utf-8")

            with self.assertRaises(QueuePersistenceError):
                QueuePersistence(path).load()


if __name__ == "__main__":
    unittest.main()
