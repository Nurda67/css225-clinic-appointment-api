from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from threading import RLock

from app.domain import Appointment, Doctor, MedicalRecord, Role, Schedule, Specialty, User

CLINIC_TZ = timezone(timedelta(hours=5))


class Store:
    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        *,
        seed_demo_visit: bool = False,
    ) -> None:
        self.lock = RLock()
        self._clock = clock
        self.users = {
            1: User(1, "Dana Omar", Role.PATIENT),
            2: User(2, "Arman Iskakov", Role.PATIENT),
            3: User(3, "Aida Sadykova", Role.DOCTOR),
            4: User(4, "Timur Saparov", Role.DOCTOR),
            5: User(5, "Clinic Admin", Role.ADMIN),
        }
        self.tokens = {
            "demo-patient": 1,
            "demo-patient-2": 2,
            "demo-doctor": 3,
            "demo-doctor-2": 4,
            "demo-admin": 5,
        }
        self.specialties = {
            1: Specialty(1, "General Practice"),
            2: Specialty(2, "Cardiology"),
        }
        self.doctors = {3: Doctor(3, 1), 4: Doctor(4, 2)}
        self.schedules = {
            (doctor_id, weekday): Schedule(time(9), time(17), 30)
            for doctor_id in self.doctors
            for weekday in range(5)
        }
        self.days_off: set[tuple[int, date]] = set()
        self.appointments: dict[int, Appointment] = {}
        self.records: dict[int, MedicalRecord] = {}
        self._next_ids = {"user": 6, "specialty": 3, "appointment": 1}
        if seed_demo_visit:
            self._add_demo_visit()

    def now(self) -> datetime:
        if self._clock is None:
            return datetime.now(CLINIC_TZ)
        return self._clock().astimezone(CLINIC_TZ)

    def next_id(self, kind: str) -> int:
        """Allocate an ID inside a store transaction."""
        value = self._next_ids[kind]
        self._next_ids[kind] += 1
        return value

    def _add_demo_visit(self) -> None:
        day = self.now().date() - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        start = datetime.combine(day, time(9), CLINIC_TZ)
        with self.lock:
            visit_id = self.next_id("appointment")
            self.appointments[visit_id] = Appointment(
                id=visit_id,
                doctor_id=3,
                patient_id=1,
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
            )
