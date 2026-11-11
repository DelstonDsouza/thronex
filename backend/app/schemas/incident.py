from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import IncidentCategory, IncidentStatus, Severity


class DependencyCreate(BaseModel):
    """`source_service_id` depends on (calls) `target_service_id`."""

    source_service_id: int
    target_service_id: int


class DependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    source_service_id: int
    target_service_id: int
    created_at: datetime


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    incident_id: int | None
    metric_name: str
    observed_value: float
    baseline_value: float
    anomaly_score: float
    severity: Severity
    detected_at: datetime
    started_at: datetime
    ended_at: datetime
    ongoing: bool
    model_version: str
    explanation: str
    contributing_signals: list[dict]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    message: str
    actor_user_id: int | None
    created_at: datetime


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    body: str
    created_at: datetime


class IncidentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    service_id: int | None
    title: str
    severity: Severity
    category: IncidentCategory
    status: IncidentStatus
    assigned_user_id: int | None
    started_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None


class IncidentDetail(IncidentSummary):
    description: str
    root_cause_hypothesis: str | None
    recommended_actions: list[str]
    resolution_notes: str | None
    anomalies: list[AnomalyOut]
    events: list[EventOut]
    comments: list[CommentOut]


class StatusChange(BaseModel):
    status: IncidentStatus
    resolution_notes: str | None = Field(default=None, max_length=4000)


class AssignRequest(BaseModel):
    user_id: int | None  # null = unassign


class ServiceOutcomeOut(BaseModel):
    service: str
    outcome: str
    detail: str


class DetectionReportOut(BaseModel):
    results: list[ServiceOutcomeOut]
    incident_ids: list[int]


class IncidentStats(BaseModel):
    total: int
    open: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    mttd_seconds: float | None  # mean time to detect: detection time minus problem start
    mttr_seconds: float | None  # mean time to resolve: resolved time minus detection time
    per_day: dict[str, int]  # incidents created per UTC day