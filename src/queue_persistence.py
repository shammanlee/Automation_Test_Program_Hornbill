"""Versioned, atomic persistence for pending test-run requests."""

import json
from pathlib import Path


SCHEMA_VERSION = 1


class QueuePersistenceError(RuntimeError):
    pass


class QueuePersistence:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, requests):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "pending": [self._serialize(request) for request in requests],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exception:
            raise QueuePersistenceError(
                f"Unable to save test queue: {exception}"
            ) from exception

    def load(self):
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exception:
            raise QueuePersistenceError(
                f"Unable to load test queue: {exception}"
            ) from exception
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise QueuePersistenceError(
                f"Unsupported test queue schema: {payload.get('schema_version')}"
            )
        pending = payload.get("pending")
        if not isinstance(pending, list):
            raise QueuePersistenceError("Test queue pending data must be a list")
        return pending

    @staticmethod
    def _serialize(request):
        parameters = request.parameters
        if not isinstance(parameters, dict):
            parameters = vars(parameters)
        return {
            "run_id": request.run_id,
            "label": request.label,
            "checkbox_states": dict(request.checkbox_states),
            "configuration": dict(request.configuration),
            "parameters": dict(parameters),
        }
