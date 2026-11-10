"""Thin client for the Prometheus HTTP API."""

import math

import httpx

from app.core.config import settings

_TIMEOUT_SECONDS = 5.0


class PrometheusError(Exception):
    """Prometheus is unreachable or rejected the query."""


def label_value(value: str) -> str:
    """Escapes user-provided text so it is safe inside a PromQL label matcher."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _to_float(raw: object) -> float | None:
    try:
        number = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None  # NaN/Inf become None


def _get(path: str, params: dict) -> list[dict]:
    try:
        response = httpx.get(
            f"{settings.prometheus_url}{path}", params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PrometheusError(str(exc)) from exc
    if body.get("status") != "success":
        raise PrometheusError(body.get("error", "query failed"))
    return body["data"]["result"]


def query_instant(promql: str) -> list[dict]:
    """Returns [{"labels": {...}, "value": float | None}, ...]."""
    result = _get("/api/v1/query", {"query": promql})
    return [
        {"labels": item["metric"], "value": _to_float(item["value"][1])}
        for item in result
    ]


def query_range(promql: str, start: float, end: float, step: int) -> list[dict]:
    """Returns [{"labels": {...}, "points": [[timestamp, float | None], ...]}, ...]."""
    result = _get(
        "/api/v1/query_range",
        {"query": promql, "start": start, "end": end, "step": step},
    )
    return [
        {
            "labels": item["metric"],
            "points": [[ts, _to_float(val)] for ts, val in item["values"]],
        }
        for item in result
    ]