from datetime import date, datetime, time, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.database import CLINIC_TZ
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import AccessToken, Appointment, Doctor, Specialty, User
from app.schemas.directory import AppointmentCounts, DoctorCreated, DoctorView, StatisticsView


def list_specialties(session: Session) -> list[Specialty]:
    statement = select(Specialty).order_by(func.lower(Specialty.name), Specialty.id)
    return list(session.scalars(statement))


def _get_specialty(session: Session, specialty_id: int) -> Specialty:
    specialty = session.get(Specialty, specialty_id)
    if specialty is None:
        raise DomainError(404, "specialty_not_found", "Specialty not found.")
    return specialty


def _check_specialty_name(session: Session, name: str, exclude_id: int | None = None) -> None:
    statement = select(Specialty.id).where(func.lower(Specialty.name) == func.lower(name))
    if exclude_id is not None:
        statement = statement.where(Specialty.id != exclude_id)
    if session.scalar(statement.limit(1)) is not None:
        raise DomainError(409, "specialty_name_taken", "A specialty with that name already exists.")


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


def _get_doctor(session: Session, doctor_id: int, *, for_update: bool = False) -> Doctor:
    statement = select(Doctor).where(Doctor.id == doctor_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    doctor = session.scalar(statement)
    if doctor is None:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return doctor


def _doctor_view(doctor: Doctor) -> DoctorView:
    return DoctorView(
        id=doctor.id,
        name=doctor.user.name,
        specialty_id=doctor.specialty_id,
        specialty_name=doctor.specialty.name,
        is_active=doctor.is_active,
    )


def list_doctors(session: Session, specialty_id: int | None, query: str | None) -> list[DoctorView]:
    if specialty_id is not None:
        _get_specialty(session, specialty_id)
    statement = (
        select(Doctor)
        .join(Doctor.user)
        .join(Doctor.specialty)
        .options(joinedload(Doctor.user), joinedload(Doctor.specialty))
        .where(Doctor.is_active.is_(True))
        .order_by(func.lower(User.name), Doctor.id)
    )
    if specialty_id is not None:
        statement = statement.where(Doctor.specialty_id == specialty_id)
    if query is not None:
        normalized_query = query.strip().lower()
        statement = statement.where(
            or_(
                func.lower(User.name).contains(normalized_query, autoescape=True),
                func.lower(Specialty.name).contains(normalized_query, autoescape=True),
            )
        )
    return [_doctor_view(doctor) for doctor in session.scalars(statement)]


def get_public_doctor(session: Session, doctor_id: int) -> DoctorView:
    doctor = _get_doctor(session, doctor_id)
    if not doctor.is_active:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return _doctor_view(doctor)


def create_doctor(session: Session, name: str, specialty_id: int) -> DoctorCreated:
    specialty = _get_specialty(session, specialty_id)
    user = User(name=name, role=Role.DOCTOR)
    session.add(user)
    session.flush()
    doctor = Doctor(id=user.id, user=user, specialty=specialty, is_active=True)
    access_token = token_urlsafe(32)
    token = AccessToken(token_hash=sha256(access_token.encode()).hexdigest(), user_id=user.id)
    session.add_all([doctor, token])
    session.flush()
    return DoctorCreated(**_doctor_view(doctor).model_dump(), access_token=access_token)


def set_doctor_status(session: Session, doctor_id: int, is_active: bool) -> DoctorView:
    doctor = _get_doctor(session, doctor_id, for_update=True)
    doctor.is_active = is_active
    session.flush()
    return _doctor_view(doctor)


def get_statistics(
    session: Session, start_date: date | None, end_date: date | None
) -> StatisticsView:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise DomainError(422, "invalid_date_range", "start_date must be on or before end_date.")

    statement = select(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status)
    if start_date is not None:
        start = datetime.combine(start_date, time.min, CLINIC_TZ)
        statement = statement.where(Appointment.starts_at >= start)
    if end_date == date.max:
        end = datetime.combine(end_date, time.max, CLINIC_TZ)
        statement = statement.where(Appointment.starts_at <= end)
    elif end_date is not None:
        end_exclusive = datetime.combine(end_date + timedelta(days=1), time.min, CLINIC_TZ)
        statement = statement.where(Appointment.starts_at < end_exclusive)
    counts = dict(session.execute(statement).all())
    total_doctors, active_doctors = session.execute(
        select(func.count(Doctor.id), func.count(Doctor.id).filter(Doctor.is_active.is_(True)))
    ).one()
    total_specialties = session.scalar(select(func.count(Specialty.id)))
    return StatisticsView(
        start_date=start_date,
        end_date=end_date,
        total_doctors=total_doctors,
        active_doctors=active_doctors,
        blocked_doctors=total_doctors - active_doctors,
        total_specialties=total_specialties,
        total_appointments=sum(counts.values()),
        appointments_by_status=AppointmentCounts(
            booked=counts.get(AppointmentStatus.BOOKED, 0),
            cancelled=counts.get(AppointmentStatus.CANCELLED, 0),
            done=counts.get(AppointmentStatus.DONE, 0),
        ),
    )
