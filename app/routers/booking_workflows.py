from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.booking_schemas import (
    NotificationView,
    ReplacementOfferView,
    ShiftReplacementInput,
    WaitlistInput,
    WaitlistView,
)
from app.dependencies import (
    AdminUser,
    DatabaseSession,
    Patient,
    ResourceId,
    get_current_user,
    require_roles,
)
from app.domain import Role
from app.errors import error_responses
from app.schemas import AppointmentResponse
from app.services import notifications, replacements, visits, waitlist
from app.models import Appointment, User
from app.workflow_models import Notification, ReplacementOffer, WaitlistEntry

router = APIRouter()
CurrentUser = Annotated[User, Depends(get_current_user)]
PatientOrAdmin = Annotated[User, Depends(require_roles(Role.PATIENT, Role.ADMIN))]


@router.post(
    "/waitlist",
    response_model=WaitlistView,
    status_code=status.HTTP_201_CREATED,
    tags=["Waitlist"],
    responses=error_responses(401, 403, 404, 409),
)
def join_waitlist(data: WaitlistInput, patient: Patient, session: DatabaseSession) -> WaitlistEntry:
    """Join the waitlist for a doctor on a clinic date."""
    return waitlist.join_waitlist(session, patient.id, data.doctor_id, data.date)


@router.get(
    "/waitlist",
    response_model=list[WaitlistView],
    tags=["Waitlist"],
    responses=error_responses(401, 403),
)
def list_waitlist(patient: Patient, session: DatabaseSession) -> list[WaitlistEntry]:
    """View your entries and available offers."""
    return waitlist.list_waitlist(session, patient.id)


@router.post(
    "/waitlist/{entry_id}/accept",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Waitlist"],
    responses=error_responses(401, 403, 404, 409),
)
def accept_waitlist_offer(entry_id: ResourceId, patient: Patient, session: DatabaseSession) -> Appointment:
    """Book the offered slot if it is still free."""
    return visits.accept_waitlist_offer(session, patient.id, entry_id)


@router.get(
    "/notifications",
    response_model=list[NotificationView],
    tags=["Notifications"],
    responses=error_responses(401),
)
def list_notifications(user: CurrentUser, session: DatabaseSession) -> list[Notification]:
    """View your in-app notifications, newest first."""
    return notifications.list_notifications(session, user.id)


@router.patch(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Notifications"],
    responses=error_responses(401, 404),
)
def mark_notification_read(
    notification_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> Response:
    """Mark one of your notifications as read."""
    notifications.mark_read(session, user.id, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/shift-replacements",
    response_model=list[ReplacementOfferView],
    status_code=status.HTTP_201_CREATED,
    tags=["Shift replacements"],
    responses=error_responses(401, 403, 404, 409),
)
def propose_shift_replacements(
    data: ShiftReplacementInput, admin: AdminUser, session: DatabaseSession
) -> list[ReplacementOffer]:
    """Close the original doctor's shift and notify patients about a matching substitute."""
    return replacements.propose_replacements(session, data.doctor_id, data.replacement_doctor_id, data.date)


@router.get(
    "/shift-replacements",
    response_model=list[ReplacementOfferView],
    tags=["Shift replacements"],
    responses=error_responses(401, 403),
)
def list_shift_replacements(user: PatientOrAdmin, session: DatabaseSession) -> list[ReplacementOffer]:
    """View your replacement offers or the clinic's offers as an administrator."""
    return replacements.list_replacements(session, user)


@router.post(
    "/shift-replacements/{offer_id}/accept",
    response_model=AppointmentResponse,
    tags=["Shift replacements"],
    responses=error_responses(401, 403, 404, 409),
)
def accept_shift_replacement(offer_id: ResourceId, patient: Patient, session: DatabaseSession) -> Appointment:
    """Confirm your substitute and transfer your appointment at its current time."""
    return replacements.accept_replacement(session, patient.id, offer_id)
