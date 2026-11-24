from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus
from app.errors import DomainError
from app.models import Appointment, DayOff, Schedule
from app.services.notifications import notify
from app.services.schedule import available_slots, get_doctor, schedule_slots
from app.workflow_models import WaitlistEntry


def join_waitlist(session: Session, patient_id: int, doctor_id: int, day: date) -> WaitlistEntry:
    current_time = now(session)
    if day < current_time.date():
        raise DomainError(409, "past_date", "Choose today or a future date.")

    doctor = get_doctor(session, doctor_id, lock=True)
    if not doctor.is_active:
        raise DomainError(409, "doctor_inactive", "This doctor is not accepting appointments.")
    schedule = session.get(Schedule, (doctor_id, day.weekday()), populate_existing=True)
    day_off = session.get(DayOff, (doctor_id, day), populate_existing=True)
    if schedule is None or day_off is not None:
        raise DomainError(409, "doctor_unavailable", "The doctor does not work on this date.")
    if not any(start > current_time for start, _ in schedule_slots(schedule, day)):
        raise DomainError(409, "no_future_slots", "There are no future times on this date.")

    session.execute(
        update(WaitlistEntry)
        .where(
            WaitlistEntry.patient_id == patient_id,
            WaitlistEntry.doctor_id == doctor_id,
            WaitlistEntry.day == day,
            WaitlistEntry.status == "offered",
            WaitlistEntry.offered_start <= current_time,
        )
        .values(status="expired")
    )
    existing = session.scalar(
        select(WaitlistEntry.id).where(
            WaitlistEntry.patient_id == patient_id,
            WaitlistEntry.doctor_id == doctor_id,
            WaitlistEntry.day == day,
            WaitlistEntry.status.in_(("waiting", "offered")),
        )
    )
    if existing is not None:
        raise DomainError(409, "already_waiting", "You already joined this waitlist.")

    entry = WaitlistEntry(
        patient_id=patient_id,
        doctor_id=doctor_id,
        day=day,
        status="waiting",
        created_at=current_time,
    )
    session.add(entry)
    session.flush()
    return entry


def list_waitlist(session: Session, patient_id: int) -> list[WaitlistEntry]:
    query = (
        select(WaitlistEntry)
        .where(WaitlistEntry.patient_id == patient_id)
        .order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id.desc())
    )
    return list(session.scalars(query))


def get_patient_entry(session: Session, patient_id: int, entry_id: int) -> WaitlistEntry:
    entry = session.get(WaitlistEntry, entry_id)
    if entry is None:
        raise DomainError(404, "waitlist_entry_not_found", "Waitlist entry not found.")
    if entry.patient_id != patient_id:
        raise DomainError(403, "waitlist_forbidden", "You can only accept your own offers.")
    return entry


def offer_released_slot(
    session: Session, doctor_id: int, patient_id: int, starts_at: datetime, ends_at: datetime
) -> None:
    # The caller has already updated the appointment while holding the doctor's lock.
    start = starts_at.astimezone(CLINIC_TZ)
    if start <= now(session) or not get_doctor(session, doctor_id).is_active:
        return
    if (start, ends_at) not in available_slots(session, doctor_id, start.date()):
        return

    overlap = (
        select(Appointment.id)
        .where(
            Appointment.patient_id == WaitlistEntry.patient_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.starts_at < ends_at,
            Appointment.ends_at > start,
        )
        .exists()
    )
    query = (
        select(WaitlistEntry)
        .where(
            WaitlistEntry.doctor_id == doctor_id,
            WaitlistEntry.day == start.date(),
            WaitlistEntry.patient_id != patient_id,
            WaitlistEntry.status == "waiting",
            ~overlap,
        )
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
        .limit(1)
        .with_for_update()
    )
    entry = session.scalar(query)
    if entry is None:
        return

    entry.offered_start = start
    entry.status = "offered"
    message = f"A time opened on {start.date()} at {start:%H:%M} clinic time."
    notify(session, entry.patient_id, "waitlist_offer", message, entry.id)


def expire_slot_offers(
    session: Session, doctor_id: int, starts_at: datetime, *, accepted_entry_id: int | None = None
) -> None:
    statement = update(WaitlistEntry).where(
        WaitlistEntry.doctor_id == doctor_id,
        WaitlistEntry.offered_start == starts_at,
        WaitlistEntry.status == "offered",
    )
    if accepted_entry_id is not None:
        statement = statement.where(WaitlistEntry.id != accepted_entry_id)
    session.execute(statement.values(status="expired"))


def expire_day_offers(session: Session, doctor_id: int, day: date) -> None:
    session.execute(
        update(WaitlistEntry)
        .where(
            WaitlistEntry.doctor_id == doctor_id,
            WaitlistEntry.day == day,
            WaitlistEntry.status == "offered",
        )
        .values(status="expired")
    )
