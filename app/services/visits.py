from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import Appointment, DayOff, Doctor, MedicalRecord, Schedule, User
from app.services import waitlist
from app.services.schedule import ensure_shift_open, get_doctor, schedule_slots
from app.workflow_models import ReplacementOffer


def lock_patient(session: Session, patient_id: int) -> None:
    # A no-key lock excludes a second booking while permitting notification foreign keys.
    patient = session.get(
        User, patient_id, with_for_update={"key_share": True}, populate_existing=True
    )
    if patient is None or patient.role != Role.PATIENT:
        raise DomainError(404, "patient_not_found", "Patient not found.")


def get_booking_slot(
    session: Session, doctor: Doctor, starts_at: datetime
) -> tuple[datetime, datetime]:
    try:
        start = starts_at.astimezone(CLINIC_TZ)
    except OverflowError as error:
        raise DomainError(
            422, "invalid_timestamp", "Timestamp is outside the clinic calendar."
        ) from error

    if not doctor.is_active:
        raise DomainError(409, "doctor_inactive", "This doctor is not accepting appointments.")
    if start <= now(session):
        raise DomainError(409, "past_slot", "The appointment must start in the future.")

    day = start.date()
    schedule = session.get(Schedule, (doctor.id, day.weekday()), populate_existing=True)
    day_off = session.get(DayOff, (doctor.id, day), populate_existing=True)
    if schedule is None or day_off is not None:
        raise DomainError(409, "doctor_unavailable", "The doctor does not work on this date.")

    for slot_start, slot_end in schedule_slots(schedule, day):
        if slot_start == start:
            return slot_start, slot_end
    raise DomainError(409, "invalid_slot", "The start time does not match the doctor's schedule.")


def ensure_slot_free(
    session: Session,
    patient_id: int,
    doctor_id: int,
    start: datetime,
    end: datetime,
    *,
    exclude_appointment_id: int | None = None,
) -> None:
    # Two appointments can share a boundary, so compare overlapping ranges.
    query = select(Appointment.doctor_id).where(
        Appointment.status != AppointmentStatus.CANCELLED,
        Appointment.starts_at < end,
        Appointment.ends_at > start,
        or_(Appointment.doctor_id == doctor_id, Appointment.patient_id == patient_id),
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    conflicting_doctors = session.scalars(query).all()
    if doctor_id in conflicting_doctors:
        raise DomainError(409, "slot_taken", "This slot has already been booked.")
    if conflicting_doctors:
        raise DomainError(409, "patient_conflict", "You already have a visit during this time.")


def _book_locked(
    session: Session,
    patient_id: int,
    doctor: Doctor,
    starts_at: datetime,
    *,
    waitlist_entry_id: int | None = None,
) -> Appointment:
    start, end = get_booking_slot(session, doctor, starts_at)
    ensure_slot_free(session, patient_id, doctor.id, start, end)
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_id,
        starts_at=start,
        ends_at=end,
        status=AppointmentStatus.BOOKED,
    )
    session.add(appointment)
    session.flush()
    waitlist.expire_slot_offers(session, doctor.id, start, accepted_entry_id=waitlist_entry_id)
    return appointment


def book_appointment(
    session: Session, patient_id: int, doctor_id: int, starts_at: datetime
) -> Appointment:
    lock_patient(session, patient_id)
    doctor = get_doctor(session, doctor_id, lock=True)
    return _book_locked(session, patient_id, doctor, starts_at)


def accept_waitlist_offer(session: Session, patient_id: int, entry_id: int) -> Appointment:
    entry = waitlist.get_patient_entry(session, patient_id, entry_id)
    lock_patient(session, patient_id)
    doctor = get_doctor(session, entry.doctor_id, lock=True)
    session.refresh(entry, with_for_update=True)
    if (
        entry.status != "offered"
        or entry.offered_start is None
        or entry.offered_start <= now(session)
    ):
        raise DomainError(409, "offer_unavailable", "This waitlist offer is no longer available.")
    appointment = _book_locked(
        session, patient_id, doctor, entry.offered_start, waitlist_entry_id=entry.id
    )
    entry.status = "booked"
    entry.appointment_id = appointment.id
    session.flush()
    return appointment


def list_appointments(
    session: Session, user: User, status: AppointmentStatus | None
) -> list[Appointment]:
    query = select(Appointment)
    if user.role == Role.PATIENT:
        query = query.where(Appointment.patient_id == user.id)
    else:
        query = query.where(Appointment.doctor_id == user.id)
    if status is not None:
        query = query.where(Appointment.status == status)
    query = query.order_by(Appointment.starts_at, Appointment.id)
    return list(session.scalars(query))


