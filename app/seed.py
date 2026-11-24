from datetime import datetime, time, timedelta
from os import getenv

from sqlalchemy import func, select, text
from sqlalchemy.exc import ArgumentError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.activate_user import prompt_for_password
from app.config import get_database_url
from app.database import CLINIC_TZ, Database, now
from app.domain import Role
from app.errors import DomainError
from app.models import Appointment, Doctor, Schedule, Specialty, User
from app.services.accounts import set_user_credentials


def seed_demo_data(session: Session, *, demo_password: str, include_visit: bool = True) -> None:
    """Set up fictional demo accounts and preserve existing credentials and clinic data."""
    session.execute(text("SELECT pg_advisory_xact_lock(225006)"))
    for specialty_id, name in [(1, "General Practice"), (2, "Cardiology")]:
        existing = session.get(Specialty, specialty_id)
        if existing is None:
            session.add(Specialty(id=specialty_id, name=name))
    session.flush()

    demo_users = [
        (1, "Dana Omar", Role.PATIENT, "patient@example.com"),
        (2, "Arman Iskakov", Role.PATIENT, "patient2@example.com"),
        (3, "Aida Sadykova", Role.DOCTOR, "doctor@example.com"),
        (4, "Timur Saparov", Role.DOCTOR, "doctor2@example.com"),
        (5, "Clinic Admin", Role.ADMIN, "admin@example.com"),
    ]
    for user_id, name, role, email in demo_users:
        user = session.get(User, user_id, with_for_update=True, populate_existing=True)
        if user is None:
            user = User(id=user_id, name=name, role=role)
            session.add(user)
        elif user.name != name or user.role != role:
            raise ValueError("Demo account IDs are occupied by different users.")
        if user.email is None:
            set_user_credentials(session, user, email, demo_password)

    for doctor_id, specialty_id in [(3, 1), (4, 2)]:
        if session.get(Doctor, doctor_id) is None:
            session.add(Doctor(id=doctor_id, specialty_id=specialty_id, is_active=True))
            session.flush()
            for weekday in range(5):
                session.add(Schedule(
                    doctor_id=doctor_id, weekday=weekday,
                    start=time(9), end=time(17), slot_minutes=30,
                ))
    session.flush()
    for model in (User, Specialty):
        highest_id = session.scalar(select(func.max(model.id)))
        session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                "GREATEST(COALESCE(pg_sequence_last_value(CAST("
                "pg_get_serial_sequence(:table_name, 'id') AS regclass)), 1), :highest_id), true)"
            ),
            {"table_name": model.__tablename__, "highest_id": highest_id},
        )

    if include_visit and session.scalar(select(Appointment.id).limit(1)) is None:
        day = now(session).date() - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        start = datetime.combine(day, time(9), CLINIC_TZ)
        session.add(Appointment(
            doctor_id=3, patient_id=1, starts_at=start,
            ends_at=start + timedelta(minutes=30),
        ))
    session.flush()


def main() -> None:
    demo_password = getenv("DEMO_PASSWORD") or prompt_for_password()
    if not 8 <= len(demo_password) <= 128:
        raise SystemExit("Set DEMO_PASSWORD to a password with 8 to 128 characters.")

    try:
        database = Database(get_database_url())
    except (ArgumentError, ValueError):
        raise SystemExit("Check the clinic database settings.") from None
    try:
        with database.session_factory.begin() as session:
            seed_demo_data(session, demo_password=demo_password)
        print("Fictional demo accounts are ready. Existing data was preserved.")
    except (DomainError, ValueError) as error:
        raise SystemExit(str(error)) from None
    except IntegrityError:
        raise SystemExit("Demo credentials conflict with existing data.") from None
    except OperationalError:
        raise SystemExit("Could not connect to the clinic database.") from None
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
