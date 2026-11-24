from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain import AppointmentStatus, Role


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(name)) >= 2", name="ck_users_name"),
        CheckConstraint(
            "(email IS NULL) = (password_hash IS NULL)", name="ck_users_credentials_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # Users created before Assignment 7 can activate their existing account.
    email: Mapped[str | None] = mapped_column(String(320))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            create_constraint=True,
            name="ck_users_role",
        ),
    )
    doctor: Mapped["Doctor | None"] = relationship(back_populates="user", uselist=False)
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="patient",
        foreign_keys="Appointment.patient_id",
    )
    tokens: Mapped[list["AccessToken"]] = relationship(back_populates="user")


Index(
    "uq_users_email_lower",
    func.lower(User.email),
    unique=True,
    postgresql_where=User.email.is_not(None),
)


class Specialty(Base):
    __tablename__ = "specialties"
    __table_args__ = (CheckConstraint("length(trim(name)) >= 2", name="ck_specialties_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    doctors: Mapped[list["Doctor"]] = relationship(
        back_populates="specialty",
        passive_deletes="all",
    )


Index("uq_specialties_name_lower", func.lower(Specialty.name), unique=True)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
        autoincrement=False,
    )
    specialty_id: Mapped[int] = mapped_column(
        ForeignKey("specialties.id", ondelete="RESTRICT"),
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    user: Mapped[User] = relationship(back_populates="doctor")
    specialty: Mapped[Specialty] = relationship(back_populates="doctors")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="doctor")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="doctor")
    days_off: Mapped[list["DayOff"]] = relationship(back_populates="doctor")


class AccessToken(Base):
    """Assignment 6 token records retained for migration rollback."""

    __tablename__ = "access_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    user: Mapped[User] = relationship(back_populates="tokens")


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedules_weekday"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 120", name="ck_schedules_slot_minutes"),
        CheckConstraint('"end" > start', name="ck_schedules_window"),
        CheckConstraint(
            'extract(second from start) = 0 AND extract(second from "end") = 0',
            name="ck_schedules_whole_minutes",
        ),
        CheckConstraint(
            '(extract(epoch from ("end" - start))::numeric % (slot_minutes * 60)) = 0',
            name="ck_schedules_divisible",
        ),
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, primary_key=True)
    start: Mapped[time] = mapped_column(Time(timezone=False))
    end: Mapped[time] = mapped_column(Time(timezone=False))
    slot_minutes: Mapped[int] = mapped_column(Integer)
    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class DayOff(Base):
    __tablename__ = "days_off"

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    closed_for_replacement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    doctor: Mapped[Doctor] = relationship(back_populates="days_off")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_appointments_window"),
        UniqueConstraint("previous_appointment_id", name="uq_appointments_previous"),
        Index(
            "uq_appointments_active_slot",
            "doctor_id",
            "starts_at",
            unique=True,
            postgresql_where=text("status != 'cancelled'"),
        ),
        Index("ix_appointments_patient_starts", "patient_id", "starts_at"),
        Index("ix_appointments_doctor_starts", "doctor_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", name="fk_appointments_previous", ondelete="RESTRICT")
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            create_constraint=True,
            name="ck_appointments_status",
        ),
        default=AppointmentStatus.BOOKED,
        server_default="booked",
    )
    doctor: Mapped[Doctor] = relationship(back_populates="appointments")
    patient: Mapped[User] = relationship(back_populates="appointments", foreign_keys=[patient_id])
    medical_record: Mapped["MedicalRecord | None"] = relationship(
        back_populates="appointment",
        uselist=False,
    )


class MedicalRecord(Base):
    __tablename__ = "medical_records"
    __table_args__ = (
        CheckConstraint(
            "length(trim(diagnosis)) >= 1",
            name="ck_medical_records_diagnosis",
        ),
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        primary_key=True,
        autoincrement=False,
    )
    diagnosis: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    appointment: Mapped[Appointment] = relationship(back_populates="medical_record")

    @property
    def doctor_id(self) -> int:
        return self.appointment.doctor_id

    @property
    def patient_id(self) -> int:
        return self.appointment.patient_id
