from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, timedelta

from app.domain import (
    Appointment,
    AppointmentStatus,
    MedicalRecord,
    Role,
    Schedule,
    User,
)
from app.errors import DomainError
from app.store import CLINIC_TZ, Store


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


def _overlaps(appointment: Appointment, start: datetime, end: datetime) -> bool:
    return appointment.starts_at < end and start < appointment.ends_at


def available_slots(
    store: Store, doctor_id: int, day: date
) -> list[tuple[datetime, datetime]]:
    with store.lock:
        doctor = store.doctors.get(doctor_id)
        if doctor is None or not doctor.is_active:
            raise DomainError(404, "doctor_not_found", "Active doctor not found.")

        schedule = store.schedules.get((doctor_id, day.weekday()))
        now = store.now()
        if schedule is None or day < now.date() or (doctor_id, day) in store.days_off:
            return []

        reservations = [
            appointment
            for appointment in store.appointments.values()
            if appointment.doctor_id == doctor_id
            and appointment.status != AppointmentStatus.CANCELLED
            and appointment.starts_at.date() == day
        ]
        return [
            (start, end)
            for start, end in _schedule_slots(schedule, day)
            if start > now
            and not any(_overlaps(appointment, start, end) for appointment in reservations)
        ]


def doctor_schedule(
    store: Store, doctor_id: int
) -> tuple[list[tuple[int, Schedule]], list[date]]:
    with store.lock:
        schedule = sorted(
            (weekday, hours)
            for (owner, weekday), hours in store.schedules.items()
            if owner == doctor_id
        )
        days_off = sorted(day for owner, day in store.days_off if owner == doctor_id)
        return schedule, days_off


def _upcoming_bookings(store: Store, doctor_id: int) -> Iterator[Appointment]:
    now = store.now()
    return (
        appointment
        for appointment in store.appointments.values()
        if appointment.doctor_id == doctor_id
        and appointment.status == AppointmentStatus.BOOKED
        and appointment.starts_at > now
    )


def set_working_hours(
    store: Store, doctor_id: int, weekday: int, schedule: Schedule
) -> None:
    with store.lock:
        for appointment in _upcoming_bookings(store, doctor_id):
            day = appointment.starts_at.date()
            if day.weekday() != weekday:
                continue
            reserved_slot = (appointment.starts_at, appointment.ends_at)
            if reserved_slot not in _schedule_slots(schedule, day):
                raise DomainError(
                    409,
                    "schedule_conflict",
                    "These working hours would change an existing booked visit.",
                )
        store.schedules[doctor_id, weekday] = schedule


def add_day_off(store: Store, doctor_id: int, day: date) -> None:
    with store.lock:
        if day < store.now().date():
            raise DomainError(409, "past_date", "A day off cannot be added in the past.")
        if (doctor_id, day) in store.days_off:
            raise DomainError(409, "day_off_exists", "This day off is already recorded.")
        if any(
            appointment.starts_at.date() == day
            for appointment in _upcoming_bookings(store, doctor_id)
        ):
            raise DomainError(
                409, "day_off_conflict", "There are already booked visits on this date."
            )
        store.days_off.add((doctor_id, day))


def remove_day_off(store: Store, doctor_id: int, day: date) -> None:
    with store.lock:
        if (doctor_id, day) not in store.days_off:
            raise DomainError(404, "day_off_not_found", "Day off not found.")
        store.days_off.remove((doctor_id, day))


