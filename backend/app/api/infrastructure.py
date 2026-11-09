from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.access import (
    load_application,
    load_environment,
    load_service,
    require_org_role,
)
from app.api.deps import CurrentUser, DbSession
from app.models import Application, Environment, EnvironmentType, Role, Service
from app.schemas.infrastructure import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentUpdate,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
)

router = APIRouter()


def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, conflict_message)


def _check_chaos_safety(env_type: EnvironmentType, chaos_enabled: bool) -> None:
    """Safety rule: chaos experiments can never be enabled on production."""
    if env_type == EnvironmentType.PRODUCTION and chaos_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Chaos experiments cannot be enabled on production environments",
        )


def _apply_updates(obj: object, data: dict) -> None:
    # Fields sent as null are ignored (this keeps required columns safe).
    for field, value in data.items():
        if value is not None:
            setattr(obj, field, value)


# ======================= Applications =======================
@router.post(
    "/organizations/{org_id}/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
)
def create_application(
    org_id: int, payload: ApplicationCreate, db: DbSession, user: CurrentUser
) -> Application:
    require_org_role(db, user, org_id, Role.ADMIN)
    app = Application(organization_id=org_id, **payload.model_dump())
    db.add(app)
    _commit(db, "An application with this name already exists")
    db.refresh(app)
    return app


@router.get(
    "/organizations/{org_id}/applications",
    response_model=list[ApplicationOut],
    tags=["applications"],
)
def list_applications(
    org_id: int, db: DbSession, user: CurrentUser
) -> list[Application]:
    require_org_role(db, user, org_id, Role.VIEWER)
    return list(
        db.scalars(
            select(Application)
            .where(Application.organization_id == org_id)
            .order_by(Application.name)
        )
    )


@router.get(
    "/applications/{app_id}", response_model=ApplicationOut, tags=["applications"]
)
def get_application(app_id: int, db: DbSession, user: CurrentUser) -> Application:
    return load_application(db, user, app_id, Role.VIEWER)


@router.patch(
    "/applications/{app_id}", response_model=ApplicationOut, tags=["applications"]
)
def update_application(
    app_id: int, payload: ApplicationUpdate, db: DbSession, user: CurrentUser
) -> Application:
    app = load_application(db, user, app_id, Role.ADMIN)
    _apply_updates(app, payload.model_dump(exclude_unset=True))
    _commit(db, "An application with this name already exists")
    db.refresh(app)
    return app


@router.delete(
    "/applications/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["applications"],
)
def delete_application(app_id: int, db: DbSession, user: CurrentUser) -> Response:
    app = load_application(db, user, app_id, Role.ADMIN)
    db.delete(app)  # cascades to its environments and services
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================= Environments =======================
@router.post(
    "/applications/{app_id}/environments",
    response_model=EnvironmentOut,
    status_code=status.HTTP_201_CREATED,
    tags=["environments"],
)
def create_environment(
    app_id: int, payload: EnvironmentCreate, db: DbSession, user: CurrentUser
) -> Environment:
    load_application(db, user, app_id, Role.ADMIN)
    _check_chaos_safety(payload.env_type, payload.chaos_enabled)
    env = Environment(application_id=app_id, **payload.model_dump())
    db.add(env)
    _commit(db, "An environment with this name already exists in this application")
    db.refresh(env)
    return env


@router.get(
    "/applications/{app_id}/environments",
    response_model=list[EnvironmentOut],
    tags=["environments"],
)
def list_environments(
    app_id: int, db: DbSession, user: CurrentUser
) -> list[Environment]:
    load_application(db, user, app_id, Role.VIEWER)
    return list(
        db.scalars(
            select(Environment)
            .where(Environment.application_id == app_id)
            .order_by(Environment.name)
        )
    )


@router.get(
    "/environments/{env_id}", response_model=EnvironmentOut, tags=["environments"]
)
def get_environment(env_id: int, db: DbSession, user: CurrentUser) -> Environment:
    return load_environment(db, user, env_id, Role.VIEWER)


@router.patch(
    "/environments/{env_id}", response_model=EnvironmentOut, tags=["environments"]
)
def update_environment(
    env_id: int, payload: EnvironmentUpdate, db: DbSession, user: CurrentUser
) -> Environment:
    env = load_environment(db, user, env_id, Role.ADMIN)
    data = payload.model_dump(exclude_unset=True)
    # Validate the final combined state, not just the fields that were sent.
    final_type = data.get("env_type") or env.env_type
    final_chaos = data.get("chaos_enabled")
    if final_chaos is None:
        final_chaos = env.chaos_enabled
    _check_chaos_safety(final_type, final_chaos)
    _apply_updates(env, data)
    _commit(db, "An environment with this name already exists in this application")
    db.refresh(env)
    return env


@router.delete(
    "/environments/{env_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["environments"],
)
def delete_environment(env_id: int, db: DbSession, user: CurrentUser) -> Response:
    env = load_environment(db, user, env_id, Role.ADMIN)
    db.delete(env)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================= Services =======================
@router.post(
    "/environments/{env_id}/services",
    response_model=ServiceOut,
    status_code=status.HTTP_201_CREATED,
    tags=["services"],
)
def create_service(
    env_id: int, payload: ServiceCreate, db: DbSession, user: CurrentUser
) -> Service:
    load_environment(db, user, env_id, Role.ADMIN)
    service = Service(environment_id=env_id, **payload.model_dump())
    db.add(service)
    _commit(db, "A service with this name already exists in this environment")
    db.refresh(service)
    return service


@router.get(
    "/environments/{env_id}/services",
    response_model=list[ServiceOut],
    tags=["services"],
)
def list_services(env_id: int, db: DbSession, user: CurrentUser) -> list[Service]:
    load_environment(db, user, env_id, Role.VIEWER)
    return list(
        db.scalars(
            select(Service).where(Service.environment_id == env_id).order_by(Service.name)
        )
    )


@router.get("/services/{service_id}", response_model=ServiceOut, tags=["services"])
def get_service(service_id: int, db: DbSession, user: CurrentUser) -> Service:
    return load_service(db, user, service_id, Role.VIEWER)


@router.patch("/services/{service_id}", response_model=ServiceOut, tags=["services"])
def update_service(
    service_id: int, payload: ServiceUpdate, db: DbSession, user: CurrentUser
) -> Service:
    service = load_service(db, user, service_id, Role.ADMIN)
    _apply_updates(service, payload.model_dump(exclude_unset=True))
    _commit(db, "A service with this name already exists in this environment")
    db.refresh(service)
    return service


@router.delete(
    "/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["services"],
)
def delete_service(service_id: int, db: DbSession, user: CurrentUser) -> Response:
    service = load_service(db, user, service_id, Role.ADMIN)
    db.delete(service)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)