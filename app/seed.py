from datetime import datetime, time, timedelta
from hashlib import sha256

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_database_url
from app.database import CLINIC_TZ, Database, now
from app.domain import Role
from app.models import AccessToken, Appointment, Doctor, Schedule, Specialty, User


def seed_demo_data(session: Session, *, include_visit: bool = True) -> None:
    """Insert fictional demo accounts once, preserving subsequent application data."""
    session.execute(text("SELECT pg_advisory_xact_lock(225006)"))
    for specialty_id, name in [(1, "General Practice"), (2, "Cardiology")]:
        existing = session.get(Specialty, specialty_id)
        if existing is None:
            session.add(Specialty(id=specialty_id, name=name))
    session.flush()

    demo_users = [
        (1, "Dana Omar", Role.PATIENT, "demo-patient"),
        (2, "Arman Iskakov", Role.PATIENT, "demo-patient-2"),
        (3, "Aida Sadykova", Role.DOCTOR, "demo-doctor"),
        (4, "Timur Saparov", Role.DOCTOR, "demo-doctor-2"),
        (5, "Clinic Admin", Role.ADMIN, "demo-admin"),
    ]
    for user_id, name, role, token in demo_users:
        user = session.get(User, user_id)
        if user is None:
            session.add(User(id=user_id, name=name, role=role))
        elif user.name != name or user.role != role:
            raise ValueError("Demo account IDs are occupied by different users.")
        session.flush()
        token_hash = sha256(token.encode()).hexdigest()
        saved_token = session.get(AccessToken, token_hash)
        if saved_token is None:
            session.add(AccessToken(token_hash=token_hash, user_id=user_id))
        elif saved_token.user_id != user_id:
            raise ValueError("A demo token belongs to a different user.")

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
    database = Database(get_database_url())
    try:
        with database.session_factory.begin() as session:
            seed_demo_data(session)
        print("Fictional demo accounts are ready. Existing data was preserved.")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
