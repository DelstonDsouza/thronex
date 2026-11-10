"""The signals we monitor, and how big a change must be to matter."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    unit: str
    min_scale: float  # floor for "normal spread", so a perfectly steady metric
    #                   doesn't turn tiny wiggles into huge z-scores
    min_delta: float  # smallest absolute change from baseline that matters
    direction: str  # "up" = only increases matter, "both" = either direction


FEATURES = (
    FeatureSpec("request_rate", "req/s", 1.0, 2.0, "both"),
    FeatureSpec("error_rate", "ratio", 0.02, 0.02, "up"),
    FeatureSpec("latency_p95", "s", 0.05, 0.05, "up"),
    FeatureSpec("cpu_cores", "cores", 0.03, 0.05, "up"),
    FeatureSpec("memory_mb", "MB", 5.0, 10.0, "up"),
)
FEATURE_NAMES = tuple(f.name for f in FEATURES)