from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import Appointment, DayOff, User
from app.services import visits, waitlist
from app.services.notifications import notify
from app.services.schedule import available_slots, get_doctor
from app.workflow_models import ReplacementOffer


def propose_replacements(
    session: Session, doctor_id: int, replacement_doctor_id: int, day: date
) -> list[ReplacementOffer]:
    if doctor_id == replacement_doctor_id:
        raise DomainError(409, "same_doctor", "Choose a different doctor for the replacement.")
    current_time = now(session)
    if day < current_time.date():
        raise DomainError(409, "past_date", "Choose today or a future date.")

    doctors = {
        item_id: get_doctor(session, item_id, lock=True)
        for item_id in sorted((doctor_id, replacement_doctor_id))
    }
    original_doctor = doctors[doctor_id]
    replacement_doctor = doctors[replacement_doctor_id]
    if original_doctor.specialty_id != replacement_doctor.specialty_id:
        raise DomainError(
            409, "specialty_mismatch", "The replacement doctor must have the same specialty."
        )
    if not replacement_doctor.is_active:
        raise DomainError(409, "replacement_inactive", "The replacement doctor is not active.")

    opens_at = datetime.combine(day, time.min, CLINIC_TZ)
    closes_at = datetime.combine(day, time.max, CLINIC_TZ)
    query = (
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.starts_at >= opens_at,
            Appointment.starts_at <= closes_at,
            Appointment.starts_at > current_time,
        )
        .order_by(Appointment.starts_at, Appointment.id)
    )
    appointments = list(session.scalars(query))
    if not appointments:
        raise DomainError(
            409, "no_visits_to_replace", "There are no upcoming visits to replace on this date."
        )

    free_slots = set(available_slots(session, replacement_doctor_id, day))
    for appointment in appointments:
        if (appointment.starts_at, appointment.ends_at) not in free_slots:
            raise DomainError(
                409,
                "replacement_unavailable",
                "The replacement doctor does not have matching free slots for every visit.",
            )

    day_off = session.get(DayOff, (doctor_id, day), populate_existing=True)
    if day_off is None:
        session.add(DayOff(doctor_id=doctor_id, date=day, closed_for_replacement=True))
    else:
        day_off.closed_for_replacement = True
    waitlist.expire_day_offers(session, doctor_id, day)
    offers = []
    for appointment in appointments:
        pending = session.scalar(
            select(ReplacementOffer).where(
                ReplacementOffer.appointment_id == appointment.id,
                ReplacementOffer.status == "pending",
            )
        )
        if pending is not None and pending.replacement_doctor_id == replacement_doctor_id:
            offers.append(pending)
            continue
        if pending is not None:
            pending.status = "stale"
            session.flush()

        offer = ReplacementOffer(
            appointment_id=appointment.id,
            original_doctor_id=doctor_id,
            replacement_doctor_id=replacement_doctor_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status="pending",
            created_at=current_time,
        )
        session.add(offer)
        session.flush()
        message = f"A replacement doctor is available for your visit on {day} at the same time."
        notify(session, appointment.patient_id, "doctor_replacement", message, offer.id)
        offers.append(offer)
    return offers


def list_replacements(session: Session, user: User) -> list[ReplacementOffer]:
    query = select(ReplacementOffer)
    if user.role == Role.PATIENT:
        query = query.join(Appointment, Appointment.id == ReplacementOffer.appointment_id)
        query = query.where(Appointment.patient_id == user.id)
    return list(
        session.scalars(query.order_by(ReplacementOffer.created_at.desc(), ReplacementOffer.id.desc()))
    )


def accept_replacement(session: Session, patient_id: int, offer_id: int) -> Appointment:
    offer = session.get(ReplacementOffer, offer_id)
    if offer is None:
        raise DomainError(404, "replacement_not_found", "Replacement offer not found.")
    visits.lock_patient(session, patient_id)
    appointment = visits.lock_appointment(
        session, offer.appointment_id, additional_doctor_id=offer.replacement_doctor_id
    )
    if appointment.patient_id != patient_id:
        raise DomainError(403, "replacement_forbidden", "You can only confirm your own replacement.")

    session.refresh(offer, with_for_update=True)
    if (
        offer.status != "pending"
        or appointment.status != AppointmentStatus.BOOKED
        or appointment.doctor_id != offer.original_doctor_id
        or appointment.starts_at != offer.starts_at
        or appointment.ends_at != offer.ends_at
        or appointment.starts_at <= now(session)
    ):
        raise DomainError(409, "offer_unavailable", "This replacement offer is no longer available.")

    doctor = get_doctor(session, offer.replacement_doctor_id)
    start, end = visits.get_booking_slot(session, doctor, offer.starts_at)
    if end != offer.ends_at:
        raise DomainError(
            409, "replacement_unavailable", "The replacement doctor's schedule has changed."
        )
    visits.ensure_slot_free(
        session, patient_id, doctor.id, start, end, exclude_appointment_id=appointment.id
    )
    appointment.doctor_id = doctor.id
    offer.status = "accepted"
    session.flush()
    waitlist.expire_slot_offers(session, doctor.id, start)
    return appointment
