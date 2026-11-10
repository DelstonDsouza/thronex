"""Anomaly detection: statistical baseline + operational gate + Isolation Forest."""

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

from app.features import FEATURES

MIN_TRAIN_SAMPLES = 30
MIN_SCALES = np.array([f.min_scale for f in FEATURES])
SEVERITY_ORDER = ["informational", "low", "medium", "high", "critical"]


@dataclass(frozen=True)
class Deviation:
    metric: str
    observed: float
    baseline: float
    z_score: float


@dataclass
class PointResult:
    deviations: list[Deviation]  # signals that passed the statistical + operational gate
    forest_score: float  # Isolation Forest: higher = more unusual, > 0 = outlier
    forest_outlier: bool

    @property
    def is_anomalous(self) -> bool:
        return bool(self.deviations)

    @property
    def max_abs_z(self) -> float:
        return max((abs(d.z_score) for d in self.deviations), default=0.0)


class AnomalyModel:
    def __init__(
        self,
        median: np.ndarray,
        scale: np.ndarray,
        forest: IsolationForest,
        version: str,
        z_threshold: float,
        n_samples: int,
    ) -> None:
        self.median = median
        self.scale = scale
        self.forest = forest
        self.version = version
        self.z_threshold = z_threshold
        self.n_samples = n_samples
        self.trained_at = datetime.now(timezone.utc).isoformat()

    @classmethod
    def train(
        cls,
        X: np.ndarray,
        version: str,
        z_threshold: float = 4.0,
        contamination: float = 0.01,
        seed: int = 42,
    ) -> "AnomalyModel":
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(FEATURES):
            raise ValueError(f"Expected a matrix with {len(FEATURES)} columns")
        if len(X) < MIN_TRAIN_SAMPLES:
            raise ValueError(
                f"Need at least {MIN_TRAIN_SAMPLES} samples to train, got {len(X)}"
            )
        median = np.median(X, axis=0)
        mad = 1.4826 * np.median(np.abs(X - median), axis=0)  # robust std estimate
        scale = np.maximum(mad, MIN_SCALES)
        forest = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=seed
        )
        forest.fit((X - median) / scale)
        return cls(median, scale, forest, version, z_threshold, len(X))

    def score(self, X: np.ndarray) -> list[PointResult]:
        X = np.asarray(X, dtype=float)
        Z = (X - self.median) / self.scale
        forest_raw = -self.forest.decision_function(Z)  # > 0 means outlier
        results: list[PointResult] = []
        for i in range(len(X)):
            deviations = []
            for j, spec in enumerate(FEATURES):
                z = float(Z[i, j])
                delta = float(X[i, j] - self.median[j])
                if spec.direction == "up":
                    hit = z >= self.z_threshold and delta >= spec.min_delta
                else:
                    hit = abs(z) >= self.z_threshold and abs(delta) >= spec.min_delta
                if hit:
                    deviations.append(
                        Deviation(spec.name, float(X[i, j]), float(self.median[j]), z)
                    )
            results.append(
                PointResult(
                    deviations=deviations,
                    forest_score=float(forest_raw[i]),
                    forest_outlier=bool(forest_raw[i] > 0),
                )
            )
        return results


def confirm(results: list[PointResult], min_consecutive: int = 3) -> list[bool]:
    """A point is confirmed once `min_consecutive` anomalous points in a row ended at it."""
    confirmed, run = [], 0
    for r in results:
        run = run + 1 if r.is_anomalous else 0
        confirmed.append(run >= min_consecutive)
    return confirmed


def find_episodes(
    results: list[PointResult], min_consecutive: int = 3
) -> list[tuple[int, int]]:
    """Runs of anomalous points at least `min_consecutive` long, as (start, end) inclusive."""
    episodes, i, n = [], 0, len(results)
    while i < n:
        if results[i].is_anomalous:
            j = i
            while j + 1 < n and results[j + 1].is_anomalous:
                j += 1
            if j - i + 1 >= min_consecutive:
                episodes.append((i, j))
            i = j + 1
        else:
            i += 1
    return episodes


def classify_severity(deviations: list[Deviation]) -> str:
    """Heuristic severity: statistical size, raised by operational thresholds."""
    level = 1  # low
    max_z = max((abs(d.z_score) for d in deviations), default=0.0)
    if max_z >= 40:
        level = 3
    elif max_z >= 15:
        level = 2
    for d in deviations:
        if d.metric == "error_rate":
            if d.observed >= 0.5:
                level = max(level, 4)
            elif d.observed >= 0.05:
                level = max(level, 3)
        elif d.metric == "latency_p95":
            if d.observed >= 2.0:
                level = max(level, 3)
            elif d.observed >= 1.0:
                level = max(level, 2)
    return SEVERITY_ORDER[level]


def explain(result: PointResult) -> str:
    parts = [
        f"{d.metric} is {d.observed:.3g} (baseline {d.baseline:.3g}, z={d.z_score:.1f})"
        for d in sorted(result.deviations, key=lambda d: -abs(d.z_score))
    ]
    forest = (
        "The Isolation Forest also rates this combination of signals as unusual."
        if result.forest_outlier
        else "The Isolation Forest does not rate the combination as an outlier."
    )
    return (
        "Evidence: " + "; ".join(parts) + ". " + forest + " "
        "This is a deviation from the learned baseline, not a confirmed root cause."
    )