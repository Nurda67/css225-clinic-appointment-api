from collections.abc import Callable, Iterator
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import Role
from app.errors import DomainError
from app.models import AccessToken, User

bearer = HTTPBearer(
    scheme_name="DemoBearer",
    description="Enter a demo token from the README.",
    auto_error=False,
)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session_factory() as session:
        try:
            with session.begin():
                yield session
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_appointments_active_slot":
                raise DomainError(409, "slot_taken", "This slot has already been booked.") from error
            if constraint == "uq_specialties_name_lower":
                raise DomainError(409, "specialty_name_taken", "A specialty with that name already exists.") from error
            raise DomainError(
                409, "data_conflict", "This operation conflicts with existing or related data."
            ) from error


def require_roles(*roles: Role) -> Callable[..., User]:
    def check_access(
        session: Annotated[Session, Depends(get_session)],
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> User:
        if credentials is None:
            raise DomainError(401, "authentication_required", "Provide a bearer token.")
        token_hash = sha256(credentials.credentials.encode()).hexdigest()
        user = session.scalar(
            select(User).join(AccessToken).where(AccessToken.token_hash == token_hash)
        )
        if user is None:
            raise DomainError(401, "invalid_token", "The bearer token is invalid.")
        if user.role not in roles:
            raise DomainError(403, "forbidden", "Your role cannot perform this operation.")
        return user

    return check_access
