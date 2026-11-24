from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.dependencies import DatabaseSession, get_current_user
from app.domain import Role
from app.errors import error_responses
from app.models import User
from app.schemas import LoginInput, RegistrationInput, TokenResponse, UserResponse
from app.security import create_access_token
from app.services import accounts

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409),
)
def register(body: RegistrationInput, session: DatabaseSession) -> User:
    """Register a patient account with a unique email address."""
    return accounts.create_user(
        session, body.name, body.email, body.password.get_secret_value(), Role.PATIENT
    )


@router.post("/login", response_model=TokenResponse, responses=error_responses(401))
def login(
    body: LoginInput, session: DatabaseSession, request: Request, response: Response
) -> TokenResponse:
    """Verify an email and password and return an access token."""
    user = accounts.authenticate_user(session, body.email, body.password.get_secret_value())
    token = create_access_token(user.id, request.app.state.jwt_secret)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserResponse, responses=error_responses(401))
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Get the current user's profile and role."""
    return user
