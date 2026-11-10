from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import CLINIC_TZ, Store


class ClinicApiTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 16, 8, 0, tzinfo=CLINIC_TZ)
        self.app = create_app(store=Store(clock=lambda: self.now))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    @staticmethod
    def auth(token):
        return {"Authorization": f"Bearer {token}"}

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

    def book(self, doctor_id=3, hour=9, minute=0, patient="demo-patient", day=16):
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
        self.assertTrue(
            any(
                scheme["type"] == "http" and scheme["scheme"] == "bearer"
                for scheme in schema["components"]["securitySchemes"].values()
            )
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
        admin = self.auth("demo-admin")
        payload = {"name": "Dermatology"}
        self.expect(self.client.post("/specialties", json=payload), 401)
        self.expect(
            self.client.post("/specialties", headers=self.auth("wrong-token"), json=payload),
            401,
        )
        self.expect(
            self.client.post("/specialties", headers=self.auth("demo-patient"), json=payload),
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
        admin = self.auth("demo-admin")
        payload = {"name": "Dr. Morgan", "specialty_id": 999}
        self.expect(self.client.post("/doctors", headers=admin, json=payload), 404)
        payload["specialty_id"] = 1
        doctor = self.expect(self.client.post("/doctors", headers=admin, json=payload), 201)
        self.assertTrue(doctor["access_token"])
        doctor_id = doctor["id"]
        public_doctor = self.expect(self.client.get(f"/doctors/{doctor_id}"), 200)
        self.assertNotIn("access_token", public_doctor)
        schedule = self.expect(
            self.client.get("/doctors/me/schedule", headers=self.auth(doctor["access_token"])),
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
            self.client.get("/appointments", headers=self.auth("demo-doctor")), 200
        )
        self.assertIn(appointment["id"], {item["id"] for item in appointments})
        self.expect(
            self.client.patch("/doctors/3", headers=admin, json={"is_active": True}), 200
        )
        self.expect(self.book(minute=30), 201)

    def test_recurring_slots_and_day_off(self):
        doctor = self.auth("demo-doctor")
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
        doctor = self.auth("demo-doctor")
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
        patient = self.auth("demo-patient")
        second_patient = self.auth("demo-patient-2")
        appointment = self.expect(self.book(), 201)
        self.expect(self.book(patient="demo-patient-2"), 409)
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
        rebooked = self.expect(self.book(patient="demo-patient-2"), 201)
        self.assertNotEqual(rebooked["id"], appointment["id"])
        appointments = self.expect(
            self.client.get("/appointments", headers=patient, params={"status": "cancelled"}),
            200,
        )
        self.assertEqual([item["id"] for item in appointments], [appointment["id"]])
        self.expect(self.client.get("/appointments", headers=patient, params={"status": "typo"}), 422)

    def test_same_slot_concurrent_booking_has_one_winner(self):
        barrier = Barrier(2, timeout=5)

        def attempt(token):
            with TestClient(self.app) as client:
                barrier.wait()
                return client.post(
                    "/appointments",
                    headers=self.auth(token),
                    json={"doctor_id": 3, "starts_at": "2026-11-16T09:00:00+05:00"},
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, ("demo-patient", "demo-patient-2")))
        self.assertEqual(sorted(statuses), [201, 409])

    def test_consultation_and_patient_history(self):
        patient = self.auth("demo-patient")
        doctor = self.auth("demo-doctor")
        second_doctor = self.auth("demo-doctor-2")
        first = self.expect(self.book(), 201)
        path = f"/appointments/{first['id']}/medical-record"
        payload = {"diagnosis": "Fictional observation A", "notes": "Follow up in two weeks."}
        self.expect(self.client.post(path, headers=patient, json=payload), 403)
        self.expect(self.client.post(path, headers=second_doctor, json=payload), 403)
        self.expect(self.client.post(path, headers=doctor, json=payload), 409)

        history = "/patients/1/medical-records"
        self.expect(self.client.get(history, headers=second_doctor), 403)
        self.expect(self.client.get(history, headers=self.auth("demo-patient-2")), 403)
        self.expect(self.client.get(history, headers=self.auth("demo-admin")), 403)
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

    def test_statistics_respect_role_and_date_filters(self):
        admin = self.auth("demo-admin")
        appointment = self.expect(self.book(), 201)
        self.expect(self.book(day=17), 201)
        self.expect(
            self.client.patch(
                f"/appointments/{appointment['id']}",
                headers=self.auth("demo-patient"),
                json={"status": "cancelled"},
            ),
            200,
        )
        self.expect(self.client.get("/statistics"), 401)
        self.expect(self.client.get("/statistics", headers=self.auth("demo-doctor")), 403)
        stats = self.expect(
            self.client.get(
                "/statistics",
                headers=admin,
                params={"start_date": "2026-11-16", "end_date": "2026-11-16"},
            ),
            200,
        )
        self.assertEqual(stats["total_appointments"], 1)
        self.assertEqual(stats["appointments_by_status"], {"booked": 0, "cancelled": 1, "done": 0})
        self.expect(
            self.client.get(
                "/statistics",
                headers=admin,
                params={"start_date": "2026-11-17", "end_date": "2026-11-16"},
            ),
            422,
        )


if __name__ == "__main__":
    unittest.main()
