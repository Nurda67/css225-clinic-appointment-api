from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.database import CLINIC_TZ
from app.schemas import RequestBody


class ReviewInput(RequestBody):
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class ReviewView(BaseModel):
    id: int
    appointment_id: int
    doctor_id: int
    rating: int
    comment: str
    status: Literal["pending", "published"]


class PublicReview(BaseModel):
    rating: int
    comment: str
    published_at: datetime


class DoctorReviews(BaseModel):
    doctor_id: int
    average_rating: float | None
    review_count: int
    reviews: list[PublicReview]


class CertificateView(BaseModel):
    appointment_id: int
    patient_name: str
    doctor_name: str
    starts_at: datetime
    status: Literal["pending", "approved"]

    @field_serializer("starts_at")
    def serialize_clinic_time(self, value: datetime) -> str:
        return value.astimezone(CLINIC_TZ).isoformat()
