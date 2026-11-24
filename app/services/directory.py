from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import CLINIC_TZ
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import Appointment, Doctor, Specialty, User
from app.services.accounts import create_user
from app.services.schedule import get_doctor as find_doctor


def list_specialties(session: Session) -> list[Specialty]:
    query = select(Specialty).order_by(func.lower(Specialty.name), Specialty.id)
    return list(session.scalars(query))


def create_specialty(session: Session, name: str) -> Specialty:
    _check_specialty_name(session, name)
    specialty = Specialty(name=name)
    session.add(specialty)
    session.flush()
    return specialty


def rename_specialty(session: Session, specialty_id: int, name: str) -> Specialty:
    specialty = _get_specialty(session, specialty_id)
    _check_specialty_name(session, name, exclude_id=specialty_id)
    specialty.name = name
    session.flush()
    return specialty


def delete_specialty(session: Session, specialty_id: int) -> None:
    specialty = _get_specialty(session, specialty_id)
    assigned_doctor = select(Doctor.id).where(Doctor.specialty_id == specialty_id).limit(1)
    if session.scalar(assigned_doctor) is not None:
        raise DomainError(409, "specialty_in_use", "A doctor is assigned to this specialty.")
    session.delete(specialty)
    session.flush()


def list_doctors(
    session: Session, specialty_id: int | None, q: str | None
) -> list[dict[str, object]]:
    query = (
        select(
            Doctor.id,
            User.name,
            Doctor.specialty_id,
            Specialty.name.label("specialty_name"),
            Doctor.is_active,
        )
        .join(Doctor.user)
        .join(Doctor.specialty)
        .where(Doctor.is_active.is_(True))
        .order_by(func.lower(User.name), Doctor.id)
    )
    if specialty_id is not None:
        _get_specialty(session, specialty_id)
        query = query.where(Doctor.specialty_id == specialty_id)
    if q is not None:
        search = q.strip().lower()
        # Treat % and _ as ordinary characters in user searches.
        query = query.where(
            or_(
                func.lower(User.name).contains(search, autoescape=True),
                func.lower(Specialty.name).contains(search, autoescape=True),
            )
        )
    return [dict(row) for row in session.execute(query).mappings()]


def get_doctor(session: Session, doctor_id: int) -> dict[str, object]:
    doctor = find_doctor(session, doctor_id)
    if not doctor.is_active:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return _doctor_data(doctor)


def create_doctor(
    session: Session, name: str, specialty_id: int, email: str, password: str
) -> dict[str, object]:
    specialty = _get_specialty(session, specialty_id)
    user = create_user(session, name, email, password, Role.DOCTOR)
    doctor = Doctor(id=user.id, user=user, specialty=specialty, is_active=True)
    session.add(doctor)
    session.flush()
    return _doctor_data(doctor)


def update_doctor_status(session: Session, doctor_id: int, is_active: bool) -> dict[str, object]:
    doctor = find_doctor(session, doctor_id, lock=True)
    doctor.is_active = is_active
    session.flush()
    return _doctor_data(doctor)


def get_statistics(
    session: Session, start_date: date | None, end_date: date | None
) -> dict[str, object]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise DomainError(422, "invalid_date_range", "start_date must be on or before end_date.")

    query = select(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status)
    if start_date is not None:
        start = datetime.combine(start_date, time.min, CLINIC_TZ)
        query = query.where(Appointment.starts_at >= start)
    if end_date is not None:
        end = datetime.combine(end_date, time.max, CLINIC_TZ)
        query = query.where(Appointment.starts_at <= end)

    counts = dict(session.execute(query).all())
    doctor_counts = select(
        func.count(Doctor.id),
        func.count(Doctor.id).filter(Doctor.is_active.is_(True)),
    )
    total_doctors, active_doctors = session.execute(doctor_counts).one()
    total_specialties = session.scalar(select(func.count(Specialty.id)))
    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_doctors": total_doctors,
        "active_doctors": active_doctors,
        "blocked_doctors": total_doctors - active_doctors,
        "total_specialties": total_specialties,
        "total_appointments": sum(counts.values()),
        "appointments_by_status": {
            "booked": counts.get(AppointmentStatus.BOOKED, 0),
            "cancelled": counts.get(AppointmentStatus.CANCELLED, 0),
            "done": counts.get(AppointmentStatus.DONE, 0),
            "no_show": counts.get(AppointmentStatus.NO_SHOW, 0),
        },
    }


def _get_specialty(session: Session, specialty_id: int) -> Specialty:
    specialty = session.get(Specialty, specialty_id)
    if specialty is None:
        raise DomainError(404, "specialty_not_found", "Specialty not found.")
    return specialty


def _check_specialty_name(session: Session, name: str, *, exclude_id: int | None = None) -> None:
    query = select(Specialty.id).where(func.lower(Specialty.name) == func.lower(name))
    if exclude_id is not None:
        query = query.where(Specialty.id != exclude_id)
    if session.scalar(query.limit(1)) is not None:
        raise DomainError(409, "specialty_name_taken", "A specialty with that name already exists.")


def _doctor_data(doctor: Doctor) -> dict[str, object]:
    return {
        "id": doctor.id,
        "name": doctor.user.name,
        "specialty_id": doctor.specialty_id,
        "specialty_name": doctor.specialty.name,
        "is_active": doctor.is_active,
    }
