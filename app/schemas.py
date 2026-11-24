from datetime import date as Date, datetime, time
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StrictBool,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from app.database import CLINIC_TZ
from app.domain import AppointmentStatus, Role


Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=r"^[^\x00]*$")
]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def reject_null_characters(cls, value: object) -> object:
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("Text cannot contain a null character.")
        return value


def lowercase_email(value: object) -> object:
    if isinstance(value, str):
        return value.lower()
    return value


AccountEmail = Annotated[EmailStr, BeforeValidator(lowercase_email)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: AccountEmail
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_text(cls, value: SecretStr) -> SecretStr:
        try:
            value.get_secret_value().encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Password must be valid Unicode text.") from None
        return value


class RegistrationInput(LoginInput):
    name: Name
    password: SecretStr = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class SpecialtyWrite(RequestBody):
    name: Name


class SpecialtyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DoctorCreate(RegistrationInput):
    specialty_id: int = Field(gt=0, strict=True)


class DoctorUpdate(RequestBody):
    is_active: StrictBool


class DoctorView(BaseModel):
    id: int
    name: str
    specialty_id: int
    specialty_name: str
    is_active: bool


class AppointmentCounts(BaseModel):
    booked: int
    cancelled: int
    done: int
    no_show: int


class StatisticsView(BaseModel):
    start_date: Date | None
    end_date: Date | None
    total_doctors: int
    active_doctors: int
    blocked_doctors: int
    total_specialties: int
    total_appointments: int
    appointments_by_status: AppointmentCounts


class ScheduleInput(RequestBody):
    start: time = Field(examples=["09:00"])
    end: time = Field(examples=["17:00"])
    slot_minutes: int = Field(strict=True, ge=5, le=120, examples=[30])

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
    model_config = ConfigDict(from_attributes=True)

    weekday: int
    start: time
    end: time
    slot_minutes: int


class DoctorSchedule(BaseModel):
    schedule: list[ScheduleItem]
    days_off: list[Date]


class DayOffInput(RequestBody):
    date: Date


class SlotResponse(BaseModel):
    starts_at: datetime
    ends_at: datetime

    @field_serializer("starts_at", "ends_at")
    def serialize_clinic_time(self, value: datetime) -> str:
        return value.astimezone(CLINIC_TZ).isoformat()


class SlotChoice(RequestBody):
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


class AppointmentInput(SlotChoice):
    doctor_id: int = Field(strict=True, gt=0, examples=[3])


class AppointmentUpdate(RequestBody):
    status: Literal["cancelled"]


class AppointmentResponse(SlotResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    status: AppointmentStatus
    arrived_at: datetime | None = None
    previous_appointment_id: int | None = None

    @field_serializer("arrived_at")
    def serialize_arrival_time(self, value: datetime | None) -> str | None:
        return value.astimezone(CLINIC_TZ).isoformat() if value is not None else None


class MedicalRecordInput(RequestBody):
    diagnosis: str = Field(min_length=1, max_length=500)
    notes: str = Field(default="", max_length=2000)


class MedicalRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    doctor_id: int
    patient_id: int
    diagnosis: str
    notes: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_clinic_time(self, value: datetime) -> str:
        return value.astimezone(CLINIC_TZ).isoformat()
