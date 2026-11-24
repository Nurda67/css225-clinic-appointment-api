from fastapi import APIRouter, status

from app.dependencies import DatabaseSession, DoctorUser, Patient, PatientOrDoctor, ResourceId
from app.domain import AppointmentStatus
from app.errors import error_responses
from app.models import Appointment, MedicalRecord
from app.schemas import (
    AppointmentInput,
    AppointmentResponse,
    AppointmentUpdate,
    MedicalRecordInput,
    MedicalRecordResponse,
    SlotChoice,
)
from app.services import visits


router = APIRouter()


@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Appointments"],
    responses=error_responses(401, 403, 404, 409),
)
def post_appointment(
    data: AppointmentInput, patient: Patient, session: DatabaseSession
) -> Appointment:
    """Book an available slot for the authenticated patient."""
    return visits.book_appointment(session, patient.id, data.doctor_id, data.starts_at)


@router.get(
    "/appointments",
    response_model=list[AppointmentResponse],
    tags=["Appointments"],
    responses=error_responses(401, 403),
)
def get_appointments(
    user: PatientOrDoctor,
    session: DatabaseSession,
    status: AppointmentStatus | None = None,
) -> list[Appointment]:
    """List your own appointments, optionally filtered by status."""
    return visits.list_appointments(session, user, status)


@router.patch(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    tags=["Appointments"],
    responses=error_responses(401, 403, 404, 409),
)
def patch_appointment(
    appointment_id: ResourceId,
    data: AppointmentUpdate,
    patient: Patient,
    session: DatabaseSession,
) -> Appointment:
    """Cancel one of your own future bookings."""
    return visits.cancel_appointment(session, patient.id, appointment_id)


@router.patch(
    "/appointments/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
    tags=["Appointments"],
    responses=error_responses(401, 403, 404, 409),
)
def patch_reschedule_appointment(
    appointment_id: ResourceId, data: SlotChoice, patient: Patient, session: DatabaseSession
) -> Appointment:
    """Move your own future visit to a new slot with the same doctor."""
    return visits.reschedule_appointment(session, patient.id, appointment_id, data.starts_at)


@router.post(
    "/appointments/{appointment_id}/medical-record",
    response_model=MedicalRecordResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Medical records"],
    responses=error_responses(401, 403, 404, 409),
)
def post_medical_record(
    appointment_id: ResourceId,
    data: MedicalRecordInput,
    doctor: DoctorUser,
    session: DatabaseSession,
) -> MedicalRecord:
    """Save the result of an assigned visit and mark it done."""
    return visits.create_medical_record(
        session, doctor.id, appointment_id, data.diagnosis, data.notes
    )


@router.get(
    "/patients/{patient_id}/medical-records",
    response_model=list[MedicalRecordResponse],
    tags=["Medical records"],
    responses=error_responses(401, 403, 404),
)
def get_medical_history(
    patient_id: ResourceId, user: PatientOrDoctor, session: DatabaseSession
) -> list[MedicalRecord]:
    """View your records as a patient, or the records you authored as a doctor."""
    return visits.medical_history(session, user, patient_id)
