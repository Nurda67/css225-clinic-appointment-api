from collections.abc import Iterator
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import Appointment, DayOff, Doctor, MedicalRecord, Schedule, User


def _schedule_slots(
    schedule: Schedule, day: date
) -> Iterator[tuple[datetime, datetime]]:
    start = datetime.combine(day, schedule.start, CLINIC_TZ)
    end = datetime.combine(day, schedule.end, CLINIC_TZ)
    step = timedelta(minutes=schedule.slot_minutes)
    while start < end:
        slot_end = start + step
        yield start, slot_end
        start = slot_end


def _doctor(session: Session, doctor_id: int, *, lock: bool = False) -> Doctor:
    query = select(Doctor).where(Doctor.id == doctor_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    doctor = session.scalar(query)
    if doctor is None:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return doctor


def available_slots(
    session: Session, doctor_id: int, day: date
) -> list[tuple[datetime, datetime]]:
    doctor = _doctor(session, doctor_id)
    if not doctor.is_active:
        raise DomainError(404, "doctor_not_found", "Active doctor not found.")
    schedule = session.get(Schedule, (doctor_id, day.weekday()))
    current_time = now(session)
    day_off = session.get(DayOff, (doctor_id, day))
    if schedule is None or day < current_time.date() or day_off is not None:
        return []

    opening = datetime.combine(day, schedule.start, CLINIC_TZ)
    closing = datetime.combine(day, schedule.end, CLINIC_TZ)
    reservations = session.scalars(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.starts_at < closing,
            Appointment.ends_at > opening,
        )
    ).all()
    return [
        (start, end)
        for start, end in _schedule_slots(schedule, day)
        if start > current_time
        and not any(
            appointment.starts_at < end and start < appointment.ends_at
            for appointment in reservations
        )
    ]


def doctor_schedule(
    session: Session, doctor_id: int
) -> tuple[list[tuple[int, Schedule]], list[date]]:
    schedule = session.scalars(
        select(Schedule)
        .where(Schedule.doctor_id == doctor_id)
        .order_by(Schedule.weekday)
    ).all()
    days_off = session.scalars(
        select(DayOff.date)
        .where(DayOff.doctor_id == doctor_id)
        .order_by(DayOff.date)
    ).all()
    return [(hours.weekday, hours) for hours in schedule], list(days_off)


def _upcoming_bookings(session: Session, doctor_id: int) -> list[Appointment]:
    query = select(Appointment).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.starts_at > now(session),
    )
    return list(session.scalars(query))


def set_working_hours(
    session: Session, doctor_id: int, weekday: int, schedule: Schedule
) -> None:
    _doctor(session, doctor_id, lock=True)
    for appointment in _upcoming_bookings(session, doctor_id):
        day = appointment.starts_at.astimezone(CLINIC_TZ).date()
        if day.weekday() != weekday:
            continue
        reserved_slot = (appointment.starts_at, appointment.ends_at)
        if reserved_slot not in _schedule_slots(schedule, day):
            raise DomainError(
                409,
                "schedule_conflict",
                "These working hours would change an existing booked visit.",
            )

    existing = session.get(Schedule, (doctor_id, weekday), populate_existing=True)
    if existing is None:
        schedule.doctor_id = doctor_id
        schedule.weekday = weekday
        session.add(schedule)
    else:
        existing.start = schedule.start
        existing.end = schedule.end
        existing.slot_minutes = schedule.slot_minutes
    session.flush()


def add_day_off(session: Session, doctor_id: int, day: date) -> None:
    _doctor(session, doctor_id, lock=True)
    if day < now(session).date():
        raise DomainError(409, "past_date", "A day off cannot be added in the past.")
    if session.get(DayOff, (doctor_id, day), populate_existing=True) is not None:
        raise DomainError(409, "day_off_exists", "This day off is already recorded.")
    if any(
        appointment.starts_at.astimezone(CLINIC_TZ).date() == day
        for appointment in _upcoming_bookings(session, doctor_id)
    ):
        raise DomainError(
            409, "day_off_conflict", "There are already booked visits on this date."
        )
    session.add(DayOff(doctor_id=doctor_id, date=day))
    session.flush()


def remove_day_off(session: Session, doctor_id: int, day: date) -> None:
    _doctor(session, doctor_id, lock=True)
    day_off = session.get(DayOff, (doctor_id, day), populate_existing=True)
    if day_off is None:
        raise DomainError(404, "day_off_not_found", "Day off not found.")
    session.delete(day_off)
    session.flush()


