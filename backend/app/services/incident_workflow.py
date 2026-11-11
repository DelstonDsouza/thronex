"""Incident lifecycle rules and the event timeline."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Incident, IncidentEvent, IncidentStatus, User

S = IncidentStatus

OPEN_STATUSES = (S.DETECTED, S.ACKNOWLEDGED, S.INVESTIGATING, S.MITIGATING)

ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    S.DETECTED: {S.ACKNOWLEDGED, S.INVESTIGATING, S.RESOLVED},
    S.ACKNOWLEDGED: {S.INVESTIGATING, S.MITIGATING, S.RESOLVED},
    S.INVESTIGATING: {S.MITIGATING, S.RESOLVED},
    S.MITIGATING: {S.INVESTIGATING, S.RESOLVED},
    S.RESOLVED: {S.INVESTIGATING, S.CLOSED},  # INVESTIGATING = reopen
    S.CLOSED: set(),
}


class InvalidTransition(Exception):
    pass


def add_event(
    db: Session,
    incident: Incident,
    event_type: str,
    message: str,
    actor_id: int | None = None,
) -> None:
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type=event_type,
            message=message,
            actor_user_id=actor_id,
        )
    )


def apply_status_change(
    db: Session,
    incident: Incident,
    new_status: IncidentStatus,
    user: User,
    notes: str | None = None,
) -> None:
    allowed = ALLOWED_TRANSITIONS[incident.status]
    if new_status not in allowed:
        options = ", ".join(sorted(s.value for s in allowed)) or "none (closed is final)"
        raise InvalidTransition(
            f"Cannot move from '{incident.status.value}' to '{new_status.value}'. "
            f"Allowed: {options}"
        )

    now = datetime.now(timezone.utc)
    old = incident.status
    if (
        new_status in (S.ACKNOWLEDGED, S.INVESTIGATING, S.MITIGATING)
        and incident.acknowledged_at is None
    ):
        incident.acknowledged_at = now
    if new_status == S.RESOLVED:
        incident.resolved_at = now
        incident.resolution_notes = notes
    elif old == S.RESOLVED and new_status == S.INVESTIGATING:
        incident.resolved_at = None  # reopened
    if new_status == S.CLOSED:
        incident.closed_at = now
    incident.status = new_status

    message = f"Status changed from {old.value} to {new_status.value} by {user.full_name}."
    if notes:
        message += f" Notes: {notes}"
    add_event(db, incident, "status_changed", message, user.id)