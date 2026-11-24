import argparse
import warnings
from getpass import GetPassWarning, getpass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import ArgumentError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config import get_database_url
from app.database import Database
from app.errors import DomainError
from app.models import User
from app.schemas import AccountEmail
from app.services.accounts import set_user_credentials


def activate_user(session: Session, user_id: int, email: str, password: str) -> None:
    user = session.get(User, user_id, with_for_update=True, populate_existing=True)
    if user is None:
        raise DomainError(404, "user_not_found", "User not found.")
    if user.email is not None:
        raise DomainError(409, "credentials_already_set", "This user already has login credentials.")
    set_user_credentials(session, user, email, password)
    session.flush()


def prompt_for_password() -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("New password: ")
            confirmation = getpass("Repeat password: ")
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        raise SystemExit("Use an interactive terminal to enter the password.") from None
    if password != confirmation:
        raise SystemExit("The passwords do not match.")
    if not 8 <= len(password) <= 128:
        raise SystemExit("The password must contain 8 to 128 characters.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Enable login for an existing clinic user.")
    parser.add_argument("user_id", type=int)
    parser.add_argument("email")
    args = parser.parse_args()
    if not 1 <= args.user_id <= 2_147_483_647:
        parser.error("user_id must be a positive PostgreSQL integer.")
    try:
        email = TypeAdapter(AccountEmail).validate_python(args.email)
    except ValidationError:
        parser.error("Enter a valid email address.")

    password = prompt_for_password()

    try:
        database = Database(get_database_url())
    except (ArgumentError, ValueError):
        raise SystemExit("Check the clinic database settings.") from None
    try:
        with database.session_factory.begin() as session:
            activate_user(session, args.user_id, email, password)
        print("Login enabled for the existing user.")
    except DomainError as error:
        raise SystemExit(error.message) from None
    except IntegrityError:
        raise SystemExit("The credentials conflict with existing data.") from None
    except OperationalError:
        raise SystemExit("Could not connect to the clinic database.") from None
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
