from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CLINIC_TZ, now
from app.domain import AppointmentStatus, Role
from app.errors import DomainError
from app.models import Appointment, MedicalRecord, User
from app.services.notifications import notify
from app.services.schedule import ensure_shift_open
from app.services.visits import book_appointment, lock_appointment, lock_patient
from app.workflow_models import FollowUpRecommendation, IntakeForm


def _get_owned_appointment(session: Session, user: User, appointment_id: int) -> Appointment:
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise DomainError(404, "appointment_not_found", "Appointment not found.")

    is_patient = user.role == Role.PATIENT and user.id == appointment.patient_id
    is_doctor = user.role == Role.DOCTOR and user.id == appointment.doctor_id
    if not (is_patient or is_doctor):
        raise DomainError(403, "appointment_forbidden", "You do not have access to this visit.")
    return appointment


def _appointment_owner(user: User):
    if user.role == Role.PATIENT:
        return Appointment.patient_id == user.id
    if user.role == Role.DOCTOR:
        return Appointment.doctor_id == user.id
    raise DomainError(403, "appointment_forbidden", "You do not have access to this visit.")


def get_intake(session: Session, user: User, appointment_id: int) -> IntakeForm:
    query = (
        select(IntakeForm)
        .join(Appointment, Appointment.id == IntakeForm.appointment_id)
        .where(Appointment.id == appointment_id, _appointment_owner(user))
    )
    intake = session.scalar(query)
    if intake is None:
        _get_owned_appointment(session, user, appointment_id)
        raise DomainError(
            404, "intake_not_found", "No questionnaire has been submitted for this visit."
        )
    return intake


def save_intake(
    session: Session, patient_id: int, appointment_id: int, reason: str, questions: str
) -> IntakeForm:
    appointment = lock_appointment(session, appointment_id)
    if appointment.patient_id != patient_id:
        raise DomainError(403, "appointment_forbidden", "You can only edit your own questionnaires.")
    if appointment.status != AppointmentStatus.BOOKED:
        raise DomainError(
            409, "intake_closed", "You can only edit a questionnaire for a booked visit."
        )

    intake = session.get(IntakeForm, appointment.id)
    if intake is None:
        intake = IntakeForm(appointment_id=appointment.id, reason=reason, questions=questions)
        session.add(intake)
    else:
        intake.reason = reason
        intake.questions = questions
    session.flush()
    return intake


def mark_attendance(
    session: Session, doctor_id: int, appointment_id: int, attendance: str
) -> Appointment:
    appointment = lock_appointment(session, appointment_id)
    if appointment.doctor_id != doctor_id:
        raise DomainError(
            403, "appointment_forbidden", "Only the assigned doctor can record attendance."
        )
    if appointment.status == AppointmentStatus.NO_SHOW and attendance == "no_show":
        return appointment
    if appointment.status != AppointmentStatus.BOOKED:
        raise DomainError(
            409, "attendance_closed", "Attendance can only be recorded for a booked visit."
        )

    ensure_shift_open(session, appointment)
    recorded_at = now(session)
    if appointment.starts_at > recorded_at:
        raise DomainError(
            409, "visit_not_started", "Attendance can be recorded once the visit starts."
        )
    if attendance == "no_show":
        if appointment.arrived_at is not None:
            raise DomainError(409, "patient_arrived", "Attendance was already recorded as arrived.")
        appointment.status = AppointmentStatus.NO_SHOW
    elif appointment.arrived_at is None:
        appointment.arrived_at = recorded_at
    session.flush()
    return appointment


def get_medical_record(session: Session, user: User, appointment_id: int) -> MedicalRecord:
    query = (
        select(MedicalRecord)
        .join(MedicalRecord.appointment)
        .where(Appointment.id == appointment_id, _appointment_owner(user))
    )
    record = session.scalar(query)
    if record is None:
        _get_owned_appointment(session, user, appointment_id)
        raise DomainError(
            404, "medical_record_not_found", "There is no medical record for this visit."
        )
    return record


def recommend_follow_up(
    session: Session, doctor_id: int, appointment_id: int, start_date: date, end_date: date
) -> FollowUpRecommendation:
    appointment = lock_appointment(session, appointment_id)
    if appointment.doctor_id != doctor_id:
        raise DomainError(
            403, "appointment_forbidden", "Only the assigned doctor can recommend a follow-up."
        )
    if appointment.status != AppointmentStatus.DONE:
        raise DomainError(
            409, "visit_not_completed", "Complete the visit before recommending a follow-up."
        )
    if start_date < now(session).date():
        raise DomainError(409, "follow_up_in_past", "The follow-up date range cannot start in the past.")

    existing = session.scalar(
        select(FollowUpRecommendation.id).where(
            FollowUpRecommendation.original_appointment_id == appointment.id
        )
    )
    if existing is not None:
        raise DomainError(
            409, "follow_up_exists", "A follow-up was already recommended for this visit."
        )

    recommendation = FollowUpRecommendation(
        original_appointment_id=appointment.id,
        doctor_id=doctor_id,
        patient_id=appointment.patient_id,
        start_date=start_date,
        end_date=end_date,
    )
    session.add(recommendation)
    session.flush()
    notify(
        session,
        appointment.patient_id,
        "follow_up",
        "Your doctor recommended a follow-up visit. Choose a time from the follow-ups list.",
        recommendation.id,
    )
    return recommendation


def list_follow_ups(session: Session, user: User) -> list[FollowUpRecommendation]:
    query = select(FollowUpRecommendation)
    if user.role == Role.PATIENT:
        query = query.where(FollowUpRecommendation.patient_id == user.id)
    elif user.role == Role.DOCTOR:
        query = query.where(FollowUpRecommendation.doctor_id == user.id)
    else:
        raise DomainError(403, "follow_up_forbidden", "Your role cannot view follow-ups.")
    query = query.order_by(FollowUpRecommendation.start_date, FollowUpRecommendation.id)
    return list(session.scalars(query))


def book_follow_up(
    session: Session, patient_id: int, recommendation_id: int, starts_at: datetime
) -> Appointment:
    # Hold the patient lock first, as in the usual booking path.
    lock_patient(session, patient_id)

    recommendation = session.get(
        FollowUpRecommendation, recommendation_id, with_for_update=True, populate_existing=True
    )
    if recommendation is None:
        raise DomainError(404, "follow_up_not_found", "Follow-up recommendation not found.")
    if recommendation.patient_id != patient_id:
        raise DomainError(403, "follow_up_forbidden", "You can only book your own follow-up.")
    if recommendation.booked_appointment_id is not None:
        raise DomainError(409, "follow_up_booked", "You already booked this follow-up.")

    try:
        slot_day = starts_at.astimezone(CLINIC_TZ).date()
    except OverflowError as error:
        raise DomainError(
            422, "invalid_timestamp", "Timestamp is outside the clinic calendar."
        ) from error
    if not recommendation.start_date <= slot_day <= recommendation.end_date:
        raise DomainError(
            409, "outside_follow_up_dates", "Choose a slot within the recommended date range."
        )

    appointment = book_appointment(session, patient_id, recommendation.doctor_id, starts_at)
    appointment.previous_appointment_id = recommendation.original_appointment_id
    recommendation.booked_appointment_id = appointment.id
    session.flush()
    return appointment
