from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from sqlalchemy.orm import Session

from app.dependencies import get_session, require_roles
from app.domain import Role
from app.models import User
from app.schemas.directory import (
    DoctorCreate,
    DoctorCreated,
    DoctorUpdate,
    DoctorView,
    SpecialtyView,
    SpecialtyWrite,
    StatisticsView,
)
from app.schemas.errors import error_responses
from app.services import directory


router = APIRouter()

SessionDependency = Annotated[Session, Depends(get_session)]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
PositivePathID = Annotated[int, Path(gt=0)]


@router.get("/specialties", tags=["Directory"], response_model=list[SpecialtyView])
def list_specialties(session: SessionDependency):
    """List the specialties available in the clinic directory."""
    return directory.list_specialties(session)


@router.post(
    "/specialties",
    tags=["Administration"],
    response_model=SpecialtyView,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409),
)
def create_specialty(body: SpecialtyWrite, session: SessionDependency, _admin: AdminUser):
    """Add a specialty with a unique name."""
    return directory.create_specialty(session, body.name)


@router.patch(
    "/specialties/{specialty_id}",
    tags=["Administration"],
    response_model=SpecialtyView,
    responses=error_responses(401, 403, 404, 409),
)
def rename_specialty(
    specialty_id: PositivePathID, body: SpecialtyWrite, session: SessionDependency, _admin: AdminUser
):
    """Rename a specialty and keep its existing doctor assignments."""
    return directory.rename_specialty(session, specialty_id, body.name)


@router.delete(
    "/specialties/{specialty_id}",
    tags=["Administration"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409),
)
def delete_specialty(specialty_id: PositivePathID, session: SessionDependency, _admin: AdminUser):
    """Delete a specialty if it has no assigned doctors."""
    directory.delete_specialty(session, specialty_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/doctors",
    tags=["Directory"],
    response_model=list[DoctorView],
    responses=error_responses(404),
)
def list_doctors(
    session: SessionDependency,
    specialty_id: Annotated[int | None, Query(gt=0)] = None,
    q: Annotated[str | None, Query(max_length=120, pattern=r"^[^\x00]*[^\s\x00][^\x00]*$")] = None,
):
    """Find active doctors by name, specialty name, or specialty ID."""
    return directory.list_doctors(session, specialty_id, q)


@router.get(
    "/doctors/{doctor_id}",
    tags=["Directory"],
    response_model=DoctorView,
    responses=error_responses(404),
)
def get_doctor(doctor_id: PositivePathID, session: SessionDependency):
    """View an active doctor's public profile."""
    return directory.get_public_doctor(session, doctor_id)


@router.post(
    "/doctors",
    tags=["Administration"],
    response_model=DoctorCreated,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404),
)
def create_doctor(body: DoctorCreate, session: SessionDependency, _admin: AdminUser):
    """Create a doctor account and issue its bearer token."""
    return directory.create_doctor(session, body.name, body.specialty_id)


@router.patch(
    "/doctors/{doctor_id}",
    tags=["Administration"],
    response_model=DoctorView,
    responses=error_responses(401, 403, 404),
)
def update_doctor_status(
    doctor_id: PositivePathID, body: DoctorUpdate, session: SessionDependency, _admin: AdminUser
):
    """Block or unblock new bookings while preserving existing appointments."""
    return directory.set_doctor_status(session, doctor_id, body.is_active)


@router.get(
    "/statistics",
    tags=["Administration"],
    response_model=StatisticsView,
    responses=error_responses(401, 403),
)
def get_statistics(
    session: SessionDependency,
    _admin: AdminUser,
    start_date: Annotated[date | None, Query(description="First clinic date (inclusive).")] = None,
    end_date: Annotated[date | None, Query(description="Last clinic date (inclusive).")] = None,
):
    """Show directory totals and appointment counts for the selected clinic dates."""
    return directory.get_statistics(session, start_date, end_date)
