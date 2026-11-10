import time
import uuid
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app import prometheus as prom
from app.config import MODEL_DIR
from app.detectors import AnomalyModel, classify_severity, explain, find_episodes
from app.features import FEATURE_NAMES
from app.store import ModelStore

NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
MIN_TRAIN_REQUEST_RATE = 1.0  # refuse to learn "normal" from an idle service

app = FastAPI(title="THRONEX ML Service", version="0.1.0")
store = ModelStore(MODEL_DIR)


class TrainRequest(BaseModel):
    service: str = Field(pattern=NAME_PATTERN, max_length=100)
    environment: str = Field(pattern=NAME_PATTERN, max_length=50)
    minutes: int = Field(default=15, ge=5, le=240)
    step_seconds: int = Field(default=15, ge=5, le=300)


class DetectRequest(BaseModel):
    service: str = Field(pattern=NAME_PATTERN, max_length=100)
    environment: str = Field(pattern=NAME_PATTERN, max_length=50)
    application: str | None = Field(default=None, max_length=120)
    minutes: int = Field(default=10, ge=1, le=240)
    step_seconds: int = Field(default=15, ge=5, le=300)
    min_consecutive: int = Field(default=3, ge=1, le=20)


class TrainResponse(BaseModel):
    service: str
    environment: str
    model_version: str
    samples: int
    baseline: dict[str, dict[str, float]]


class Signal(BaseModel):
    metric: str
    observed: float
    baseline: float
    z_score: float


class AnomalyOut(BaseModel):
    anomaly_id: str
    application: str | None
    environment: str
    service: str
    metric_name: str
    observed_value: float
    baseline_value: float
    anomaly_score: float  # Isolation Forest score at the peak point (> 0 = outlier)
    severity: str
    detected_at: datetime  # the most extreme point of the episode
    started_at: datetime
    ended_at: datetime
    ongoing: bool
    model_version: str
    explanation: str
    contributing_signals: list[Signal]


class DetectResponse(BaseModel):
    service: str
    environment: str
    model_version: str
    points_analyzed: int
    anomalies: list[AnomalyOut]


def _fetch(service: str, environment: str, minutes: int, step: int):
    end = time.time()
    start = end - minutes * 60
    try:
        return prom.fetch_matrix(service, environment, start, end, step)
    except prom.NoDataError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except prom.PrometheusError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Prometheus unavailable: {exc}"
        )


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models", tags=["models"])
def list_models() -> list[dict]:
    return [
        {
            "service": service,
            "environment": environment,
            "model_version": model.version,
            "trained_at": model.trained_at,
            "samples": model.n_samples,
        }
        for environment, service, model in store.all()
    ]


@app.post("/train", response_model=TrainResponse, tags=["models"])
def train(req: TrainRequest) -> TrainResponse:
    """Learns the baseline from the last N minutes. YOU are asserting that window was normal."""
    _, X = _fetch(req.service, req.environment, req.minutes, req.step_seconds)
    median_rate = float(np.median(X[:, 0]))
    if median_rate < MIN_TRAIN_REQUEST_RATE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Median request rate in the window is {median_rate:.2f}/s. "
            "Generate steady traffic before training, or the baseline would be 'idle'.",
        )
    version = datetime.now(timezone.utc).strftime("if-%Y%m%d%H%M%S")
    try:
        model = AnomalyModel.train(X, version=version)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    store.save(req.environment, req.service, model)
    return TrainResponse(
        service=req.service,
        environment=req.environment,
        model_version=version,
        samples=len(X),
        baseline={
            name: {"baseline": float(model.median[i]), "scale": float(model.scale[i])}
            for i, name in enumerate(FEATURE_NAMES)
        },
    )


@app.post("/detect", response_model=DetectResponse, tags=["detection"])
def detect(req: DetectRequest) -> DetectResponse:
    model = store.get(req.environment, req.service)
    if model is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No trained model for this service. Call POST /train first.",
        )
    timestamps, X = _fetch(req.service, req.environment, req.minutes, req.step_seconds)
    results = model.score(X)

    def to_dt(i: int) -> datetime:
        return datetime.fromtimestamp(float(timestamps[i]), tz=timezone.utc)

    anomalies = []
    for start_i, end_i in find_episodes(results, req.min_consecutive):
        peak = max(range(start_i, end_i + 1), key=lambda i: results[i].max_abs_z)
        r = results[peak]
        primary = max(r.deviations, key=lambda d: abs(d.z_score))
        anomalies.append(
            AnomalyOut(
                anomaly_id=str(uuid.uuid4()),
                application=req.application,
                environment=req.environment,
                service=req.service,
                metric_name=primary.metric,
                observed_value=primary.observed,
                baseline_value=primary.baseline,
                anomaly_score=r.forest_score,
                severity=classify_severity(r.deviations),
                detected_at=to_dt(peak),
                started_at=to_dt(start_i),
                ended_at=to_dt(end_i),
                ongoing=end_i == len(results) - 1,
                model_version=model.version,
                explanation=explain(r),
                contributing_signals=[
                    Signal(
                        metric=d.metric,
                        observed=d.observed,
                        baseline=d.baseline,
                        z_score=d.z_score,
                    )
                    for d in r.deviations
                ],
            )
        )
    return DetectResponse(
        service=req.service,
        environment=req.environment,
        model_version=model.version,
        points_analyzed=len(results),
        anomalies=anomalies,
    )