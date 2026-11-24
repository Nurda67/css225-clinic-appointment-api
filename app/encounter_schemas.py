from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import RequestBody


class IntakeInput(RequestBody):
    reason: str = Field(min_length=1, max_length=500)
    questions: str = Field(default="", max_length=1000)


class IntakeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    reason: str
    questions: str


class AttendanceInput(RequestBody):
    status: Literal["arrived", "no_show"]


class FollowUpInput(RequestBody):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_range(self) -> "FollowUpInput":
        if self.end_date < self.start_date:
            raise ValueError("The end date must be on or after the start date.")
        return self


class FollowUpView(FollowUpInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_appointment_id: int
    doctor_id: int
    patient_id: int
    booked_appointment_id: int | None
