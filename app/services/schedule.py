from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus
from app.errors import DomainError
from app.models import Appointment, DayOff, Doctor, Schedule


def get_doctor(session: Session, doctor_id: int, *, lock: bool = False) -> Doctor:
    # Calendar changes share this row lock until the request commits.
    doctor = session.get(Doctor, doctor_id, with_for_update=lock, populate_existing=lock)
    if doctor is None:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return doctor


def schedule_slots(schedule: Schedule, day: date) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, schedule.start, CLINIC_TZ)
    closing_time = datetime.combine(day, schedule.end, CLINIC_TZ)
    duration = timedelta(minutes=schedule.slot_minutes)
    slots = []
    while start < closing_time:
        end = start + duration
        slots.append((start, end))
        start = end
    return slots


def available_slots(
    session: Session, doctor_id: int, day: date
) -> list[tuple[datetime, datetime]]:
    doctor = get_doctor(session, doctor_id)
    if not doctor.is_active:
        raise DomainError(404, "doctor_not_found", "Active doctor not found.")

    current_time = now(session)
    hours = session.get(Schedule, (doctor_id, day.weekday()))
    if hours is None or day < current_time.date():
        return []
    if session.get(DayOff, (doctor_id, day)) is not None:
        return []

    opens_at = datetime.combine(day, hours.start, CLINIC_TZ)
    closes_at = datetime.combine(day, hours.end, CLINIC_TZ)
    query = select(Appointment).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status != AppointmentStatus.CANCELLED,
        Appointment.starts_at < closes_at,
        Appointment.ends_at > opens_at,
    )
    reservations = session.scalars(query).all()
    free_slots = []
    for start, end in schedule_slots(hours, day):
        if start <= current_time:
            continue
        is_reserved = any(
            appointment.starts_at < end and appointment.ends_at > start
            for appointment in reservations
        )
        if not is_reserved:
            free_slots.append((start, end))
    return free_slots


def get_schedule(session: Session, doctor_id: int) -> tuple[list[Schedule], list[date]]:
    hours_query = (
        select(Schedule)
        .where(Schedule.doctor_id == doctor_id)
        .order_by(Schedule.weekday)
    )
    days_off_query = select(DayOff.date).where(DayOff.doctor_id == doctor_id).order_by(DayOff.date)
    return list(session.scalars(hours_query)), list(session.scalars(days_off_query))


def _upcoming_bookings(session: Session, doctor_id: int) -> list[Appointment]:
    query = select(Appointment).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.BOOKED,
        Appointment.starts_at > now(session),
    )
    return list(session.scalars(query))


def set_working_hours(
    session: Session, doctor_id: int, weekday: int, start: time, end: time, slot_minutes: int
) -> Schedule:
    get_doctor(session, doctor_id, lock=True)
    new_hours = Schedule(
        doctor_id=doctor_id, weekday=weekday, start=start, end=end, slot_minutes=slot_minutes
    )
    for appointment in _upcoming_bookings(session, doctor_id):
        day = appointment.starts_at.astimezone(CLINIC_TZ).date()
        if day.weekday() != weekday:
            continue
        booked_slot = (appointment.starts_at, appointment.ends_at)
        if booked_slot not in schedule_slots(new_hours, day):
            raise DomainError(
                409, "schedule_conflict", "These working hours would change an existing booked visit."
            )

    hours = session.get(Schedule, (doctor_id, weekday), populate_existing=True)
    if hours is None:
        hours = new_hours
        session.add(hours)
    else:
        hours.start = start
        hours.end = end
        hours.slot_minutes = slot_minutes
    session.flush()
    return hours


def add_day_off(session: Session, doctor_id: int, day: date) -> None:
    get_doctor(session, doctor_id, lock=True)
    if day < now(session).date():
        raise DomainError(409, "past_date", "A day off cannot be added in the past.")
    if session.get(DayOff, (doctor_id, day), populate_existing=True) is not None:
        raise DomainError(409, "day_off_exists", "This day off is already recorded.")
    for appointment in _upcoming_bookings(session, doctor_id):
        if appointment.starts_at.astimezone(CLINIC_TZ).date() == day:
            raise DomainError(409, "day_off_conflict", "There are already booked visits on this date.")
    session.add(DayOff(doctor_id=doctor_id, date=day))
    session.flush()


def remove_day_off(session: Session, doctor_id: int, day: date) -> None:
    get_doctor(session, doctor_id, lock=True)
    day_off = session.get(DayOff, (doctor_id, day), populate_existing=True)
    if day_off is None:
        raise DomainError(404, "day_off_not_found", "Day off not found.")
    if day_off.closed_for_replacement:
        raise DomainError(409, "shift_closed", "This shift was closed by clinic staff.")
    session.delete(day_off)
    session.flush()


def ensure_shift_open(session: Session, appointment: Appointment) -> None:
    day = appointment.starts_at.astimezone(CLINIC_TZ).date()
    day_off = session.get(DayOff, (appointment.doctor_id, day))
    if day_off is not None and day_off.closed_for_replacement:
        raise DomainError(409, "shift_closed", "Clinic staff closed this shift.")
