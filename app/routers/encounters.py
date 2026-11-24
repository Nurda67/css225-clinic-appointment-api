from fastapi import APIRouter, status

from app.dependencies import DatabaseSession, DoctorUser, Patient, PatientOrDoctor, ResourceId
from app.encounter_schemas import (
    AttendanceInput,
    FollowUpInput,
    FollowUpView,
    IntakeInput,
    IntakeView,
)
from app.errors import error_responses
from app.models import Appointment, MedicalRecord
from app.schemas import AppointmentResponse, MedicalRecordResponse, SlotChoice
from app.services import encounters
from app.workflow_models import FollowUpRecommendation, IntakeForm


router = APIRouter()


@router.get(
    "/appointments/{appointment_id}/intake",
    response_model=IntakeView,
    tags=["Intake and attendance"],
    responses=error_responses(401, 403, 404),
)
def get_intake(
    appointment_id: ResourceId, user: PatientOrDoctor, session: DatabaseSession
) -> IntakeForm:
    """Read the questionnaire for a visit you own or are assigned to."""
    return encounters.get_intake(session, user, appointment_id)


@router.put(
    "/appointments/{appointment_id}/intake",
    response_model=IntakeView,
    tags=["Intake and attendance"],
    responses=error_responses(401, 403, 404, 409),
)
def put_intake(
    appointment_id: ResourceId, data: IntakeInput, patient: Patient, session: DatabaseSession
) -> IntakeForm:
    """Create or update the questionnaire for your booked visit."""
    return encounters.save_intake(session, patient.id, appointment_id, data.reason, data.questions)


@router.patch(
    "/appointments/{appointment_id}/attendance",
    response_model=AppointmentResponse,
    tags=["Intake and attendance"],
    responses=error_responses(401, 403, 404, 409),
)
def patch_attendance(
    appointment_id: ResourceId, data: AttendanceInput, doctor: DoctorUser, session: DatabaseSession
) -> Appointment:
    """Record whether the patient arrived or did not attend the visit."""
    return encounters.mark_attendance(session, doctor.id, appointment_id, data.status)


@router.get(
    "/appointments/{appointment_id}/medical-record",
    response_model=MedicalRecordResponse,
    tags=["Medical records"],
    responses=error_responses(401, 403, 404),
)
def get_medical_record(
    appointment_id: ResourceId, user: PatientOrDoctor, session: DatabaseSession
) -> MedicalRecord:
    """Read the result of a consultation you attended or conducted."""
    return encounters.get_medical_record(session, user, appointment_id)


@router.post(
    "/appointments/{appointment_id}/follow-up",
    response_model=FollowUpView,
    status_code=status.HTTP_201_CREATED,
    tags=["Follow-ups"],
    responses=error_responses(401, 403, 404, 409),
)
def post_follow_up(
    appointment_id: ResourceId, data: FollowUpInput, doctor: DoctorUser, session: DatabaseSession
) -> FollowUpRecommendation:
    """Suggest a date range for a follow-up after a completed consultation."""
    return encounters.recommend_follow_up(
        session, doctor.id, appointment_id, data.start_date, data.end_date
    )


@router.get(
    "/follow-ups",
    response_model=list[FollowUpView],
    tags=["Follow-ups"],
    responses=error_responses(401, 403),
)
def get_follow_ups(user: PatientOrDoctor, session: DatabaseSession) -> list[FollowUpRecommendation]:
    """List your follow-up recommendations and any linked bookings."""
    return encounters.list_follow_ups(session, user)


@router.post(
    "/follow-ups/{recommendation_id}/book",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Follow-ups"],
    responses=error_responses(401, 403, 404, 409),
)
def post_follow_up_booking(
    recommendation_id: ResourceId, data: SlotChoice, patient: Patient, session: DatabaseSession
) -> Appointment:
    """Book a follow-up with the original doctor within the recommended dates."""
    return encounters.book_follow_up(session, patient.id, recommendation_id, data.starts_at)
