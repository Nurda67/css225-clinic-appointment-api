from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import Role
from app.errors import DomainError
from app.models import User
from app.security import hash_password, verify_password

# Verify a hash even when the email is unknown to keep login work similar.
DUMMY_PASSWORD_HASH = hash_password("placeholder for unknown accounts")


def find_user_by_email(session: Session, email: str) -> User | None:
    statement = select(User).where(func.lower(User.email) == email.lower())
    return session.scalar(statement)


def set_user_credentials(session: Session, user: User, email: str, password: str) -> None:
    existing_user = find_user_by_email(session, email)
    if existing_user is not None and existing_user.id != user.id:
        raise DomainError(409, "email_taken", "This email is already registered.")
    user.email = email
    user.password_hash = hash_password(password)


def create_user(session: Session, name: str, email: str, password: str, role: Role) -> User:
    user = User(name=name, role=role)
    set_user_credentials(session, user, email, password)
    session.add(user)
    session.flush()
    return user


def authenticate_user(session: Session, email: str, password: str) -> User:
    user = find_user_by_email(session, email)
    stored_hash = user.password_hash if user is not None else None
    valid_password = verify_password(password, stored_hash or DUMMY_PASSWORD_HASH)
    if user is None or stored_hash is None or not valid_password:
        raise DomainError(401, "invalid_credentials", "The email or password is incorrect.")
    return user
