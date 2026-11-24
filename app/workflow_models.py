from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import Appointment


class IntakeForm(Base):
    __tablename__ = "intake_forms"

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"), primary_key=True, autoincrement=False
    )
    reason: Mapped[str] = mapped_column(String(500))
    questions: Mapped[str] = mapped_column(String(1000))


class FollowUpRecommendation(Base):
    __tablename__ = "follow_up_recommendations"
    __table_args__ = (
        UniqueConstraint("original_appointment_id", name="uq_follow_ups_original"),
        UniqueConstraint("booked_appointment_id", name="uq_follow_ups_booking"),
        CheckConstraint("end_date >= start_date", name="ck_follow_up_date_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    original_appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT")
    )
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    booked_appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT")
    )


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'offered', 'booked', 'expired')", name="ck_waitlist_status"
        ),
        CheckConstraint(
            "status != 'offered' OR offered_start IS NOT NULL", name="ck_waitlist_offer"
        ),
        Index("ix_waitlist_doctor_day", "doctor_id", "day"),
        Index(
            "uq_waitlist_active", "patient_id", "doctor_id", "day", unique=True,
            postgresql_where=text("status IN ('waiting', 'offered')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="waiting", server_default="waiting")
    offered_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReplacementOffer(Base):
    __tablename__ = "replacement_offers"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'stale')", name="ck_replacement_status"),
        CheckConstraint("ends_at > starts_at", name="ck_replacement_window"),
        CheckConstraint(
            "replacement_doctor_id != original_doctor_id", name="ck_replacement_distinct_doctors"
        ),
        Index(
            "uq_pending_replacement", "appointment_id", unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"), index=True
    )
    original_doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    replacement_doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(240))
    subject_id: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("appointment_id", name="uq_review_appointment"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="RESTRICT"))
    rating: Mapped[int]
    comment: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment: Mapped[Appointment] = relationship()


class VisitCertificate(Base):
    __tablename__ = "visit_certificates"
    __table_args__ = (
        CheckConstraint(
            "(approved_at IS NULL) = (approved_by IS NULL)", name="ck_certificate_approval"
        ),
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"), primary_key=True, autoincrement=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    appointment: Mapped[Appointment] = relationship()
