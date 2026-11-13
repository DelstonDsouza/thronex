from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    user: User | None,
    org_id: int,
    action: str,
    target_type: str,
    target_id: int | None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=org_id,
            user_id=user.id if user else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )