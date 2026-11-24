from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from json import dumps
from threading import Barrier
import unittest
from pathlib import Path
from uuid import uuid4

import jwt
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.config import get_database_url
from app.database import CLINIC_TZ, Database
from app.domain import AppointmentStatus, Role
from app.main import create_app
from app.models import AccessToken, Appointment, Doctor, Schedule, Specialty, User
from app.security import create_access_token, hash_password
from app.seed import seed_demo_data


PATIENT_ID = 1
SECOND_PATIENT_ID = 2
DOCTOR_ID = 3
SECOND_DOCTOR_ID = 4
ADMIN_ID = 5
DEMO_PASSWORD = "only-for-clinic-tests"


class ClinicApiTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 16, 8, 0, tzinfo=CLINIC_TZ)
        self.schema = "test_clinic_" + uuid4().hex
        self.admin_database = Database(get_database_url())
        self.addCleanup(self.admin_database.dispose)
        with self.admin_database.engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addCleanup(self.drop_test_schema)
        self.database = Database(get_database_url(), clock=lambda: self.now, schema=self.schema)
        self.addCleanup(self.database.dispose)
        self.migrate("head")
        with self.database.session_factory.begin() as session:
            seed_demo_data(session, demo_password=DEMO_PASSWORD, include_visit=False)
        self.app = create_app(database=self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def drop_test_schema(self):
        if not self.schema.startswith("test_clinic_") or len(self.schema) != 44:
            raise AssertionError("Refusing to drop an unexpected schema")
        if not self.schema.removeprefix("test_clinic_").isalnum():
            raise AssertionError("Refusing to drop an unsafe schema")
        with self.admin_database.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))

    def migrate(self, revision, downgrade=False):
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        with self.database.engine.begin() as connection:
            config.attributes["connection"] = connection
            operation = command.downgrade if downgrade else command.upgrade
            operation(config, revision)

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    def auth(self, user_id):
        return self.bearer(create_access_token(user_id, self.app.state.jwt_secret))

    def login(self, email, password=DEMO_PASSWORD):
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        credentials = self.expect(response, 200)
        self.assertEqual(credentials["token_type"], "bearer")
        return credentials["access_token"]

    def expect(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        if status >= 400:
            error = response.json()["error"]
            self.assertTrue(error["code"])
            self.assertTrue(error["message"])
        if status == 204:
            self.assertEqual(response.content, b"")
            return None
        return response.json()

    def book(self, doctor_id=3, hour=9, minute=0, patient=PATIENT_ID, day=16):
        starts_at = datetime(2026, 11, day, hour, minute, tzinfo=CLINIC_TZ)
        return self.client.post(
            "/appointments",
            headers=self.auth(patient),
            json={"doctor_id": doctor_id, "starts_at": starts_at.isoformat()},
        )

    def slots(self, date="2026-11-16", doctor_id=3):
        return self.client.get(f"/doctors/{doctor_id}/slots", params={"date": date})

    def test_docs_and_openapi(self):
        self.expect(self.client.get("/"), 200)
        docs = self.client.get("/docs")
        self.assertEqual(docs.status_code, 200)
        self.assertIn("SwaggerUIBundle", docs.text)
        schema = self.expect(self.client.get("/openapi.json"), 200)
        self.assertIn("post", schema["paths"]["/auth/register"])
        self.assertIn("post", schema["paths"]["/auth/login"])
        self.assertTrue(schema["paths"]["/appointments"]["get"]["security"])
        self.assertTrue(
            any(
                scheme["type"] == "http"
                and scheme["scheme"] == "bearer"
                and scheme.get("bearerFormat") == "JWT"
                for scheme in schema["components"]["securitySchemes"].values()
            )
        )

    def test_registration_creates_a_patient_and_stores_only_a_salted_hash(self):
        payload = {
            "name": "New Patient",
            "email": "New.Patient@Example.com",
            "password": DEMO_PASSWORD,
        }
        created = self.expect(self.client.post("/auth/register", json=payload), 201)
        self.assertEqual(set(created), {"id", "name", "email", "role"})
        self.assertEqual(created["name"], payload["name"])
        self.assertEqual(created["email"], "new.patient@example.com")
        self.assertEqual(created["role"], "patient")

        with self.database.session_factory() as session:
            user = session.get(User, created["id"])
            demo_patient = session.get(User, PATIENT_ID)
            self.assertEqual(user.email, created["email"])
            self.assertTrue(user.password_hash.startswith("$argon2id$"))
            self.assertNotEqual(user.password_hash, payload["password"])
            self.assertNotEqual(user.password_hash, demo_patient.password_hash)
            self.assertEqual(session.scalar(select(func.count()).select_from(AccessToken)), 0)

        token = self.login(payload["email"].upper())
        visits = self.expect(self.client.get("/appointments", headers=self.bearer(token)), 200)
        self.assertEqual(visits, [])

    def test_registration_rejects_invalid_input_and_duplicate_email(self):
        valid = {"name": "New Patient", "email": "new@example.com", "password": DEMO_PASSWORD}
        cases = {
            "missing password": {"name": valid["name"], "email": valid["email"]},
            "short password": {**valid, "password": "short"},
            "invalid email": {**valid, "email": "invalid-email"},
            "privileged role": {**valid, "role": "admin"},
        }
        for case, payload in cases.items():
            with self.subTest(case=case):
                self.expect(self.client.post("/auth/register", json=payload), 422)

        duplicate = {**valid, "email": "PATIENT@EXAMPLE.COM"}
        error = self.expect(self.client.post("/auth/register", json=duplicate), 409)["error"]
        self.assertEqual(error["code"], "email_taken")

    def test_auth_rejects_invalid_unicode_input(self):
        payload = {"email": "patient@example.com", "password": "invalid-unicode-\ud800"}
        invalid_json_password = dumps(payload)
        self.expect(self.client.post(
            "/auth/login", content=invalid_json_password, headers={"Content-Type": "application/json"}
        ), 422)
        self.expect(self.client.post(
            "/auth/register",
            content=dumps({**payload, "email": "unicode@example.com", "name": "Test Patient"}),
            headers={"Content-Type": "application/json"},
        ), 422)

        # Lowercasing the email expands each dotted capital I into two code points.
        domain = ".".join(["a" * 63, "b" * 63, "c" * 63, "com"])
        long_email = "\u0130" * 20 + "@" + domain
        self.expect(self.client.post("/auth/register", json={
            "name": "Test Patient", "email": long_email, "password": DEMO_PASSWORD,
        }), 422)

    def test_concurrent_registration_creates_only_one_account(self):
        barrier = Barrier(2, timeout=10)

        def register(email):
            with TestClient(self.app) as client:
                barrier.wait()
                return client.post("/auth/register", json={
                    "name": "Test Patient", "email": email, "password": DEMO_PASSWORD,
                })

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(register, ("Same@example.com", "same@example.com")))
        self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
        conflict = next(response for response in responses if response.status_code == 409)
        self.assertEqual(conflict.json()["error"]["code"], "email_taken")

    def test_login_rejects_wrong_password_and_unknown_email_consistently(self):
        wrong_password = self.client.post(
            "/auth/login", json={"email": "patient@example.com", "password": "wrong-password"}
        )
        unknown_email = self.client.post(
            "/auth/login", json={"email": "unknown@example.com", "password": DEMO_PASSWORD}
        )
        self.assertEqual(self.expect(wrong_password, 401), self.expect(unknown_email, 401))
        self.assertEqual(wrong_password.headers["WWW-Authenticate"], "Bearer")

    def test_protected_route_rejects_missing_invalid_and_expired_tokens(self):
        response = self.client.get("/appointments")
        self.expect(response, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

        now = datetime.now(timezone.utc)
        secret = self.app.state.jwt_secret
        claims = {
            "sub": str(PATIENT_ID),
            "iss": "clinic-appointment-api",
            "iat": now - timedelta(minutes=2),
            "exp": now + timedelta(minutes=2),
        }
        invalid_tokens = {
            "malformed": "not-a-jwt",
            "wrong signature": jwt.encode(claims, uuid4().hex, algorithm="HS256"),
            "expired": jwt.encode(
                {**claims, "exp": now - timedelta(minutes=1)}, secret, algorithm="HS256"
            ),
            "missing expiration": jwt.encode(
                {"sub": claims["sub"], "iss": claims["iss"], "iat": claims["iat"]},
                secret,
                algorithm="HS256",
            ),
            "unknown user": create_access_token(99999, secret),
        }
        for case, token in invalid_tokens.items():
            with self.subTest(case=case):
                response = self.client.get("/appointments", headers=self.bearer(token))
                self.expect(response, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

        self.expect(
            self.client.get("/appointments", headers=self.bearer(self.login("patient@example.com"))),
            200,
        )

    def test_logged_in_users_respect_role_and_appointment_ownership(self):
        patient = self.bearer(self.login("patient@example.com"))
        second_patient = self.bearer(self.login("patient2@example.com"))
        doctor = self.bearer(self.login("doctor@example.com"))
        admin = self.bearer(self.login("admin@example.com"))
        payload = {"doctor_id": DOCTOR_ID, "starts_at": "2026-11-16T09:00:00+05:00"}
        visit = self.expect(self.client.post("/appointments", headers=patient, json=payload), 201)
        cancel_path = f"/appointments/{visit['id']}"

        self.assertEqual(self.expect(self.client.get("/appointments", headers=second_patient), 200), [])
        self.expect(
            self.client.patch(cancel_path, headers=second_patient, json={"status": "cancelled"}),
            403,
        )
        self.expect(self.client.get("/doctors/me/schedule", headers=patient), 403)
        self.expect(self.client.get("/doctors/me/schedule", headers=doctor), 200)
        self.expect(self.client.post("/specialties", headers=doctor, json={"name": "Dermatology"}), 403)
        self.expect(self.client.post("/specialties", headers=admin, json={"name": "Dermatology"}), 201)
        self.expect(
            self.client.patch(cancel_path, headers=patient, json={"status": "cancelled"}), 200
        )

    def test_public_directory_filters(self):
        specialties = self.expect(self.client.get("/specialties"), 200)
        self.assertEqual({item["id"] for item in specialties}, {1, 2})
        doctors = self.expect(
            self.client.get("/doctors", params={"specialty_id": 2}), 200
        )
        self.assertEqual([doctor["id"] for doctor in doctors], [4])
        doctor = self.expect(self.client.get("/doctors/3"), 200)
        doctors = self.expect(
            self.client.get("/doctors", params={"q": doctor["name"].upper()}), 200
        )
        self.assertEqual([item["id"] for item in doctors], [3])
        self.assertNotIn("access_token", doctor)
        self.expect(self.client.get("/doctors/999"), 404)

    def test_specialty_lifecycle_validation_and_authorization(self):
        admin = self.auth(ADMIN_ID)
        payload = {"name": "Dermatology"}
        self.expect(self.client.post("/specialties", json=payload), 401)
        self.expect(
            self.client.post("/specialties", headers=self.bearer("wrong-token"), json=payload),
            401,
        )
        self.expect(
            self.client.post("/specialties", headers=self.auth(PATIENT_ID), json=payload),
            403,
        )
        self.expect(self.client.post("/specialties", headers=admin, json={"name": " "}), 422)
        specialty = self.expect(self.client.post("/specialties", headers=admin, json=payload), 201)
        self.expect(
            self.client.post("/specialties", headers=admin, json={"name": "dermatology"}), 409
        )
        url = f"/specialties/{specialty['id']}"
        self.expect(self.client.patch(url, headers=admin, json={"name": "Cardiology"}), 409)
        updated = self.expect(
            self.client.patch(url, headers=admin, json={"name": "Pediatric Dermatology"}), 200
        )
        self.assertEqual(updated["name"], "Pediatric Dermatology")
        self.expect(self.client.delete("/specialties/1", headers=admin), 409)
        self.expect(self.client.delete(url, headers=admin), 204)
        self.expect(self.client.delete(url, headers=admin), 404)

    def test_doctor_creation_and_blocking(self):
        admin = self.auth(ADMIN_ID)
        payload = {
            "name": "Dr. Morgan",
            "specialty_id": 999,
            "email": "morgan@example.com",
            "password": DEMO_PASSWORD,
        }
        self.expect(self.client.post("/doctors", headers=admin, json=payload), 404)
        payload["specialty_id"] = 1
        doctor = self.expect(self.client.post("/doctors", headers=admin, json=payload), 201)
        for private_field in ("email", "password", "password_hash", "access_token"):
            self.assertNotIn(private_field, doctor)
        public_doctor = self.expect(self.client.get(f"/doctors/{doctor['id']}"), 200)
        self.assertEqual(public_doctor, doctor)
        token = self.login(payload["email"], payload["password"])
        schedule = self.expect(
            self.client.get("/doctors/me/schedule", headers=self.bearer(token)),
            200,
        )
        self.assertEqual(schedule["schedule"], [])

        appointment = self.expect(self.book(), 201)
        self.expect(
            self.client.patch("/doctors/3", headers=admin, json={"is_active": False}), 200
        )
        self.expect(self.client.get("/doctors/3"), 404)
        self.expect(self.slots(), 404)
        self.expect(self.book(minute=30), 409)
        appointments = self.expect(
            self.client.get("/appointments", headers=self.auth(DOCTOR_ID)), 200
        )
        self.assertIn(appointment["id"], {item["id"] for item in appointments})
        self.expect(
            self.client.patch("/doctors/3", headers=admin, json={"is_active": True}), 200
        )
        self.expect(self.book(minute=30), 201)

    def test_recurring_slots_and_day_off(self):
        doctor = self.auth(DOCTOR_ID)
        response = self.expect(self.slots(), 200)
        self.assertEqual(len(response), 16)
        self.assertEqual(datetime.fromisoformat(response[0]["starts_at"]).hour, 9)
        self.assertEqual(datetime.fromisoformat(response[-1]["ends_at"]).hour, 17)
        self.assertEqual(self.expect(self.slots(date="2026-11-21"), 200), [])
        self.assertEqual(self.expect(self.slots(date="2026-11-15"), 200), [])
        self.expect(self.slots(date="bad-date"), 422)

        updated = {"start": "10:00", "end": "11:00", "slot_minutes": 20}
        self.expect(
            self.client.put("/doctors/me/schedule/0", headers=doctor, json=updated), 200
        )
        self.assertEqual(len(self.expect(self.slots(), 200)), 3)
        for path, payload in [
            ("/doctors/me/schedule/7", updated),
            ("/doctors/me/schedule/0", {**updated, "end": "09:00"}),
            ("/doctors/me/schedule/0", {**updated, "end": "11:10"}),
        ]:
            with self.subTest(path=path, payload=payload):
                self.expect(self.client.put(path, headers=doctor, json=payload), 422)

        day_off = {"date": "2026-11-16"}
        self.expect(self.client.post("/doctors/me/days-off", headers=doctor, json=day_off), 201)
        self.expect(self.client.post("/doctors/me/days-off", headers=doctor, json=day_off), 409)
        self.assertEqual(self.expect(self.slots(), 200), [])
        self.expect(self.book(hour=10), 409)
        schedule = self.expect(self.client.get("/doctors/me/schedule", headers=doctor), 200)
        self.assertIn(day_off["date"], schedule["days_off"])
        path = f"/doctors/me/days-off/{day_off['date']}"
        self.expect(self.client.delete(path, headers=doctor), 204)
        self.expect(self.client.delete(path, headers=doctor), 404)
        self.assertEqual(len(self.expect(self.slots(), 200)), 3)

    def test_schedule_changes_preserve_existing_reservations(self):
        doctor = self.auth(DOCTOR_ID)
        self.expect(self.book(), 201)
        self.expect(
            self.client.put(
                "/doctors/me/schedule/0",
                headers=doctor,
                json={"start": "10:00", "end": "11:00", "slot_minutes": 30},
            ),
            409,
        )
        self.expect(
            self.client.post("/doctors/me/days-off", headers=doctor, json={"date": "2026-11-16"}),
            409,
        )
        slots = self.expect(self.slots(), 200)
        self.assertEqual(len(slots), 15)
        self.assertEqual(datetime.fromisoformat(slots[0]["starts_at"]).minute, 30)

    def test_booking_conflicts_validation_and_ownership(self):
        patient = self.auth(PATIENT_ID)
        second_patient = self.auth(SECOND_PATIENT_ID)
        appointment = self.expect(self.book(), 201)
        self.expect(self.book(patient=SECOND_PATIENT_ID), 409)
        self.expect(self.book(doctor_id=4), 409)
        self.expect(self.book(minute=15), 409)
        self.expect(self.book(hour=7), 409)
        self.expect(self.book(doctor_id=999), 404)
        self.expect(
            self.client.post(
                "/appointments",
                headers=patient,
                json={"doctor_id": 3, "starts_at": "2026-11-16T10:00:00"},
            ),
            422,
        )
        self.expect(
            self.client.post(
                "/appointments",
                headers=patient,
                json={"doctor_id": 3, "starts_at": "2026-11-16T04:00:00Z"},
            ),
            409,
        )

        appointments = self.expect(self.client.get("/appointments", headers=second_patient), 200)
        self.assertNotIn(appointment["id"], {item["id"] for item in appointments})
        path = f"/appointments/{appointment['id']}"
        cancel = {"status": "cancelled"}
        self.expect(self.client.patch(path, headers=second_patient, json=cancel), 403)
        self.expect(self.client.patch(path, headers=patient, json={"status": "done"}), 422)
        self.expect(self.client.patch("/appointments/999", headers=patient, json=cancel), 404)
        self.assertEqual(
            self.expect(self.client.patch(path, headers=patient, json=cancel), 200)["status"],
            "cancelled",
        )
        self.expect(self.client.patch(path, headers=patient, json=cancel), 409)
        rebooked = self.expect(self.book(patient=SECOND_PATIENT_ID), 201)
        self.assertNotEqual(rebooked["id"], appointment["id"])
        appointments = self.expect(
            self.client.get("/appointments", headers=patient, params={"status": "cancelled"}),
            200,
        )
        self.assertEqual([item["id"] for item in appointments], [appointment["id"]])
        self.expect(self.client.get("/appointments", headers=patient, params={"status": "typo"}), 422)

    def test_same_slot_concurrent_booking_has_one_winner(self):
        barrier = Barrier(2, timeout=5)

        def attempt(patient_id):
            with TestClient(self.app) as client:
                barrier.wait()
                return client.post(
                    "/appointments",
                    headers=self.auth(patient_id),
                    json={"doctor_id": 3, "starts_at": "2026-11-16T09:00:00+05:00"},
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, (PATIENT_ID, SECOND_PATIENT_ID)))
        self.assertEqual(sorted(statuses), [201, 409])

    def test_consultation_and_patient_history(self):
        patient = self.auth(PATIENT_ID)
        doctor = self.auth(DOCTOR_ID)
        second_doctor = self.auth(SECOND_DOCTOR_ID)
        first = self.expect(self.book(), 201)
        path = f"/appointments/{first['id']}/medical-record"
        payload = {"diagnosis": "Fictional observation A", "notes": "Follow up in two weeks."}
        self.expect(self.client.post(path, headers=patient, json=payload), 403)
        self.expect(self.client.post(path, headers=second_doctor, json=payload), 403)
        self.expect(self.client.post(path, headers=doctor, json=payload), 409)

        history = "/patients/1/medical-records"
        self.expect(self.client.get(history, headers=second_doctor), 403)
        self.expect(self.client.get(history, headers=self.auth(SECOND_PATIENT_ID)), 403)
        self.expect(self.client.get(history, headers=self.auth(ADMIN_ID)), 403)
        self.assertEqual(self.expect(self.client.get(history, headers=doctor), 200), [])

        second = self.expect(self.book(doctor_id=4, minute=30), 201)
        self.now = self.now + timedelta(hours=2)
        self.expect(
            self.client.patch(
                f"/appointments/{first['id']}", headers=patient, json={"status": "cancelled"}
            ),
            409,
        )
        self.expect(self.client.post(path, headers=doctor, json={"diagnosis": ""}), 422)
        record = self.expect(self.client.post(path, headers=doctor, json=payload), 201)
        self.assertEqual(record["diagnosis"], payload["diagnosis"])
        self.expect(self.client.post(path, headers=doctor, json=payload), 409)
        self.expect(
            self.client.post(
                f"/appointments/{second['id']}/medical-record",
                headers=second_doctor,
                json={"diagnosis": "Fictional observation B"},
            ),
            201,
        )
        records = self.expect(self.client.get(history, headers=patient), 200)
        self.assertEqual({item["appointment_id"] for item in records}, {first["id"], second["id"]})
        records = self.expect(self.client.get(history, headers=doctor), 200)
        self.assertEqual([item["appointment_id"] for item in records], [first["id"]])
        records = self.expect(self.client.get(history, headers=second_doctor), 200)
        self.assertEqual([item["appointment_id"] for item in records], [second["id"]])
        appointments = self.expect(
            self.client.get("/appointments", headers=patient, params={"status": "done"}), 200
        )
        self.assertEqual({item["id"] for item in appointments}, {first["id"], second["id"]})

    def test_persistence_survives_engine_and_application_recreation(self):
        appointment = self.expect(self.book(), 201)
        self.client.close()
        self.database.dispose()
        reopened = Database(get_database_url(), clock=lambda: self.now, schema=self.schema)
        try:
            with TestClient(create_app(database=reopened)) as client:
                response = client.get("/appointments", headers=self.auth(PATIENT_ID))
                visits = self.expect(response, 200)
                self.assertEqual([visit["id"] for visit in visits], [appointment["id"]])
        finally:
            reopened.dispose()

    def test_independent_sessions_prevent_patient_overlap(self):
        barrier = Barrier(2, timeout=10)

        def attempt(doctor_id):
            independent = Database(get_database_url(), clock=lambda: self.now, schema=self.schema)
            try:
                with TestClient(create_app(database=independent)) as client:
                    barrier.wait()
                    return client.post(
                        "/appointments", headers=self.auth(PATIENT_ID),
                        json={"doctor_id": doctor_id, "starts_at": "2026-11-16T09:00:00+05:00"},
                    ).status_code
            finally:
                independent.dispose()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, (3, 4)))
        self.assertEqual(sorted(statuses), [201, 409])

    def test_database_constraints_rollback_and_relationships(self):
        appointment = self.expect(self.book(), 201)
        start = datetime(2026, 11, 16, 9, tzinfo=CLINIC_TZ)
        bad_values = [
            Specialty(name="cardiology"),
            User(name=" ", role=Role.PATIENT),
            User(name="Partial Credentials", role=Role.PATIENT, email="partial@example.com"),
            User(
                name="Duplicate Email",
                role=Role.PATIENT,
                email="PATIENT@EXAMPLE.COM",
                password_hash=hash_password(DEMO_PASSWORD),
            ),
            Doctor(id=99999, specialty_id=1),
            Appointment(doctor_id=3, patient_id=2, starts_at=start, ends_at=start + timedelta(minutes=30)),
            Appointment(doctor_id=4, patient_id=2, starts_at=start, ends_at=start),
        ]
        with self.database.session_factory.begin() as session:
            for value in bad_values:
                with self.subTest(model=type(value).__name__):
                    with self.assertRaises(IntegrityError):
                        with session.begin_nested():
                            session.add(value)
                            session.flush()
            saved = session.get(Appointment, appointment["id"])
            self.assertEqual(saved.patient.id, 1)
            self.assertEqual(saved.doctor.specialty.name, "General Practice")
            self.assertEqual(len(saved.doctor.appointments), 1)
            self.assertIsNone(saved.medical_record)
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 5)
            saved.status = AppointmentStatus.CANCELLED
            session.flush()
            replacement = Appointment(
                doctor_id=3, patient_id=2, starts_at=start, ends_at=start + timedelta(minutes=30)
            )
            session.add(replacement)
            session.flush()
            self.assertNotEqual(replacement.id, saved.id)

    def test_concurrent_schedule_change_and_booking_remain_consistent(self):
        barrier = Barrier(2, timeout=10)

        def attempt(operation):
            independent = Database(get_database_url(), clock=lambda: self.now, schema=self.schema)
            try:
                with TestClient(create_app(database=independent)) as client:
                    barrier.wait()
                    if operation == "schedule":
                        return client.put(
                            "/doctors/me/schedule/0", headers=self.auth(DOCTOR_ID),
                            json={"start": "10:00", "end": "17:00", "slot_minutes": 30},
                        ).status_code
                    return client.post(
                        "/appointments", headers=self.auth(PATIENT_ID),
                        json={"doctor_id": 3, "starts_at": "2026-11-16T09:00:00+05:00"},
                    ).status_code
            finally:
                independent.dispose()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, ("schedule", "booking")))
        self.assertIn(statuses, ([200, 409], [409, 201]))
        with self.database.session_factory() as session:
            schedule = session.get(Schedule, (3, 0))
            count = session.scalar(select(func.count()).select_from(Appointment))
            self.assertEqual((schedule.start.hour, count), (10, 0) if statuses[0] == 200 else (9, 1))

    def test_failed_transaction_leaves_no_partial_doctor_account(self):
        payload = {
            "name": "Rollback Doctor",
            "specialty_id": 99999,
            "email": "rollback@example.com",
            "password": DEMO_PASSWORD,
        }
        with self.database.session_factory() as session:
            user_count = session.scalar(select(func.count()).select_from(User))
            doctor_count = session.scalar(select(func.count()).select_from(Doctor))
        self.expect(
            self.client.post("/doctors", headers=self.auth(ADMIN_ID), json=payload),
            404,
        )
        with self.database.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), user_count)
            self.assertEqual(session.scalar(select(func.count()).select_from(Doctor)), doctor_count)
        with self.assertRaises(IntegrityError):
            with self.database.session_factory.begin() as session:
                user = User(
                    name=payload["name"],
                    role=Role.DOCTOR,
                    email=payload["email"],
                    password_hash=hash_password(DEMO_PASSWORD),
                )
                session.add(user)
                session.flush()
                session.add(Doctor(id=user.id, specialty_id=payload["specialty_id"]))
                session.flush()
        with self.database.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), user_count)
            self.assertEqual(session.scalar(select(func.count()).select_from(Doctor)), doctor_count)

    def test_seed_is_idempotent_and_preserves_edits(self):
        self.expect(self.book(), 201)
        self.expect(self.client.patch("/doctors/3", headers=self.auth(ADMIN_ID),
                                     json={"is_active": False}), 200)
        with self.database.session_factory.begin() as session:
            saved_hash = session.get(User, PATIENT_ID).password_hash
            schedule = session.get(Schedule, (4, 0))
            session.delete(schedule)
            seed_demo_data(session, demo_password=DEMO_PASSWORD, include_visit=False)
            seed_demo_data(session, demo_password="different-test-password", include_visit=False)
        with self.database.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 5)
            self.assertEqual(session.scalar(select(func.count(User.password_hash))), 5)
            self.assertEqual(session.get(User, PATIENT_ID).password_hash, saved_hash)
            self.assertEqual(session.scalar(select(func.count()).select_from(AccessToken)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Appointment)), 1)
            self.assertFalse(session.get(Doctor, 3).is_active)
            self.assertIsNone(session.get(Schedule, (4, 0)))

    def test_migration_downgrade_and_upgrade(self):
        self.migrate("base", downgrade=True)
        with self.database.engine.connect() as connection:
            tables = inspect(connection).get_table_names(schema=self.schema)
            self.assertNotIn("appointments", tables)
            self.assertNotIn("users", tables)
        self.migrate("head")
        with self.database.session_factory.begin() as session:
            seed_demo_data(session, demo_password=DEMO_PASSWORD, include_visit=False)
        self.expect(self.book(), 201)

    def test_auth_migration_preserves_existing_accounts_and_appointments(self):
        appointment = self.expect(self.book(), 201)
        legacy_token = "demo-patient"
        legacy_hash = sha256(legacy_token.encode()).hexdigest()
        with self.database.session_factory.begin() as session:
            session.add(AccessToken(token_hash=legacy_hash, user_id=PATIENT_ID))
        self.migrate("0001_clinic_schema", downgrade=True)
        self.migrate("head")

        with self.database.session_factory() as session:
            patient = session.get(User, PATIENT_ID)
            visit = session.get(Appointment, appointment["id"])
            self.assertEqual(patient.role, Role.PATIENT)
            self.assertIsNone(patient.email)
            self.assertIsNone(patient.password_hash)
            self.assertEqual(visit.patient_id, patient.id)
            self.assertIsNotNone(session.get(AccessToken, legacy_hash))
        self.expect(self.client.get("/appointments", headers=self.auth(PATIENT_ID)), 401)
        with self.database.session_factory.begin() as session:
            seed_demo_data(session, demo_password=DEMO_PASSWORD, include_visit=False)

        self.expect(self.client.get("/appointments", headers=self.bearer(legacy_token)), 401)
        token = self.login("patient@example.com")
        visits = self.expect(self.client.get("/appointments", headers=self.bearer(token)), 200)
        self.assertEqual([visit["id"] for visit in visits], [appointment["id"]])

    def test_null_character_inputs_are_rejected_without_poisoning_sessions(self):
        admin = self.auth(ADMIN_ID)
        self.expect(self.client.post("/specialties", headers=admin, json={"name": "Bad\u0000Name"}), 422)
        self.expect(self.client.post("/doctors", headers=admin,
                                     json={
                                         "name": "Bad\u0000Name",
                                         "specialty_id": 1,
                                         "email": "invalid-name@example.com",
                                         "password": DEMO_PASSWORD,
                                     }), 422)
        self.expect(self.client.get("/doctors", params={"q": "bad\u0000query"}), 422)
        appointment = self.expect(self.book(), 201)
        self.now += timedelta(hours=2)
        path = f"/appointments/{appointment['id']}/medical-record"
        for payload in [
            {"diagnosis": "Bad\u0000Diagnosis"},
            {"diagnosis": "Valid observation", "notes": "Bad\u0000Note"},
        ]:
            with self.subTest(payload=payload):
                self.expect(self.client.post(path, headers=self.auth(DOCTOR_ID), json=payload), 422)
        self.expect(self.client.get("/doctors"), 200)
        self.expect(self.client.post(path, headers=self.auth(DOCTOR_ID),
                                     json={"diagnosis": "Valid fictional observation"}), 201)

    def test_statistics_respect_role_and_date_filters(self):
        admin = self.auth(ADMIN_ID)
        appointment = self.expect(self.book(), 201)
        self.expect(self.book(day=17), 201)
        self.expect(
            self.client.patch(
                f"/appointments/{appointment['id']}",
                headers=self.auth(PATIENT_ID),
                json={"status": "cancelled"},
            ),
            200,
        )
        self.expect(self.client.get("/statistics"), 401)
        self.expect(self.client.get("/statistics", headers=self.auth(DOCTOR_ID)), 403)
        stats = self.expect(
            self.client.get(
                "/statistics",
                headers=admin,
                params={"start_date": "2026-11-16", "end_date": "2026-11-16"},
            ),
            200,
        )
        self.assertEqual(stats["total_appointments"], 1)
        self.assertEqual(stats["appointments_by_status"], {"booked": 0, "cancelled": 1, "done": 0, "no_show": 0})
        self.expect(
            self.client.get(
                "/statistics",
                headers=admin,
                params={"start_date": "2026-11-17", "end_date": "2026-11-16"},
            ),
            422,
        )

    def test_reschedule_offers_released_slot_to_first_waitlisted_patient(self):
        original = self.expect(self.book(), 201)
        self.expect(self.book(minute=30), 201)
        third_user = self.expect(self.client.post("/auth/register", json={
            "name": "Another Patient", "email": "another@example.com", "password": DEMO_PASSWORD,
        }), 201)
        waitlist_request = {"doctor_id": DOCTOR_ID, "date": "2026-11-16"}
        first = self.expect(self.client.post(
            "/waitlist", headers=self.auth(SECOND_PATIENT_ID), json=waitlist_request
        ), 201)
        self.expect(self.client.post(
            "/waitlist", headers=self.auth(third_user["id"]), json=waitlist_request
        ), 201)

        reschedule = f"/appointments/{original['id']}/reschedule"
        self.expect(self.client.patch(reschedule, headers=self.auth(PATIENT_ID), json={
            "starts_at": "2026-11-16T09:30:00+05:00",
        }), 409)
        unchanged = self.expect(self.client.get("/appointments", headers=self.auth(PATIENT_ID)), 200)
        self.assertEqual(unchanged[0]["starts_at"], original["starts_at"])
        self.expect(self.client.patch(reschedule, headers=self.auth(PATIENT_ID), json={
            "starts_at": "2026-11-17T09:00:00+05:00",
        }), 200)

        notices = self.expect(self.client.get("/notifications", headers=self.auth(SECOND_PATIENT_ID)), 200)
        self.assertEqual([(n["kind"], n["subject_id"]) for n in notices], [("waitlist_offer", first["id"])])
        self.assertEqual(
            self.expect(self.client.get("/notifications", headers=self.auth(third_user["id"])), 200), []
        )
        read = f"/notifications/{notices[0]['id']}/read"
        self.expect(self.client.patch(read, headers=self.auth(PATIENT_ID)), 404)
        self.expect(self.client.patch(read, headers=self.auth(SECOND_PATIENT_ID)), 204)
        accept = f"/waitlist/{first['id']}/accept"
        self.expect(self.client.post(accept, headers=self.auth(third_user["id"])), 403)
        booked = self.expect(self.client.post(accept, headers=self.auth(SECOND_PATIENT_ID)), 201)
        self.assertEqual(booked["starts_at"], original["starts_at"])
        self.assertNotEqual(booked["id"], original["id"])
        self.expect(self.client.post(accept, headers=self.auth(SECOND_PATIENT_ID)), 409)

    def test_intake_attendance_and_booked_follow_up_link_previous_record(self):
        visit = self.expect(self.book(), 201)
        path = f"/appointments/{visit['id']}"
        intake = {"reason": "Discuss a sample concern", "questions": "What happens next?"}
        self.expect(self.client.put(f"{path}/intake", headers=self.auth(PATIENT_ID), json=intake), 200)
        self.expect(self.client.get(f"{path}/intake", headers=self.auth(SECOND_DOCTOR_ID)), 403)
        seen = self.expect(self.client.get(f"{path}/intake", headers=self.auth(DOCTOR_ID)), 200)
        self.assertEqual(seen["questions"], intake["questions"])
        self.expect(self.client.patch(
            f"{path}/attendance", headers=self.auth(DOCTOR_ID), json={"status": "arrived"}
        ), 409)

        self.now = self.now.replace(hour=10)
        arrived = self.expect(self.client.patch(
            f"{path}/attendance", headers=self.auth(DOCTOR_ID), json={"status": "arrived"}
        ), 200)
        self.assertIsNotNone(arrived["arrived_at"])
        notes = {"diagnosis": "Fictional note", "notes": "Discuss a follow-up."}
        self.expect(self.client.post(f"{path}/medical-record", headers=self.auth(DOCTOR_ID), json=notes), 201)
        recommendation = self.expect(self.client.post(
            f"{path}/follow-up", headers=self.auth(DOCTOR_ID),
            json={"start_date": "2026-11-17", "end_date": "2026-11-19"},
        ), 201)
        notifications = self.expect(self.client.get("/notifications", headers=self.auth(PATIENT_ID)), 200)
        self.assertIn(("follow_up", recommendation["id"]), {(n["kind"], n["subject_id"]) for n in notifications})
        follow_up_path = f"/follow-ups/{recommendation['id']}/book"
        booking = {"starts_at": "2026-11-18T09:00:00+05:00"}
        self.expect(self.client.post(follow_up_path, headers=self.auth(SECOND_PATIENT_ID), json=booking), 403)
        self.expect(self.client.post(follow_up_path, headers=self.auth(PATIENT_ID), json={
            "starts_at": "2026-11-20T09:00:00+05:00",
        }), 409)
        follow_up = self.expect(self.client.post(follow_up_path, headers=self.auth(PATIENT_ID), json=booking), 201)
        self.assertEqual(follow_up["doctor_id"], DOCTOR_ID)
        self.assertEqual(follow_up["previous_appointment_id"], visit["id"])
        previous = self.expect(self.client.get(f"{path}/medical-record", headers=self.auth(DOCTOR_ID)), 200)
        self.assertEqual(previous["diagnosis"], notes["diagnosis"])
        self.expect(self.client.get(f"{path}/medical-record", headers=self.auth(SECOND_DOCTOR_ID)), 403)
        self.expect(self.client.post(follow_up_path, headers=self.auth(PATIENT_ID), json=booking), 409)

    def test_no_show_remains_terminal_and_has_no_consultation(self):
        visit = self.expect(self.book(), 201)
        path = f"/appointments/{visit['id']}"
        self.now = self.now.replace(hour=10)
        no_show = self.expect(self.client.patch(
            f"{path}/attendance", headers=self.auth(DOCTOR_ID), json={"status": "no_show"}
        ), 200)
        self.assertEqual(no_show["status"], "no_show")
        self.assertIsNone(no_show["arrived_at"])
        self.expect(self.client.patch(
            f"{path}/attendance", headers=self.auth(DOCTOR_ID), json={"status": "arrived"}
        ), 409)
        self.expect(self.client.post(
            f"{path}/medical-record", headers=self.auth(DOCTOR_ID), json={"diagnosis": "Fictional"}
        ), 409)
        self.expect(self.client.get(f"{path}/medical-record", headers=self.auth(PATIENT_ID)), 404)
        self.expect(self.client.post(f"{path}/review", headers=self.auth(PATIENT_ID), json={"rating": 4}), 409)
        self.expect(self.client.post(f"{path}/certificate", headers=self.auth(PATIENT_ID)), 409)
        visits = self.expect(self.client.get("/appointments?status=no_show", headers=self.auth(PATIENT_ID)), 200)
        self.assertEqual([row["id"] for row in visits], [visit["id"]])

    def test_moderated_review_and_staff_approved_certificate(self):
        visit = self.expect(self.book(), 201)
        path = f"/appointments/{visit['id']}"
        self.now = self.now.replace(hour=10)
        self.expect(self.client.post(
            f"{path}/medical-record", headers=self.auth(DOCTOR_ID), json={"diagnosis": "Sample note"}
        ), 201)
        patient, staff = self.auth(PATIENT_ID), self.auth(ADMIN_ID)
        review = self.expect(self.client.post(
            f"{path}/review", headers=patient, json={"rating": 5, "comment": "Clear explanations."}
        ), 201)
        public = f"/doctors/{DOCTOR_ID}/reviews"
        self.assertIsNone(self.expect(self.client.get(public), 200)["average_rating"])
        self.expect(self.client.post(f"{path}/review", headers=patient, json={"rating": 4}), 409)
        self.expect(self.client.patch(f"/admin/reviews/{review['id']}/publish", headers=patient), 403)
        self.expect(self.client.patch(f"/admin/reviews/{review['id']}/publish", headers=staff), 200)
        summary = self.expect(self.client.get(public), 200)
        self.assertEqual((summary["review_count"], summary["average_rating"]), (1, 5.0))
        self.assertEqual(set(summary["reviews"][0]), {"rating", "comment", "published_at"})

        certificate = self.expect(self.client.post(f"{path}/certificate", headers=patient), 201)
        self.assertEqual(certificate["status"], "pending")
        self.expect(self.client.get(f"{path}/certificate.pdf", headers=patient), 409)
        self.expect(self.client.get("/admin/certificates", headers=patient), 403)
        self.expect(self.client.patch(f"/admin/certificates/{visit['id']}/approve", headers=staff), 200)
        self.expect(self.client.get(f"{path}/certificate.pdf", headers=self.auth(SECOND_PATIENT_ID)), 403)
        pdf = self.client.get(f"{path}/certificate.pdf", headers=patient)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))

    def test_shift_replacement_requires_same_specialty_and_patient_confirmation(self):
        visit = self.expect(self.book(), 201)
        admin = self.auth(ADMIN_ID)
        new_doctor = self.expect(self.client.post("/doctors", headers=admin, json={
            "name": "Substitute Doctor", "email": "substitute@example.com",
            "specialty_id": 1, "password": DEMO_PASSWORD,
        }), 201)
        self.expect(self.client.put(
            "/doctors/me/schedule/0", headers=self.auth(new_doctor["id"]),
            json={"start": "09:00", "end": "17:00", "slot_minutes": 30},
        ), 200)
        shift = {"doctor_id": DOCTOR_ID, "date": "2026-11-16"}
        self.expect(self.client.post("/shift-replacements", headers=admin, json={
            **shift, "replacement_doctor_id": SECOND_DOCTOR_ID,
        }), 409)
        offers = self.expect(self.client.post("/shift-replacements", headers=admin, json={
            **shift, "replacement_doctor_id": new_doctor["id"],
        }), 201)
        self.assertEqual(offers[0]["appointment_id"], visit["id"])
        self.expect(self.client.delete(
            "/doctors/me/days-off/2026-11-16", headers=self.auth(DOCTOR_ID)
        ), 409)
        intake = f"/appointments/{visit['id']}/intake"
        self.expect(self.client.put(intake, headers=self.auth(PATIENT_ID), json={
            "reason": "Sample concern", "questions": "What should I bring?",
        }), 200)
        during = self.expect(self.client.get("/appointments", headers=self.auth(PATIENT_ID)), 200)
        self.assertEqual(during[0]["doctor_id"], DOCTOR_ID)
        accept = f"/shift-replacements/{offers[0]['id']}/accept"
        self.expect(self.client.post(accept, headers=self.auth(SECOND_PATIENT_ID)), 403)
        accepted = self.expect(self.client.post(accept, headers=self.auth(PATIENT_ID)), 200)
        self.assertEqual(accepted["doctor_id"], new_doctor["id"])
        self.assertEqual(accepted["starts_at"], visit["starts_at"])
        self.expect(self.client.get(intake, headers=self.auth(DOCTOR_ID)), 403)
        self.expect(self.client.get(intake, headers=self.auth(new_doctor["id"])), 200)
        self.assertEqual(self.expect(self.slots(), 200), [])
        self.expect(self.client.post(accept, headers=self.auth(PATIENT_ID)), 409)


if __name__ == "__main__":
    unittest.main()
