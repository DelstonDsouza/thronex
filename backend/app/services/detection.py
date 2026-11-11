"""Turns ML-service anomalies into deduplicated incidents."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    SEVERITY_RANK,
    Anomaly,
    Environment,
    Incident,
    IncidentCategory,
    IncidentEvent,
    IncidentStatus,
    Service,
    ServiceDependency,
    Severity,
)
from app.services.incident_workflow import OPEN_STATUSES, add_event


class MlServiceError(Exception):
    """The ML service is unreachable or returned an unexpected response."""


def call_ml(
    service: str, environment: str, application: str
) -> tuple[list[dict] | None, str]:
    """Returns (anomalies, note). anomalies is None when the service cannot be analyzed."""
    try:
        response = httpx.post(
            f"{settings.ml_service_url}/detect",
            json={
                "service": service,
                "environment": environment,
                "application": application,
                "minutes": 5,
                "step_seconds": 15,
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise MlServiceError(f"ML service unreachable: {exc}") from exc
    if response.status_code == 404:
        return None, "no trained model or no telemetry for this service"
    if response.status_code == 422:
        return None, "service name not accepted by the ML service"
    if response.status_code != 200:
        raise MlServiceError(f"ML service returned HTTP {response.status_code}")
    return response.json()["anomalies"], "ok"


# ---------------------------------------------------------------- dependency graph
@dataclass
class Graph:
    calls: dict[int, set[int]] = field(default_factory=dict)  # service -> what it depends on
    neighbours: dict[int, set[int]] = field(default_factory=dict)  # undirected


def load_graph(db: Session, env_id: int) -> Graph:
    calls: dict[int, set[int]] = defaultdict(set)
    neighbours: dict[int, set[int]] = defaultdict(set)
    for dep in db.scalars(
        select(ServiceDependency).where(ServiceDependency.environment_id == env_id)
    ):
        calls[dep.source_service_id].add(dep.target_service_id)
        neighbours[dep.source_service_id].add(dep.target_service_id)
        neighbours[dep.target_service_id].add(dep.source_service_id)
    return Graph(dict(calls), dict(neighbours))


def component(graph: Graph, start: int) -> set[int]:
    """All services connected to `start` through dependencies (either direction)."""
    seen, stack = {start}, [start]
    while stack:
        for nxt in graph.neighbours.get(stack.pop(), set()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


# ---------------------------------------------------------------- classification
CATEGORY_LABEL = {
    IncidentCategory.RESOURCE_EXHAUSTION: "Resource exhaustion",
    IncidentCategory.HIGH_LATENCY: "High latency",
    IncidentCategory.TRAFFIC_SPIKE: "Traffic spike",
    IncidentCategory.SERVICE_FAILURE: "Service failure",
    IncidentCategory.DATABASE_CONNECTIVITY: "Database connectivity failure",
    IncidentCategory.AUTHENTICATION_ANOMALY: "Authentication anomaly",
    IncidentCategory.DEPLOYMENT_REGRESSION: "Deployment regression",
    IncidentCategory.UNKNOWN: "Unclassified anomaly",
}

# Rule-based. Database, authentication and deployment categories exist in the data
# model but nothing produces them yet (we have no such signals or labeled data).
ACTIONS = {
    IncidentCategory.RESOURCE_EXHAUSTION: [
        "Compare CPU and memory of {svc} with its limits.",
        "Look for a runaway process or a memory leak.",
        "Scale or restart {svc} only after you understand the cause.",
    ],
    IncidentCategory.HIGH_LATENCY: [
        "Check the logs of {svc} for slow operations or timeouts.",
        "Check what {svc} depends on (database, other services) for slowness.",
        "Review recent deployments or configuration changes to {svc}.",
    ],
    IncidentCategory.TRAFFIC_SPIKE: [
        "Check where the extra traffic comes from (a client, a retry storm, a test).",
        "Check whether {svc} still has headroom for CPU, memory and connections.",
    ],
    IncidentCategory.SERVICE_FAILURE: [
        "Check whether {svc} is running and passing health checks.",
        "Check the logs of {svc} for crashes or errors.",
        "Check the services {svc} depends on.",
    ],
    IncidentCategory.UNKNOWN: [
        "Inspect the contributing signals and the logs of {svc}.",
    ],
}


def classify(anomalies: list[Anomaly]) -> IncidentCategory:
    signals = [s for a in anomalies for s in (a.contributing_signals or [])]
    metrics = {s["metric"] for s in signals}
    if metrics & {"cpu_cores", "memory_mb"}:
        return IncidentCategory.RESOURCE_EXHAUSTION
    if any(s["metric"] == "request_rate" and s["observed"] > s["baseline"] for s in signals):
        return IncidentCategory.TRAFFIC_SPIKE
    if any(s["metric"] == "error_rate" and s["observed"] >= 0.5 for s in signals):
        return IncidentCategory.SERVICE_FAILURE
    if "latency_p95" in metrics:
        return IncidentCategory.HIGH_LATENCY
    if "error_rate" in metrics:
        return IncidentCategory.SERVICE_FAILURE
    return IncidentCategory.UNKNOWN


def build_hypothesis(
    anomalies: list[Anomaly],
    names: dict[int, str],
    origins: list[int],
    has_edges: bool,
) -> str:
    latest = {a.service_id: a for a in anomalies}
    evidence = "; ".join(
        f"{names[sid]}: {a.metric_name} {a.observed_value:.3g} vs baseline {a.baseline_value:.3g}"
        for sid, a in sorted(latest.items(), key=lambda kv: names[kv[0]])
    )
    origin_names = ", ".join(names[o] for o in origins)
    if len(latest) == 1:
        return (
            f"Evidence: only {origin_names} deviates ({evidence}). "
            f"Hypothesis: the problem may be local to {origin_names} (its own resources "
            "or code, or a dependency that is not monitored). "
            "This is a hypothesis, not a confirmed cause."
        )
    if has_edges and len(origins) == 1:
        return (
            f"Evidence: {len(latest)} connected services deviate at the same time "
            f"({evidence}). The configured dependencies show the other affected services "
            f"depend, directly or indirectly, on {origin_names}, which does not depend on "
            f"any other anomalous service. Hypothesis: the problem may originate in "
            f"{origin_names} and propagate to its callers. This is a correlation, not "
            f"proof: confirm with the logs and traces of {origin_names}."
        )
    if has_edges:
        return (
            f"Evidence: {len(latest)} connected services deviate ({evidence}). "
            f"There is more than one possible starting point ({origin_names}). "
            "Hypothesis: separate problems, or a shared dependency that is not configured. "
            "This is not a confirmed cause."
        )
    return (
        f"Evidence: {len(latest)} services deviate ({evidence}). No anomalous service "
        "directly depends on another anomalous one in the configured dependencies, so "
        "propagation cannot be assessed. Hypothesis: unknown. They may share a cause "
        "(for example the same host) or be unrelated."
    )


# ---------------------------------------------------------------- incident handling
def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _anomaly_values(a: dict) -> dict:
    return {
        "ml_anomaly_id": a.get("anomaly_id"),
        "metric_name": a["metric_name"],
        "observed_value": a["observed_value"],
        "baseline_value": a["baseline_value"],
        "anomaly_score": a["anomaly_score"],
        "severity": Severity(a["severity"]),
        "detected_at": _parse_dt(a["detected_at"]),
        "started_at": _parse_dt(a["started_at"]),
        "ended_at": _parse_dt(a["ended_at"]),
        "ongoing": bool(a["ongoing"]),
        "model_version": a["model_version"],
        "explanation": a["explanation"],
        "contributing_signals": a.get("contributing_signals", []),
    }


def _find_open_incident(
    db: Session, env_id: int, service_id: int, graph: Graph
) -> Incident | None:
    connected = component(graph, service_id)
    open_incidents = db.scalars(
        select(Incident)
        .where(Incident.environment_id == env_id, Incident.status.in_(OPEN_STATUSES))
        .order_by(Incident.id)
    ).all()
    for incident in open_incidents:
        involved = set(
            db.scalars(select(Anomaly.service_id).where(Anomaly.incident_id == incident.id))
        )
        if involved & connected:
            return incident
    return None


def _sync_service(
    db: Session,
    env: Environment,
    svc: Service,
    ml_anomalies: list[dict],
    graph: Graph,
    touched: set[int],
) -> None:
    ongoing = next((a for a in ml_anomalies if a.get("ongoing")), None)
    active = db.scalar(
        select(Anomaly)
        .where(Anomaly.service_id == svc.id, Anomaly.ongoing.is_(True))
        .order_by(Anomaly.id.desc())
        .limit(1)
    )

    if ongoing is None:
        if active is not None:  # the problem ended
            active.ongoing = False
            if active.incident_id is not None:
                touched.add(active.incident_id)
        return

    values = _anomaly_values(ongoing)
    if active is not None:  # same problem still going: update, never duplicate
        for key, value in values.items():
            if key != "started_at":
                setattr(active, key, value)
        if active.incident_id is not None:
            touched.add(active.incident_id)
        return

    incident = _find_open_incident(db, env.id, svc.id, graph)
    if incident is None:
        incident = Incident(
            environment_id=env.id,
            service_id=svc.id,
            title=f"Anomaly in {svc.name}",
            description="",
            severity=values["severity"],
            category=IncidentCategory.UNKNOWN,
            status=IncidentStatus.DETECTED,
            started_at=values["started_at"],
            recommended_actions=[],
        )
        db.add(incident)
        db.flush()
        add_event(db, incident, "detected", f"Incident created from an anomaly on {svc.name}.")

    db.add(Anomaly(service_id=svc.id, incident_id=incident.id, **values))
    db.flush()  # session has autoflush off, so later lookups must see this row
    add_event(
        db,
        incident,
        "anomaly_added",
        f"{svc.name}: {values['metric_name']} is {values['observed_value']:.3g} "
        f"(baseline {values['baseline_value']:.3g}).",
    )
    touched.add(incident.id)


def refresh_incident(db: Session, incident: Incident, env: Environment, graph: Graph) -> None:
    """Recomputes severity, category, hypothesis and title from all linked anomalies."""
    db.flush()
    anomalies = list(
        db.scalars(select(Anomaly).where(Anomaly.incident_id == incident.id).order_by(Anomaly.id))
    )
    if not anomalies:
        return
    anomalous = {a.service_id for a in anomalies}
    names = {
        s.id: s.name for s in db.scalars(select(Service).where(Service.id.in_(anomalous)))
    }

    severity = max((a.severity for a in anomalies), key=lambda s: SEVERITY_RANK[s])
    if severity != incident.severity:
        add_event(
            db,
            incident,
            "severity_changed",
            f"Severity changed from {incident.severity.value} to {severity.value}.",
        )
        incident.severity = severity

    category = classify(anomalies)
    origins = sorted(
        (s for s in anomalous if not (graph.calls.get(s, set()) & anomalous)),
        key=lambda s: names[s],
    ) or sorted(anomalous, key=lambda s: names[s])
    has_edges = any(graph.calls.get(s, set()) & anomalous for s in anomalous)
    origin_names = ", ".join(names[o] for o in origins)
    dependents = len(anomalous) - len(origins)

    title = f"{CATEGORY_LABEL[category]}: {origin_names}"
    if dependents > 0:
        title += f" (affecting {dependents} dependent service(s))"

    incident.title = title[:255]
    incident.category = category
    incident.service_id = origins[0]
    incident.started_at = min(a.started_at for a in anomalies)
    incident.root_cause_hypothesis = build_hypothesis(anomalies, names, origins, has_edges)
    incident.description = (
        f"{len(anomalous)} service(s) in {env.name} deviate from their learned baseline: "
        f"{', '.join(sorted(names.values()))}. Detected automatically by the THRONEX ML service."
    )
    templates = ACTIONS.get(category, ACTIONS[IncidentCategory.UNKNOWN])
    incident.recommended_actions = [t.format(svc=origin_names) for t in templates]

    if incident.status in OPEN_STATUSES and not any(a.ongoing for a in anomalies):
        last_type = db.scalar(
            select(IncidentEvent.event_type)
            .where(IncidentEvent.incident_id == incident.id)
            .order_by(IncidentEvent.id.desc())
            .limit(1)
        )
        if last_type != "telemetry_recovered":
            add_event(
                db,
                incident,
                "telemetry_recovered",
                "Telemetry has returned to baseline. The incident stays open until a "
                "person resolves it.",
            )


# ---------------------------------------------------------------- the job
@dataclass
class ServiceOutcome:
    service: str
    outcome: str  # ok | skipped | error
    detail: str


@dataclass
class DetectionReport:
    results: list[ServiceOutcome]
    incident_ids: list[int]


def run_detection(db: Session, env: Environment) -> DetectionReport:
    """One detection pass over every active service in the environment."""
    services = list(
        db.scalars(
            select(Service)
            .where(Service.environment_id == env.id, Service.is_active.is_(True))
            .order_by(Service.name)
        )
    )
    graph = load_graph(db, env.id)
    results: list[ServiceOutcome] = []
    touched: set[int] = set()

    for svc in services:
        try:
            anomalies, note = call_ml(svc.name, env.env_type.value, env.application.name)
        except MlServiceError as exc:
            results.append(ServiceOutcome(svc.name, "error", str(exc)))
            continue
        if anomalies is None:
            results.append(ServiceOutcome(svc.name, "skipped", note))
            continue
        _sync_service(db, env, svc, anomalies, graph, touched)
        results.append(
            ServiceOutcome(svc.name, "ok", f"{len(anomalies)} anomaly record(s) from the ML service")
        )

    for incident_id in sorted(touched):
        incident = db.get(Incident, incident_id)
        if incident is not None:
            refresh_incident(db, incident, env, graph)
    db.commit()
    return DetectionReport(results=results, incident_ids=sorted(touched))