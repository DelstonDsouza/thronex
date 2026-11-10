"""Saves trained models to disk. Only ever loads files this service wrote itself."""

import threading
from pathlib import Path

import joblib

from app.detectors import AnomalyModel


class ModelStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._models: dict[tuple[str, str], AnomalyModel] = {}
        self._lock = threading.Lock()
        for path in self.directory.glob("*.joblib"):
            try:
                payload = joblib.load(path)
                self._models[(payload["environment"], payload["service"])] = payload["model"]
            except Exception:
                continue  # skip unreadable files

    def _path(self, environment: str, service: str) -> Path:
        # Names are validated upstream to [A-Za-z0-9_.-], so no path traversal.
        return self.directory / f"{environment}__{service}.joblib"

    def save(self, environment: str, service: str, model: AnomalyModel) -> None:
        with self._lock:
            joblib.dump(
                {"environment": environment, "service": service, "model": model},
                self._path(environment, service),
            )
            self._models[(environment, service)] = model

    def get(self, environment: str, service: str) -> AnomalyModel | None:
        return self._models.get((environment, service))

    def all(self) -> list[tuple[str, str, AnomalyModel]]:
        return [(e, s, m) for (e, s), m in self._models.items()]