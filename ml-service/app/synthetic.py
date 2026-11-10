"""SYNTHETIC telemetry generator. Used only by tests, never by the real pipeline."""

import numpy as np

from app.features import FEATURES


def normal_telemetry(n: int, seed: int) -> np.ndarray:
    """Healthy-service data: ~10 req/s, ~0.3% errors, ~120 ms P95, ~0.05 cores, ~60 MB."""
    rng = np.random.default_rng(seed)
    X = np.column_stack(
        [
            rng.normal(10.0, 0.8, n),
            np.clip(np.abs(rng.normal(0.003, 0.003, n)), 0, 0.02),
            np.clip(rng.normal(0.12, 0.01, n), 0.05, None),
            np.clip(rng.normal(0.05, 0.005, n), 0, None),
            rng.normal(60.0, 1.0, n),
        ]
    )
    assert X.shape[1] == len(FEATURES)
    return X


def inject_scenario(X: np.ndarray, start: int, end: int, scenario: str) -> np.ndarray:
    """Returns a copy of X with an abnormal period in rows [start, end)."""
    X = X.copy()
    s = slice(start, end)
    if scenario == "latency_spike":
        X[s, 2] = 2.5
    elif scenario == "error_spike":
        X[s, 1] = 0.35
        X[s, 2] *= 3
    elif scenario == "cpu_spike":
        X[s, 3] = 0.9
        X[s, 2] *= 2
    elif scenario == "traffic_drop":
        X[s, 0] = 0.2
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return X