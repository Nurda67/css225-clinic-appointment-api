from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.dependencies import DatabaseSession, DoctorUser, ResourceId
from app.errors import error_responses
from app.schemas import DayOffInput, DoctorSchedule, ScheduleInput, ScheduleItem, SlotResponse
from app.services import schedule

router = APIRouter()


@router.get(
    "/doctors/{doctor_id}/slots",
    tags=["Doctors"],
    responses=error_responses(404),
)
def list_slots(
    doctor_id: ResourceId,
    day: Annotated[date, Query(alias="date", description="Date in the clinic calendar.")],
    session: DatabaseSession,
) -> list[SlotResponse]:
    """List the doctor's future, unreserved slots on a date."""
    slots = schedule.available_slots(session, doctor_id, day)
    return [SlotResponse(starts_at=start, ends_at=end) for start, end in slots]


@router.get(
    "/doctors/me/schedule",
    tags=["Doctor schedule"],
    responses=error_responses(401, 403),
)
def get_own_schedule(doctor: DoctorUser, session: DatabaseSession) -> DoctorSchedule:
    """View your weekly working hours and days off."""
    hours, days_off = schedule.get_schedule(session, doctor.id)
    return DoctorSchedule(schedule=hours, days_off=days_off)


@router.put(
    "/doctors/me/schedule/{weekday}",
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 409),
)
def put_working_hours(
    weekday: Annotated[int, Path(ge=0, le=6, description="Monday is 0 and Sunday is 6.")],
    data: ScheduleInput,
    doctor: DoctorUser,
    session: DatabaseSession,
) -> ScheduleItem:
    """Set your clinic-local working hours for a weekday."""
    hours = schedule.set_working_hours(
        session, doctor.id, weekday, data.start, data.end, data.slot_minutes
    )
    return ScheduleItem.model_validate(hours)


@router.post(
    "/doctors/me/days-off",
    status_code=status.HTTP_201_CREATED,
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 409),
)
def post_day_off(data: DayOffInput, doctor: DoctorUser, session: DatabaseSession) -> DayOffInput:
    """Mark a date as closed if you have no upcoming visits that day."""
    schedule.add_day_off(session, doctor.id, data.date)
    return data


@router.delete(
    "/doctors/me/days-off/{day}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Doctor schedule"],
    responses=error_responses(401, 403, 404),
)
def delete_day_off(day: date, doctor: DoctorUser, session: DatabaseSession) -> Response:
    """Remove a date override and restore the weekly schedule for that day."""
    schedule.remove_day_off(session, doctor.id, day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