def book_appointment(
    session: Session, patient_id: int, doctor_id: int, start: datetime
) -> Appointment:
    try:
        start = start.astimezone(CLINIC_TZ)
    except OverflowError as error:
        raise DomainError(
            422, "invalid_timestamp", "Timestamp is outside the clinic calendar."
        ) from error

    # The patient lock also serializes overlapping bookings with different doctors.
    patient = session.scalar(
        select(User).where(User.id == patient_id).with_for_update()
    )
    if patient is None or patient.role != Role.PATIENT:
        raise DomainError(404, "patient_not_found", "Patient not found.")
    doctor = _doctor(session, doctor_id, lock=True)
    if not doctor.is_active:
        raise DomainError(409, "doctor_inactive", "This doctor is not accepting appointments.")
    if start <= now(session):
        raise DomainError(409, "past_slot", "The appointment must start in the future.")

    day = start.date()
    schedule = session.get(Schedule, (doctor_id, day.weekday()), populate_existing=True)
    day_off = session.get(DayOff, (doctor_id, day), populate_existing=True)
    if schedule is None or day_off is not None:
        raise DomainError(409, "doctor_unavailable", "The doctor does not work on this date.")
    end = next(
        (slot_end for slot_start, slot_end in _schedule_slots(schedule, day) if slot_start == start),
        None,
    )
    if end is None:
        raise DomainError(409, "invalid_slot", "The start time does not match the doctor's schedule.")

    conflicts = session.scalars(
        select(Appointment).where(
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.starts_at < end,
            Appointment.ends_at > start,
            or_(
                Appointment.doctor_id == doctor_id,
                Appointment.patient_id == patient_id,
            ),
        ).execution_options(populate_existing=True)
    ).all()
    if any(appointment.doctor_id == doctor_id for appointment in conflicts):
        raise DomainError(409, "slot_taken", "This slot has already been booked.")
    if conflicts:
        raise DomainError(409, "patient_conflict", "You already have a visit during this time.")
    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        starts_at=start,
        ends_at=end,
        status=AppointmentStatus.BOOKED,
    )
    session.add(appointment)
    session.flush()
    return appointment


def list_appointments(
    session: Session, user: User, status: AppointmentStatus | None
) -> list[Appointment]:
    owner = Appointment.patient_id if user.role == Role.PATIENT else Appointment.doctor_id
    query = select(Appointment).where(owner == user.id)
    if status is not None:
        query = query.where(Appointment.status == status)
    return list(session.scalars(query.order_by(Appointment.starts_at, Appointment.id)))


def _locked_appointment(session: Session, appointment_id: int) -> Appointment:
    doctor_id = session.scalar(
        select(Appointment.doctor_id).where(Appointment.id == appointment_id)
    )
    if doctor_id is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")
    # Visit changes follow doctor -> appointment order, matching schedule changes.
    _doctor(session, doctor_id, lock=True)
    appointment = session.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if appointment is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")
    return appointment


def cancel_appointment(
    session: Session, patient_id: int, appointment_id: int
) -> Appointment:
    appointment = _locked_appointment(session, appointment_id)
    if appointment.patient_id != patient_id:
        raise DomainError(403, "appointment_forbidden", "You can only cancel your own visits.")
    if appointment.status != AppointmentStatus.BOOKED or appointment.starts_at <= now(session):
        raise DomainError(409, "cannot_cancel", "Only future booked visits can be cancelled.")
    appointment.status = AppointmentStatus.CANCELLED
    session.flush()
    return appointment


def create_medical_record(
    session: Session, doctor_id: int, appointment_id: int, diagnosis: str, notes: str
) -> MedicalRecord:
    appointment = _locked_appointment(session, appointment_id)
    if appointment.doctor_id != doctor_id:
        raise DomainError(
            403, "appointment_forbidden", "Only the assigned doctor can record the result."
        )
    if appointment.status != AppointmentStatus.BOOKED:
        raise DomainError(409, "cannot_complete", "Only a booked visit can be completed.")
    current_time = now(session)
    if appointment.starts_at > current_time:
        raise DomainError(409, "visit_not_started", "The visit has not started yet.")
    record = MedicalRecord(
        appointment=appointment,
        diagnosis=diagnosis,
        notes=notes,
        created_at=current_time,
    )
    session.add(record)
    appointment.status = AppointmentStatus.DONE
    session.flush()
    return record


def medical_history(
    session: Session, user: User, patient_id: int
) -> list[MedicalRecord]:
    if user.role == Role.PATIENT and user.id != patient_id:
        raise DomainError(403, "history_forbidden", "You can only view your own history.")
    patient = session.get(User, patient_id)
    if patient is None or patient.role != Role.PATIENT:
        raise DomainError(404, "patient_not_found", "Patient not found.")
    if user.role == Role.DOCTOR:
        relationship = session.scalar(
            select(Appointment.id)
            .where(Appointment.patient_id == patient_id, Appointment.doctor_id == user.id)
            .limit(1)
        )
        if relationship is None:
            raise DomainError(403, "history_forbidden", "This patient has no visits with you.")
    query = (
        select(MedicalRecord)
        .join(MedicalRecord.appointment)
        .options(joinedload(MedicalRecord.appointment))
        .where(Appointment.patient_id == patient_id)
    )
    if user.role == Role.DOCTOR:
        query = query.where(Appointment.doctor_id == user.id)
    return list(session.scalars(
        query.order_by(MedicalRecord.created_at.desc(), MedicalRecord.appointment_id.desc())
    ))