def book_appointment(
    store: Store, patient_id: int, doctor_id: int, start: datetime
) -> Appointment:
    try:
        start = start.astimezone(CLINIC_TZ)
    except OverflowError as error:
        raise DomainError(
            422, "invalid_timestamp", "Timestamp is outside the clinic calendar."
        ) from error

    with store.lock:
        doctor = store.doctors.get(doctor_id)
        if doctor is None:
            raise DomainError(404, "doctor_not_found", "Doctor not found.")
        if not doctor.is_active:
            raise DomainError(409, "doctor_inactive", "This doctor is not accepting appointments.")
        if start <= store.now():
            raise DomainError(409, "past_slot", "The appointment must start in the future.")

        day = start.date()
        schedule = store.schedules.get((doctor_id, day.weekday()))
        if schedule is None or (doctor_id, day) in store.days_off:
            raise DomainError(409, "doctor_unavailable", "The doctor does not work on this date.")

        end = next(
            (slot_end for slot_start, slot_end in _schedule_slots(schedule, day) if slot_start == start),
            None,
        )
        if end is None:
            raise DomainError(409, "invalid_slot", "The start time does not match the doctor's schedule.")

        for existing in store.appointments.values():
            if existing.status == AppointmentStatus.CANCELLED:
                continue
            if not _overlaps(existing, start, end):
                continue
            if existing.doctor_id == doctor_id:
                raise DomainError(409, "slot_taken", "This slot has already been booked.")
            if existing.patient_id == patient_id:
                raise DomainError(409, "patient_conflict", "You already have a visit during this time.")

        appointment = Appointment(store.next_id("appointment"), doctor_id, patient_id, start, end)
        store.appointments[appointment.id] = appointment
        return appointment


def list_appointments(
    store: Store, user: User, status: AppointmentStatus | None
) -> list[Appointment]:
    with store.lock:
        is_patient = user.role == Role.PATIENT
        appointments = [
            appointment
            for appointment in store.appointments.values()
            if user.id == (
                appointment.patient_id if is_patient else appointment.doctor_id
            )
            and (status is None or status == appointment.status)
        ]
        return sorted(appointments, key=lambda item: (item.starts_at, item.id))


def _appointment(store: Store, appointment_id: int) -> Appointment:
    appointment = store.appointments.get(appointment_id)
    if appointment is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")
    return appointment


def cancel_appointment(store: Store, patient_id: int, appointment_id: int) -> Appointment:
    with store.lock:
        appointment = _appointment(store, appointment_id)
        if appointment.patient_id != patient_id:
            raise DomainError(403, "appointment_forbidden", "You can only cancel your own visits.")
        if appointment.status != AppointmentStatus.BOOKED or appointment.starts_at <= store.now():
            raise DomainError(409, "cannot_cancel", "Only future booked visits can be cancelled.")
        cancelled = replace(appointment, status=AppointmentStatus.CANCELLED)
        store.appointments[appointment_id] = cancelled
        return cancelled


def create_medical_record(
    store: Store, doctor_id: int, appointment_id: int, diagnosis: str, notes: str
) -> MedicalRecord:
    with store.lock:
        appointment = _appointment(store, appointment_id)
        if appointment.doctor_id != doctor_id:
            raise DomainError(
                403, "appointment_forbidden", "Only the assigned doctor can record the result."
            )
        if appointment.status != AppointmentStatus.BOOKED:
            raise DomainError(409, "cannot_complete", "Only a booked visit can be completed.")
        now = store.now()
        if appointment.starts_at > now:
            raise DomainError(409, "visit_not_started", "The visit has not started yet.")
        record = MedicalRecord(appointment_id, doctor_id, appointment.patient_id, diagnosis, notes, now)
        store.records[appointment_id] = record
        store.appointments[appointment_id] = replace(appointment, status=AppointmentStatus.DONE)
        return record


def medical_history(store: Store, user: User, patient_id: int) -> list[MedicalRecord]:
    with store.lock:
        if user.role == Role.PATIENT and user.id != patient_id:
            raise DomainError(403, "history_forbidden", "You can only view your own history.")

        patient = store.users.get(patient_id)
        if patient is None or patient.role != Role.PATIENT:
            raise DomainError(404, "patient_not_found", "Patient not found.")

        if user.role == Role.DOCTOR and not any(
            appointment.patient_id == patient_id and appointment.doctor_id == user.id
            for appointment in store.appointments.values()
        ):
            raise DomainError(403, "history_forbidden", "This patient has no visits with you.")

        records = [
            record
            for record in store.records.values()
            if record.patient_id == patient_id
            and (user.role == Role.PATIENT or record.doctor_id == user.id)
        ]
        return sorted(records, key=lambda item: (item.created_at, item.appointment_id), reverse=True)
