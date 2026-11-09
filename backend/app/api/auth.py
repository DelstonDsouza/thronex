import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Organization, OrganizationMember, Role, User
from app.schemas.auth import (
    MeOut,
    MembershipOut,
    RegisterRequest,
    Token,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    return f"{base}-{secrets.token_hex(3)}"  # random suffix keeps slugs unique


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
    )
    org = Organization(name=payload.organization_name, slug=_make_slug(payload.organization_name))
    db.add_all([user, org])
    db.flush()  # assigns ids without committing yet

    db.add(OrganizationMember(user_id=user.id, organization_id=org.id, role=Role.OWNER))
    db.commit()
    return user


@router.post("/login", response_model=Token)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession
) -> Token:
    # The OAuth2 form calls the email field "username".
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not user.is_active or not verify_password(
        form.password, user.hashed_password
    ):
        # Same message for both cases so attackers can't tell which emails exist.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=MeOut)
def me(current_user: CurrentUser) -> MeOut:
    return MeOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        memberships=[
            MembershipOut(
                organization_id=m.organization_id,
                organization_name=m.organization.name,
                role=m.role,
            )
            for m in current_user.memberships
        ],
    )