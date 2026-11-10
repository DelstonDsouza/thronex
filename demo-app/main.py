"""THRONEX demo microservice.

One codebase, three roles (gateway, order, payment), chosen with the ROLE env var.
DEMO ONLY: the /admin/fault endpoint is unauthenticated and exists to simulate
failures. Never expose it outside your local machine.
"""

import asyncio
import os
import random
import time

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

ROLE = os.getenv("ROLE", "payment")  # gateway | order | payment
DOWNSTREAM_URL = os.getenv("DOWNSTREAM_URL", "")
DOWNSTREAM_NAME = os.getenv("DOWNSTREAM_NAME", "")

# ---------- Metrics ----------
# Labels like service/environment are added by Prometheus at scrape time.
# We only label by method, route template and status, which keeps cardinality low.
REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "route", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
IN_PROGRESS = Gauge("http_requests_in_progress", "Requests currently being handled")
DOWNSTREAM_REQUESTS = Counter(
    "downstream_requests_total",
    "Calls made to a downstream service",
    ["target", "status"],
)
DOWNSTREAM_LATENCY = Histogram(
    "downstream_request_duration_seconds",
    "Latency of calls to a downstream service",
    ["target"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ---------- Fault injection (demo only) ----------
class FaultConfig(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=10_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)


fault = FaultConfig()


async def apply_fault() -> None:
    if fault.latency_ms:
        await asyncio.sleep(fault.latency_ms / 1000)
    if fault.error_rate and random.random() < fault.error_rate:
        raise HTTPException(status_code=500, detail="injected fault")


app = FastAPI(title=f"demo-{ROLE}")
http_client = httpx.AsyncClient(timeout=5.0)


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    IN_PROGRESS.inc()
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = route.path if route else "unmatched"  # never raw URLs
        REQUESTS.labels(request.method, route_path, str(status_code)).inc()
        LATENCY.labels(request.method, route_path).observe(elapsed)
        IN_PROGRESS.dec()


async def call_downstream(path: str) -> dict:
    start = time.perf_counter()
    status = "error"
    try:
        response = await http_client.get(f"{DOWNSTREAM_URL}{path}")
        status = str(response.status_code)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError:
        raise HTTPException(502, f"{DOWNSTREAM_NAME} returned an error")
    except httpx.HTTPError:
        raise HTTPException(503, f"{DOWNSTREAM_NAME} is unavailable")
    finally:
        DOWNSTREAM_REQUESTS.labels(DOWNSTREAM_NAME, status).inc()
        DOWNSTREAM_LATENCY.labels(DOWNSTREAM_NAME).observe(time.perf_counter() - start)


# ---------- System endpoints ----------
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "role": ROLE}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/fault", response_model=FaultConfig)
def get_fault() -> FaultConfig:
    return fault


@app.put("/admin/fault", response_model=FaultConfig)
def set_fault(config: FaultConfig) -> FaultConfig:
    global fault
    fault = config
    return fault


# ---------- Business endpoints (depend on ROLE) ----------
if ROLE == "gateway":

    @app.get("/api/orders", dependencies=[Depends(apply_fault)])
    async def list_orders() -> dict:
        return await call_downstream("/orders")


elif ROLE == "order":

    @app.get("/orders", dependencies=[Depends(apply_fault)])
    async def orders() -> dict:
        await asyncio.sleep(random.uniform(0.01, 0.04))  # simulated work
        payment = await call_downstream("/pay")
        return {"orders": [{"id": 1, "item": "keyboard"}], "payment": payment}


else:

    @app.get("/pay", dependencies=[Depends(apply_fault)])
    async def pay() -> dict:
        await asyncio.sleep(random.uniform(0.02, 0.08))  # simulated work
        return {"status": "paid", "transaction_id": random.randint(100000, 999999)}