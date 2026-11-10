from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domain import Role, User
from app.errors import DomainError
from app.store import Store

bearer = HTTPBearer(
    scheme_name="DemoBearer",
    description="Enter a demo token from the README.",
    auto_error=False,
)


def get_store(request: Request) -> Store:
    return request.app.state.store


def require_roles(*roles: Role) -> Callable[..., User]:
    def check_access(
        store: Annotated[Store, Depends(get_store)],
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> User:
        if credentials is None:
            raise DomainError(401, "authentication_required", "Provide a bearer token.")
        with store.lock:
            user_id = store.tokens.get(credentials.credentials)
            user = store.users.get(user_id) if user_id is not None else None
        if user is None:
            raise DomainError(401, "invalid_token", "The bearer token is invalid.")
        if user.role not in roles:
            raise DomainError(403, "forbidden", "Your role cannot perform this operation.")
        return user

    return check_access