def lock_appointment(
    session: Session, appointment_id: int, *, additional_doctor_id: int | None = None
) -> Appointment:
    query = select(Appointment.doctor_id).where(Appointment.id == appointment_id)
    doctor_id = session.scalar(query)
    if doctor_id is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")

    # A substitution locks both doctors in ID order before locking the visit.
    doctor_ids = {doctor_id}
    if additional_doctor_id is not None:
        doctor_ids.add(additional_doctor_id)
    for locked_id in sorted(doctor_ids):
        get_doctor(session, locked_id, lock=True)
    appointment = session.get(
        Appointment, appointment_id, with_for_update=True, populate_existing=True
    )
    if appointment is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")
    if appointment.doctor_id != doctor_id:
        raise DomainError(409, "appointment_changed", "The appointment changed. Reload and try again.")
    return appointment


def expire_replacement_offers(session: Session, appointment_id: int) -> None:
    session.execute(
        update(ReplacementOffer)
        .where(
            ReplacementOffer.appointment_id == appointment_id,
            ReplacementOffer.status == "pending",
        )
        .values(status="stale")
    )


def cancel_appointment(
    session: Session, patient_id: int, appointment_id: int
) -> Appointment:
    lock_patient(session, patient_id)
    appointment = lock_appointment(session, appointment_id)
    if appointment.patient_id != patient_id:
        raise DomainError(403, "appointment_forbidden", "You can only cancel your own visits.")
    if appointment.status != AppointmentStatus.BOOKED or appointment.starts_at <= now(session):
        raise DomainError(409, "cannot_cancel", "Only future booked visits can be cancelled.")
    appointment.status = AppointmentStatus.CANCELLED
    session.flush()
    expire_replacement_offers(session, appointment.id)
    waitlist.offer_released_slot(
        session, appointment.doctor_id, patient_id, appointment.starts_at, appointment.ends_at
    )
    return appointment


def reschedule_appointment(
    session: Session, patient_id: int, appointment_id: int, starts_at: datetime
) -> Appointment:
    lock_patient(session, patient_id)
    appointment = lock_appointment(session, appointment_id)
    if appointment.patient_id != patient_id:
        raise DomainError(403, "appointment_forbidden", "You can only reschedule your own visits.")
    if appointment.status != AppointmentStatus.BOOKED or appointment.starts_at <= now(session):
        raise DomainError(409, "cannot_reschedule", "Only future booked visits can be rescheduled.")

    doctor = get_doctor(session, appointment.doctor_id)
    start, end = get_booking_slot(session, doctor, starts_at)
    if start == appointment.starts_at:
        raise DomainError(409, "same_slot", "Choose a different start time.")
    ensure_slot_free(session, patient_id, doctor.id, start, end, exclude_appointment_id=appointment.id)
    old_start, old_end = appointment.starts_at, appointment.ends_at
    appointment.starts_at, appointment.ends_at = start, end
    session.flush()
    expire_replacement_offers(session, appointment.id)
    waitlist.expire_slot_offers(session, doctor.id, start)
    waitlist.offer_released_slot(session, doctor.id, patient_id, old_start, old_end)
    return appointment


def create_medical_record(
    session: Session, doctor_id: int, appointment_id: int, diagnosis: str, notes: str
) -> MedicalRecord:
    appointment = lock_appointment(session, appointment_id)
    if appointment.doctor_id != doctor_id:
        raise DomainError(
            403, "appointment_forbidden", "Only the assigned doctor can record the result."
        )
    if appointment.status != AppointmentStatus.BOOKED:
        raise DomainError(409, "cannot_complete", "Only a booked visit can be completed.")
    current_time = now(session)
    if appointment.starts_at > current_time:
        raise DomainError(409, "visit_not_started", "The visit has not started yet.")

    ensure_shift_open(session, appointment)
    record = MedicalRecord(
        appointment=appointment,
        diagnosis=diagnosis,
        notes=notes,
        created_at=current_time,
    )
    session.add(record)
    if appointment.arrived_at is None:
        appointment.arrived_at = current_time
    appointment.status = AppointmentStatus.DONE
    session.flush()
    return record


def medical_history(session: Session, user: User, patient_id: int) -> list[MedicalRecord]:
    if user.role == Role.PATIENT and user.id != patient_id:
        raise DomainError(403, "history_forbidden", "You can only view your own history.")
    patient = session.get(User, patient_id)
    if patient is None or patient.role != Role.PATIENT:
        raise DomainError(404, "patient_not_found", "Patient not found.")

    if user.role == Role.DOCTOR:
        visit_query = select(Appointment.id).where(
            Appointment.patient_id == patient_id, Appointment.doctor_id == user.id
        )
        if session.scalar(visit_query.limit(1)) is None:
            raise DomainError(403, "history_forbidden", "This patient has no visits with you.")

    query = (
        select(MedicalRecord)
        .join(MedicalRecord.appointment)
        .options(joinedload(MedicalRecord.appointment))
        .where(Appointment.patient_id == patient_id)
    )
    if user.role == Role.DOCTOR:
        query = query.where(Appointment.doctor_id == user.id)
    query = query.order_by(MedicalRecord.created_at.desc(), MedicalRecord.appointment_id.desc())
    return list(session.scalars(query))
