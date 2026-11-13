import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.access import load_incident, require_org_role
from app.api.deps import CurrentUser, DbSession
from app.api.monitoring import _build_summary
from app.models import (
    AuditLog,
    Incident,
    Remediation,
    RemediationStatus,
    Role,
    Service,
    ServiceStatus,
)
from app.schemas.remediation import AuditLogOut, RemediationOut
from app.services import agent
from app.services.agent import AgentError
from app.services.audit import record_audit
from app.services.incident_workflow import OPEN_STATUSES, add_event

router = APIRouter()

COOLDOWN = timedelta(minutes=5)
MAX_PER_HOUR = 3
HEALTH_POLLS = 15  # 15 polls x 3 s = up to 45 s for the container to become healthy


def _org_id(incident: Incident) -> int:
    return incident.environment.application.organization_id


def _load(db: DbSession, user: CurrentUser, rem_id: int, min_role: Role, lock: bool = False):
    stmt = select(Remediation).where(Remediation.id == rem_id)
    if lock:
        stmt = stmt.with_for_update()
    rem = db.scalar(stmt)
    if rem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    incident = load_incident(db, user, rem.incident_id, min_role)
    return rem, incident


def _guard_against_restart_loops(db: DbSession, rem: Remediation) -> None:
    now = datetime.now(timezone.utc)
    recent = list(
        db.scalars(
            select(Remediation.executed_at).where(
                Remediation.service_id == rem.service_id,
                Remediation.id != rem.id,
                Remediation.executed_at.is_not(None),
                Remediation.executed_at >= now - timedelta(hours=1),
            )
        )
    )
    if len(recent) >= MAX_PER_HOUR:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Blocked: {rem.service_name} was already restarted {len(recent)} times in the "
            "last hour. Repeated restarts usually mean the real cause is elsewhere.",
        )
    if any(t >= now - COOLDOWN for t in recent):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Blocked by cooldown: {rem.service_name} was restarted less than "
            f"{int(COOLDOWN.total_seconds() // 60)} minutes ago.",
        )


@router.post(
    "/incidents/{incident_id}/remediations",
    response_model=RemediationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["remediation"],
)
def suggest_remediation(incident_id: int, db: DbSession, user: CurrentUser) -> Remediation:
    """Creates a recommendation only. Nothing is executed until an admin approves."""
    incident = load_incident(db, user, incident_id, Role.OPERATOR)
    if incident.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The incident is not open")
    svc = incident.service
    if svc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The incident has no target service")
    if not svc.host:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Set the 'host' of {svc.name} to its container name first "
            "(PATCH /services/{id}).",
        )

    existing = db.scalar(
        select(Remediation).where(
            Remediation.incident_id == incident.id,
            Remediation.service_id == svc.id,
            Remediation.status == RemediationStatus.RECOMMENDED,
        )
    )
    if existing is not None:
        return existing

    rem = Remediation(
        incident_id=incident.id,
        service_id=svc.id,
        service_name=svc.name,
        container=svc.host,
        reason=(
            f"Incident #{incident.id} ({incident.category.value.replace('_', ' ')}) points to "
            f"{svc.name} as the most likely origin. This is a hypothesis, not a confirmed "
            "cause. A restart clears transient in-process problems such as stuck workers, "
            "leaked memory or injected faults. It will not fix a persistent cause such as "
            "bad configuration or a failing dependency."
        ),
        expected_impact=(
            f"Requests to {svc.name} fail for roughly 5 to 15 seconds while the container "
            "restarts. Any in-memory state in the service is lost."
        ),
        requested_by_id=user.id,
    )
    db.add(rem)
    db.flush()
    add_event(
        db, incident, "remediation_suggested",
        f"Restart of {svc.name} recommended by {user.full_name}. Awaiting approval.", user.id,
    )
    record_audit(
        db, user, _org_id(incident), "remediation.suggested", "remediation", rem.id,
        {"incident_id": incident.id, "service": svc.name},
    )
    db.commit()
    db.refresh(rem)
    return rem


@router.get(
    "/incidents/{incident_id}/remediations",
    response_model=list[RemediationOut],
    tags=["remediation"],
)
def list_remediations(incident_id: int, db: DbSession, user: CurrentUser) -> list[Remediation]:
    incident = load_incident(db, user, incident_id, Role.VIEWER)
    return list(
        db.scalars(
            select(Remediation)
            .where(Remediation.incident_id == incident.id)
            .order_by(Remediation.id.desc())
        )
    )


