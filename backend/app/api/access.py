from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    Environment,
    OrganizationMember,
    Role,
    Service,
    User,
)

ROLE_RANK = {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMIN: 3, Role.OWNER: 4}


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def require_org_role(
    db: Session, user: User, org_id: int, min_role: Role = Role.VIEWER
) -> OrganizationMember:
    """Ensures the user belongs to the organization with at least `min_role`."""
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
        )
    )
    if member is None:
        raise _not_found()  # not a member: pretend it doesn't exist
    if ROLE_RANK[member.role] < ROLE_RANK[min_role]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Requires role '{min_role.value}' or higher"
        )
    return member


def load_application(
    db: Session, user: User, app_id: int, min_role: Role = Role.VIEWER
) -> Application:
    app = db.get(Application, app_id)
    if app is None:
        raise _not_found()
    require_org_role(db, user, app.organization_id, min_role)
    return app


def load_environment(
    db: Session, user: User, env_id: int, min_role: Role = Role.VIEWER
) -> Environment:
    env = db.get(Environment, env_id)
    if env is None:
        raise _not_found()
    require_org_role(db, user, env.application.organization_id, min_role)
    return env


def load_service(
    db: Session, user: User, service_id: int, min_role: Role = Role.VIEWER
) -> Service:
    service = db.get(Service, service_id)
    if service is None:
        raise _not_found()
    require_org_role(
        db, user, service.environment.application.organization_id, min_role
    )
    return service