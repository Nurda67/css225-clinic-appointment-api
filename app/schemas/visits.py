from datetime import date as Date, datetime, time
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain import AppointmentStatus


class VisitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScheduleInput(VisitRequest):
    start: time = Field(examples=["09:00"])
    end: time = Field(examples=["17:00"])
    slot_minutes: Annotated[int, Field(strict=True, ge=5, le=120)] = Field(
        examples=[30]
    )

    @field_validator("start", "end")
    @classmethod
    def whole_clinic_minute(cls, value: time) -> time:
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Use clinic-local times at whole minutes, such as 09:00.")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "ScheduleInput":
        start_minute = self.start.hour * 60 + self.start.minute
        end_minute = self.end.hour * 60 + self.end.minute
        duration = end_minute - start_minute
        if duration <= 0:
            raise ValueError("End time must be later than start time.")
        if duration % self.slot_minutes:
            raise ValueError("Working hours must divide evenly into slots.")
        return self


class ScheduleItem(BaseModel):
    weekday: int
    start: time
    end: time
    slot_minutes: int


class DoctorSchedule(BaseModel):
    schedule: list[ScheduleItem]
    days_off: list[Date]


class DayOffInput(VisitRequest):
    date: Date


class SlotResponse(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AppointmentInput(VisitRequest):
    doctor_id: Annotated[int, Field(strict=True, gt=0)] = Field(examples=[3])
    starts_at: AwareDatetime = Field(
        description="Copy a slot timestamp, including its UTC offset, from GET /doctors/{doctor_id}/slots."
    )

    @field_validator("starts_at", mode="before")
    @classmethod
    def require_iso_timestamp(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or "T" not in value.upper():
            raise ValueError("Use an ISO 8601 timestamp with a UTC offset.")
        return value


class AppointmentUpdate(VisitRequest):
    status: Literal["cancelled"]


class AppointmentResponse(SlotResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    status: AppointmentStatus


class MedicalRecordInput(VisitRequest):
    diagnosis: Annotated[str, Field(min_length=1, max_length=500)]
    notes: Annotated[str, Field(max_length=2000)] = ""


class MedicalRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    doctor_id: int
    patient_id: int
    diagnosis: str
    notes: str
    created_at: datetime
