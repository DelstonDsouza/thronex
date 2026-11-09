import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EnvironmentType(str, enum.Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class ServiceType(str, enum.Enum):
    API = "api"
    DATABASE = "database"
    CACHE = "cache"
    WORKER = "worker"
    OTHER = "other"


class ServiceStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="applications")
    environments: Mapped[list["Environment"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class Environment(Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("application_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    env_type: Mapped[EnvironmentType] = mapped_column(
        Enum(EnvironmentType, native_enum=False, length=20)
    )
    # Safety flag for Day 4: chaos experiments only run where this is True.
    chaos_enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    application: Mapped["Application"] = relationship(back_populates="environments")
    services: Mapped[list["Service"]] = relationship(
        back_populates="environment", cascade="all, delete-orphan"
    )


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("environment_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    service_type: Mapped[ServiceType] = mapped_column(
        Enum(ServiceType, native_enum=False, length=20), default=ServiceType.API
    )
    host: Mapped[str | None] = mapped_column(String(255))  # hostname or container name
    port: Mapped[int | None] = mapped_column(Integer)
    health_check_path: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus, native_enum=False, length=20), default=ServiceStatus.UNKNOWN
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    environment: Mapped["Environment"] = relationship(back_populates="services")