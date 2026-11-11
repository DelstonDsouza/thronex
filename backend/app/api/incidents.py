from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.access import load_environment, load_incident, require_org_role
from app.api.deps import CurrentUser, DbSession
from app.models import (
    Application,
    Environment,
    Incident,
    IncidentComment,
    IncidentStatus,
    OrganizationMember,
    Role,
    Service,
    ServiceDependency,
    Severity,
)
from app.schemas.incident import (
    AssignRequest,
    CommentCreate,
    DependencyCreate,
    DependencyOut,
    DetectionReportOut,
    IncidentDetail,
    IncidentStats,
    IncidentSummary,
    ServiceOutcomeOut,
    StatusChange,
)
from app.services import detection
from app.services import incident_workflow as workflow

router = APIRouter()


# ======================= Service dependencies =======================
@router.post(
    "/environments/{env_id}/dependencies",
    response_model=DependencyOut,
    status_code=status.HTTP_201_CREATED,
    tags=["dependencies"],
)
def create_dependency(
    env_id: int, payload: DependencyCreate, db: DbSession, user: CurrentUser
) -> ServiceDependency:
    env = load_environment(db, user, env_id, Role.ADMIN)
    source, target = payload.source_service_id, payload.target_service_id
    if source == target:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A service cannot depend on itself")
    found = set(
        db.scalars(
            select(Service.id).where(
                Service.environment_id == env.id, Service.id.in_([source, target])
            )
        )
    )
    if found != {source, target}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Both services must belong to this environment"
        )
    dep = ServiceDependency(
        environment_id=env.id, source_service_id=source, target_service_id=target
    )
    db.add(dep)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This dependency already exists")
    db.refresh(dep)
    return dep


@router.get(
    "/environments/{env_id}/dependencies",
    response_model=list[DependencyOut],
    tags=["dependencies"],
)
def list_dependencies(env_id: int, db: DbSession, user: CurrentUser) -> list[ServiceDependency]:
    env = load_environment(db, user, env_id, Role.VIEWER)
    return list(
        db.scalars(select(ServiceDependency).where(ServiceDependency.environment_id == env.id))
    )


@router.delete(
    "/dependencies/{dep_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["dependencies"]
)
def delete_dependency(dep_id: int, db: DbSession, user: CurrentUser) -> Response:
    dep = db.get(ServiceDependency, dep_id)
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    load_environment(db, user, dep.environment_id, Role.ADMIN)
    db.delete(dep)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================= Detection job =======================
@router.post(
    "/environments/{env_id}/detection/run",
    response_model=DetectionReportOut,
    tags=["incidents"],
)
def run_detection_now(env_id: int, db: DbSession, user: CurrentUser) -> DetectionReportOut:
    """Runs one detection pass: asks the ML service about every active service."""
    env = load_environment(db, user, env_id, Role.OPERATOR)
    report = detection.run_detection(db, env)
    return DetectionReportOut(
        results=[
            ServiceOutcomeOut(service=r.service, outcome=r.outcome, detail=r.detail)
            for r in report.results
        ],
        incident_ids=report.incident_ids,
    )


# ======================= Incidents =======================
def _org_incidents_query(org_id: int):
    return (
        select(Incident)
        .join(Environment, Incident.environment_id == Environment.id)
        .join(Application, Environment.application_id == Application.id)
        .where(Application.organization_id == org_id)
    )


@router.get(
    "/organizations/{org_id}/incidents",
    response_model=list[IncidentSummary],
    tags=["incidents"],
)
def list_incidents(
    org_id: int,
    db: DbSession,
    user: CurrentUser,
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    severity: Severity | None = None,
    environment_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Incident]:
    require_org_role(db, user, org_id, Role.VIEWER)
    stmt = _org_incidents_query(org_id)
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if environment_id:
        stmt = stmt.where(Incident.environment_id == environment_id)
    if q:
        stmt = stmt.where(Incident.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(Incident.created_at.desc(), Incident.id.desc())
    return list(db.scalars(stmt.limit(limit).offset(offset)))


@router.get(
    "/organizations/{org_id}/incidents/stats",
    response_model=IncidentStats,
    tags=["incidents"],
)
def incident_stats(
    org_id: int, db: DbSession, user: CurrentUser, days: int = Query(default=14, ge=1, le=90)
) -> IncidentStats:
    require_org_role(db, user, org_id, Role.VIEWER)
    incidents = list(db.scalars(_org_incidents_query(org_id)))

    mttd = [max(0.0, (i.created_at - i.started_at).total_seconds()) for i in incidents]
    mttr = [
        (i.resolved_at - i.created_at).total_seconds() for i in incidents if i.resolved_at
    ]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    per_day = Counter(
        i.created_at.astimezone(timezone.utc).date().isoformat()
        for i in incidents
        if i.created_at >= cutoff
    )
    return IncidentStats(
        total=len(incidents),
        open=sum(1 for i in incidents if i.status in workflow.OPEN_STATUSES),
        by_status=dict(Counter(i.status.value for i in incidents)),
        by_severity=dict(Counter(i.severity.value for i in incidents)),
        mttd_seconds=sum(mttd) / len(mttd) if mttd else None,
        mttr_seconds=sum(mttr) / len(mttr) if mttr else None,
        per_day=dict(sorted(per_day.items())),
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
def get_incident(incident_id: int, db: DbSession, user: CurrentUser) -> IncidentDetail:
    incident = load_incident(db, user, incident_id, Role.VIEWER)
    return IncidentDetail.model_validate(incident)


@router.post(
    "/incidents/{incident_id}/status", response_model=IncidentDetail, tags=["incidents"]
)
def change_status(
    incident_id: int, body: StatusChange, db: DbSession, user: CurrentUser
) -> IncidentDetail:
    incident = load_incident(db, user, incident_id, Role.OPERATOR)
    if body.status == IncidentStatus.RESOLVED and not (body.resolution_notes or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resolution_notes are required to resolve an incident"
        )
    try:
        workflow.apply_status_change(db, incident, body.status, user, body.resolution_notes)
    except workflow.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.commit()
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)


@router.post(
    "/incidents/{incident_id}/assign", response_model=IncidentDetail, tags=["incidents"]
)
def assign_incident(
    incident_id: int, body: AssignRequest, db: DbSession, user: CurrentUser
) -> IncidentDetail:
    incident = load_incident(db, user, incident_id, Role.OPERATOR)
    org_id = incident.environment.application.organization_id
    if body.user_id is None:
        incident.assigned_user_id = None
        workflow.add_event(db, incident, "assigned", f"Unassigned by {user.full_name}.", user.id)
    else:
        member = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == body.user_id,
                OrganizationMember.organization_id == org_id,
            )
        )
        if member is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "User is not a member of this organization"
            )
        incident.assigned_user_id = body.user_id
        workflow.add_event(
            db,
            incident,
            "assigned",
            f"Assigned to {member.user.full_name} by {user.full_name}.",
            user.id,
        )
    db.commit()
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)


@router.post(
    "/incidents/{incident_id}/comments",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["incidents"],
)
def add_comment(
    incident_id: int, body: CommentCreate, db: DbSession, user: CurrentUser
) -> IncidentDetail:
    incident = load_incident(db, user, incident_id, Role.OPERATOR)
    db.add(IncidentComment(incident_id=incident.id, user_id=user.id, body=body.body))
    workflow.add_event(db, incident, "comment", f"{user.full_name} added a comment.", user.id)
    db.commit()
    db.refresh(incident)
    return IncidentDetail.model_validate(incident)