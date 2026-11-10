from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum


class Role(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    role: Role


@dataclass(frozen=True, slots=True)
class Specialty:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Doctor:
    id: int
    specialty_id: int
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class Schedule:
    start: time
    end: time
    slot_minutes: int


@dataclass(frozen=True, slots=True)
class Appointment:
    id: int
    doctor_id: int
    patient_id: int
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus = AppointmentStatus.BOOKED


@dataclass(frozen=True, slots=True)
class MedicalRecord:
    appointment_id: int
    doctor_id: int
    patient_id: int
    diagnosis: str
    notes: str
    created_at: datetime
