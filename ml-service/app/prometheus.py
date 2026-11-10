"""Pulls the 5 signals for one service from Prometheus as a matrix."""

import math

import httpx
import numpy as np

from app.config import PROMETHEUS_URL
from app.features import FEATURES


class PrometheusError(Exception):
    """Prometheus is unreachable or rejected a query."""


class NoDataError(Exception):
    """Prometheus has no data at all for this service and time window."""


def label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


_RATE = "rate(http_requests_total{__SEL__}[1m])"
QUERIES = {
    "request_rate": f"sum({_RATE})",
    "error_rate": f'sum(rate(http_requests_total{{__SEL__,status=~"5.."}}[1m])) / sum({_RATE})',
    "latency_p95": "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{__SEL__}[1m])))",
    "cpu_cores": "sum(rate(process_cpu_seconds_total{__SEL__}[1m]))",
    "memory_mb": "sum(process_resident_memory_bytes{__SEL__}) / 1048576",
}


def _query_range(promql: str, start: float, end: float, step: int) -> list[dict]:
    try:
        response = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PrometheusError(str(exc)) from exc
    if body.get("status") != "success":
        raise PrometheusError(body.get("error", "query failed"))
    return body["data"]["result"]


def fetch_matrix(
    service: str, environment: str, start: float, end: float, step: int
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (timestamps, X) where X has one row per timestamp, one column per feature.

    Missing values become 0 (for example, latency when there was no traffic).
    `environment` is the Prometheus label value, such as "staging".
    """
    selector = f'service="{label_value(service)}",environment="{label_value(environment)}"'
    n = int((end - start) // step) + 1
    timestamps = start + step * np.arange(n)
    X = np.zeros((n, len(FEATURES)))
    seen = False
    for j, spec in enumerate(FEATURES):
        result = _query_range(QUERIES[spec.name].replace("__SEL__", selector), start, end, step)
        if not result:
            continue
        for ts, raw in result[0]["values"]:
            try:
                value = float(raw)
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            idx = int(round((float(ts) - start) / step))
            if 0 <= idx < n:
                X[idx, j] = value
                seen = True
    if not seen:
        raise NoDataError(f"No data for service '{service}' in environment '{environment}'")
    return timestamps, X