@router.post("/remediations/{rem_id}/approve", response_model=RemediationOut, tags=["remediation"])
def approve_remediation(rem_id: int, db: DbSession, user: CurrentUser) -> Remediation:
    """Approves and executes. This call can take up to ~60 seconds."""
    rem, incident = _load(db, user, rem_id, Role.ADMIN, lock=True)
    if rem.status != RemediationStatus.RECOMMENDED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Already {rem.status.value}; only recommendations can be approved"
        )
    svc = db.get(Service, rem.service_id)
    if svc is None or not svc.host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The target service no longer has a container")
    _guard_against_restart_loops(db, rem)

    org_id = _org_id(incident)
    now = datetime.now(timezone.utc)
    rem.container = svc.host
    rem.decided_by_id = user.id
    rem.decided_at = now
    rem.executed_at = now
    rem.status = RemediationStatus.EXECUTING
    add_event(
        db, incident, "remediation_approved",
        f"{user.full_name} approved restarting {rem.service_name}. Executing.", user.id,
    )
    record_audit(
        db, user, org_id, "remediation.approved", "remediation", rem.id,
        {"container": rem.container},
    )
    db.commit()  # releases the row lock; the status is now EXECUTING

    healthy = False
    try:
        agent.restart_container(rem.container)
        for _ in range(HEALTH_POLLS):
            state = agent.container_status(rem.container)
            if state.get("running") and state.get("health") in ("healthy", "none"):
                healthy = True
                break
            time.sleep(3)
        if healthy:
            rem.status = RemediationStatus.SUCCEEDED
            rem.result_message = (
                "Container restarted and reports healthy. Use 'Verify recovery' after "
                "about 1 to 2 minutes to confirm from telemetry."
            )
        else:
            rem.status = RemediationStatus.FAILED
            rem.result_message = "The restart ran, but the container did not become healthy within 45 seconds."
    except AgentError as exc:
        rem.status = RemediationStatus.FAILED
        rem.result_message = str(exc)

    rem.finished_at = datetime.now(timezone.utc)
    add_event(
        db, incident, "remediation_executed",
        f"Restart of {rem.service_name} {rem.status.value}: {rem.result_message}", user.id,
    )
    record_audit(
        db, user, org_id, "remediation.executed", "remediation", rem.id,
        {"result": rem.status.value},
    )
    db.commit()
    db.refresh(rem)
    return rem


@router.post("/remediations/{rem_id}/reject", response_model=RemediationOut, tags=["remediation"])
def reject_remediation(rem_id: int, db: DbSession, user: CurrentUser) -> Remediation:
    rem, incident = _load(db, user, rem_id, Role.ADMIN, lock=True)
    if rem.status != RemediationStatus.RECOMMENDED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already {rem.status.value}")
    rem.status = RemediationStatus.REJECTED
    rem.decided_by_id = user.id
    rem.decided_at = datetime.now(timezone.utc)
    add_event(db, incident, "remediation_rejected",
              f"{user.full_name} rejected restarting {rem.service_name}.", user.id)
    record_audit(db, user, _org_id(incident), "remediation.rejected", "remediation", rem.id)
    db.commit()
    db.refresh(rem)
    return rem


@router.post("/remediations/{rem_id}/verify", response_model=RemediationOut, tags=["remediation"])
def verify_remediation(rem_id: int, db: DbSession, user: CurrentUser) -> Remediation:
    """Checks live Prometheus telemetry for the service after a successful restart."""
    rem, incident = _load(db, user, rem_id, Role.OPERATOR)
    if rem.status != RemediationStatus.SUCCEEDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a succeeded restart can be verified")
    svc = db.get(Service, rem.service_id)
    if svc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service no longer exists")

    summary = _build_summary(incident.environment, [svc])[0]  # may raise 503
    verified = summary.computed_status == ServiceStatus.HEALTHY
    error = "no data" if summary.error_rate is None else f"{summary.error_rate:.1%}"
    rem.verified = verified
    rem.verification = (
        f"Telemetry status is '{summary.computed_status.value}' (error rate {error}). "
        + ("Recovery confirmed. You can now resolve the incident." if verified
           else "Not confirmed yet. Wait a minute and verify again, or investigate further.")
    )
    add_event(db, incident, "remediation_verified", rem.verification, user.id)
    record_audit(db, user, _org_id(incident), "remediation.verified", "remediation", rem.id,
                 {"verified": verified})
    db.commit()
    db.refresh(rem)
    return rem


@router.get(
    "/organizations/{org_id}/audit-logs",
    response_model=list[AuditLogOut],
    tags=["remediation"],
)
def list_audit_logs(
    org_id: int, db: DbSession, user: CurrentUser, limit: int = Query(default=100, ge=1, le=500)
) -> list[AuditLog]:
    require_org_role(db, user, org_id, Role.ADMIN)
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == org_id)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
    )