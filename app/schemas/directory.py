from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class SpecialtyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class SpecialtyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DoctorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    specialty_id: Annotated[int, Field(gt=0, strict=True)]


class DoctorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool


class DoctorView(BaseModel):
    id: int
    name: str
    specialty_id: int
    specialty_name: str
    is_active: bool


class DoctorCreated(DoctorView):
    access_token: str = Field(description="Bearer token for the new doctor's account.")


class AppointmentCounts(BaseModel):
    booked: int
    cancelled: int
    done: int


class StatisticsView(BaseModel):
    start_date: date | None
    end_date: date | None
    total_doctors: int
    active_doctors: int
    blocked_doctors: int
    total_specialties: int
    total_appointments: int
    appointments_by_status: AppointmentCounts
