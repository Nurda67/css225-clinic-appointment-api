from datetime import date as Date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.database import CLINIC_TZ
from app.schemas import RequestBody


class WaitlistInput(RequestBody):
    doctor_id: int = Field(gt=0, strict=True)
    date: Date


class WaitlistView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    day: Date
    status: Literal["waiting", "offered", "booked", "expired"]
    offered_start: datetime | None
    appointment_id: int | None
    created_at: datetime

    @field_serializer("offered_start", "created_at")
    def clinic_time(self, value: datetime | None) -> str | None:
        return value.astimezone(CLINIC_TZ).isoformat() if value is not None else None


class ShiftReplacementInput(RequestBody):
    doctor_id: int = Field(gt=0, strict=True)
    replacement_doctor_id: int = Field(gt=0, strict=True)
    date: Date


class ReplacementOfferView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    original_doctor_id: int
    replacement_doctor_id: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["pending", "accepted", "stale"]
    created_at: datetime

    @field_serializer("starts_at", "ends_at", "created_at")
    def clinic_time(self, value: datetime) -> str:
        return value.astimezone(CLINIC_TZ).isoformat()


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    message: str
    subject_id: int
    created_at: datetime
    read_at: datetime | None

    @field_serializer("created_at", "read_at")
    def clinic_time(self, value: datetime | None) -> str | None:
        return value.astimezone(CLINIC_TZ).isoformat() if value is not None else None
