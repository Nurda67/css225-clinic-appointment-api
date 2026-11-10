from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.dependencies import get_store, require_roles
from app.domain import Appointment, AppointmentStatus, MedicalRecord, Role, Schedule, User
from app.schemas.errors import error_responses
from app.schemas.visits import (
    AppointmentInput,
    AppointmentResponse,
    AppointmentUpdate,
    DayOffInput,
    DoctorSchedule,
    MedicalRecordInput,
    MedicalRecordResponse,
    ScheduleInput,
    ScheduleItem,
    SlotResponse,
)
from app.services import visits
from app.store import Store


router = APIRouter()
StoreDependency = Annotated[Store, Depends(get_store)]
Patient = Annotated[User, Depends(require_roles(Role.PATIENT))]
Doctor = Annotated[User, Depends(require_roles(Role.DOCTOR))]
PatientOrDoctor = Annotated[User, Depends(require_roles(Role.PATIENT, Role.DOCTOR))]
ResourceId = Annotated[int, Path(gt=0)]


@router.get(
    "/doctors/{doctor_id}/slots",
    tags=["Doctors"],
    responses=error_responses(404),
)
def list_slots(
    doctor_id: ResourceId,
    day: Annotated[date, Query(alias="date", description="Date in the clinic calendar.")],
    store: StoreDependency,
) -> list[SlotResponse]:
    """List the doctor's future, unreserved slots on a date."""
    return [
        SlotResponse(starts_at=start, ends_at=end)
        for start, end in visits.available_slots(store, doctor_id, day)
    ]


@router.get(
    "/doctors/me/schedule",
    tags=["Doctor schedule"],
    responses=error_responses(401, 403),
)
def get_own_schedule(doctor: Doctor, store: StoreDependency) -> DoctorSchedule:
    """View your weekly working hours and days off."""
    schedule, days_off = visits.doctor_schedule(store, doctor.id)
    return DoctorSchedule(
        schedule=[
            ScheduleItem(
                weekday=weekday, start=hours.start, end=hours.end, slot_minutes=hours.slot_minutes
            )
            for weekday, hours in schedule
        ],
        days_off=days_off,
    )


@router.put(
    "/doctors/me/schedule/{weekday}",
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 409),
)
def put_working_hours(
    weekday: Annotated[int, Path(ge=0, le=6, description="Monday is 0 and Sunday is 6.")],
    data: ScheduleInput,
    doctor: Doctor,
    store: StoreDependency,
) -> ScheduleItem:
    """Set your clinic-local working hours for a weekday."""
    schedule = Schedule(data.start, data.end, data.slot_minutes)
    visits.set_working_hours(store, doctor.id, weekday, schedule)
    return ScheduleItem(weekday=weekday, **data.model_dump())


@router.post(
    "/doctors/me/days-off",
    status_code=status.HTTP_201_CREATED,
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 409),
)
def post_day_off(data: DayOffInput, doctor: Doctor, store: StoreDependency) -> DayOffInput:
    """Mark a date as closed if you have no upcoming visits that day."""
    visits.add_day_off(store, doctor.id, data.date)
    return data


@router.delete(
    "/doctors/me/days-off/{day}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 404),
)
def delete_day_off(day: date, doctor: Doctor, store: StoreDependency) -> Response:
    """Remove a date override and restore the weekly schedule for that day."""
    visits.remove_day_off(store, doctor.id, day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Appointments"],
    responses=error_responses(401, 403, 404, 409),
)
def post_appointment(
    data: AppointmentInput, patient: Patient, store: StoreDependency
) -> Appointment:
    """Book an available slot for the authenticated patient."""
    return visits.book_appointment(store, patient.id, data.doctor_id, data.starts_at)


@router.get(
    "/appointments",
    response_model=list[AppointmentResponse],
    tags=["Appointments"],
    responses=error_responses(401, 403),
)
def get_appointments(
    user: PatientOrDoctor,
    store: StoreDependency,
    status: AppointmentStatus | None = None,
) -> list[Appointment]:
    """List your own appointments, optionally filtered by status."""
    return visits.list_appointments(store, user, status)


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
    store: StoreDependency,
) -> Appointment:
    """Cancel one of your own future bookings."""
    return visits.cancel_appointment(store, patient.id, appointment_id)


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
    doctor: Doctor,
    store: StoreDependency,
) -> MedicalRecord:
    """Save the result of an assigned visit and mark it done."""
    return visits.create_medical_record(store, doctor.id, appointment_id, data.diagnosis, data.notes)


@router.get(
    "/patients/{patient_id}/medical-records",
    response_model=list[MedicalRecordResponse],
    tags=["Medical records"],
    responses=error_responses(401, 403, 404),
)
def get_medical_history(
    patient_id: ResourceId, user: PatientOrDoctor, store: StoreDependency
) -> list[MedicalRecord]:
    """View your records as a patient, or the records you authored as a doctor."""
    return visits.medical_history(store, user, patient_id)
