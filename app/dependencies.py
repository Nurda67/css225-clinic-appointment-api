from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.domain import Role
from app.errors import DomainError
from app.models import User
from app.security import get_token_user_id

bearer = HTTPBearer(
    scheme_name="JWTBearer",
    bearerFormat="JWT",
    description="Enter the access token returned by POST /auth/login.",
    auto_error=False,
)


def get_session(request: Request) -> Iterator[Session]:
    # Each request shares one session. Success commits and an error rolls back.
    with request.app.state.database.session_factory.begin() as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_session)]
ResourceId = Annotated[int, Path(gt=0)]


def get_current_user(
    request: Request,
    session: DatabaseSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise DomainError(401, "authentication_required", "Provide a bearer token.")

    user_id = get_token_user_id(credentials.credentials, request.app.state.jwt_secret)
    user = session.get(User, user_id)
    if user is None or user.email is None:
        raise DomainError(401, "invalid_token", "The bearer token is invalid or expired.")
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def check_role(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise DomainError(403, "forbidden", "Your role cannot perform this operation.")
        return user

    return check_role


Patient = Annotated[User, Depends(require_roles(Role.PATIENT))]
DoctorUser = Annotated[User, Depends(require_roles(Role.DOCTOR))]
PatientOrDoctor = Annotated[User, Depends(require_roles(Role.PATIENT, Role.DOCTOR))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
