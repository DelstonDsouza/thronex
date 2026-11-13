import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RemediationStatus(str, enum.Enum):
    RECOMMENDED = "recommended"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class Remediation(Base):
    __tablename__ = "remediations"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    service_name: Mapped[str] = mapped_column(String(120))
    container: Mapped[str] = mapped_column(String(120))
    action_type: Mapped[str] = mapped_column(String(40), default="restart_service")
    status: Mapped[RemediationStatus] = mapped_column(
        Enum(RemediationStatus, native_enum=False, length=20),
        default=RemediationStatus.RECOMMENDED,
    )
    reason: Mapped[str] = mapped_column(Text)
    expected_impact: Mapped[str] = mapped_column(Text)
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_message: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool | None] = mapped_column(Boolean)
    verification: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int | None]
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)