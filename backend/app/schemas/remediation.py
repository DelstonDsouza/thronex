from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import RemediationStatus


class RemediationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    service_id: int
    service_name: str
    container: str
    action_type: str
    status: RemediationStatus
    reason: str
    expected_impact: str
    requested_by_id: int | None
    decided_by_id: int | None
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
    finished_at: datetime | None
    result_message: str | None
    verified: bool | None
    verification: str | None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    target_type: str
    target_id: int | None
    details: dict
    created_at: datetime