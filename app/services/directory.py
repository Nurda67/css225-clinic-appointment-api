from collections import Counter
from dataclasses import replace
from datetime import date
from secrets import token_urlsafe

from app.domain import AppointmentStatus, Doctor, Role, Specialty, User
from app.errors import DomainError
from app.schemas.directory import AppointmentCounts, DoctorCreated, DoctorView, StatisticsView
from app.store import CLINIC_TZ, Store


def list_specialties(store: Store) -> list[Specialty]:
    with store.lock:
        return sorted(store.specialties.values(), key=lambda specialty: specialty.name.casefold())


def _get_specialty(store: Store, specialty_id: int) -> Specialty:
    specialty = store.specialties.get(specialty_id)
    if specialty is None:
        raise DomainError(404, "specialty_not_found", "Specialty not found.")
    return specialty


def _check_specialty_name(store: Store, name: str, exclude_id: int | None = None) -> None:
    normalized_name = name.casefold()
    if any(
        specialty.id != exclude_id and specialty.name.casefold() == normalized_name
        for specialty in store.specialties.values()
    ):
        raise DomainError(409, "specialty_name_taken", "A specialty with that name already exists.")


def create_specialty(store: Store, name: str) -> Specialty:
    with store.lock:
        _check_specialty_name(store, name)
        specialty = Specialty(id=store.next_id("specialty"), name=name)
        store.specialties[specialty.id] = specialty
        return specialty


def rename_specialty(store: Store, specialty_id: int, name: str) -> Specialty:
    with store.lock:
        specialty = _get_specialty(store, specialty_id)
        _check_specialty_name(store, name, exclude_id=specialty_id)
        updated = replace(specialty, name=name)
        store.specialties[specialty_id] = updated
        return updated


def delete_specialty(store: Store, specialty_id: int) -> None:
    with store.lock:
        _get_specialty(store, specialty_id)
        if any(doctor.specialty_id == specialty_id for doctor in store.doctors.values()):
            raise DomainError(409, "specialty_in_use", "A doctor is assigned to this specialty.")
        del store.specialties[specialty_id]


def _get_doctor(store: Store, doctor_id: int) -> Doctor:
    doctor = store.doctors.get(doctor_id)
    if doctor is None:
        raise DomainError(404, "doctor_not_found", "Doctor not found.")
    return doctor


def _doctor_view(store: Store, doctor: Doctor) -> DoctorView:
    return DoctorView(
        id=doctor.id,
        name=store.users[doctor.id].name,
        specialty_id=doctor.specialty_id,
        specialty_name=store.specialties[doctor.specialty_id].name,
        is_active=doctor.is_active,
    )


def list_doctors(store: Store, specialty_id: int | None, query: str | None) -> list[DoctorView]:
    normalized_query = query.strip().casefold() if query is not None else ""
    with store.lock:
        if specialty_id is not None:
            _get_specialty(store, specialty_id)
        doctors = [
            _doctor_view(store, doctor)
            for doctor in store.doctors.values()
            if doctor.is_active and (specialty_id is None or doctor.specialty_id == specialty_id)
        ]
        matching_doctors = (
            doctor
            for doctor in doctors
            if normalized_query in doctor.name.casefold()
            or normalized_query in doctor.specialty_name.casefold()
        )
        return sorted(matching_doctors, key=lambda doctor: (doctor.name.casefold(), doctor.id))


def get_public_doctor(store: Store, doctor_id: int) -> DoctorView:
    with store.lock:
        doctor = _get_doctor(store, doctor_id)
        if not doctor.is_active:
            raise DomainError(404, "doctor_not_found", "Doctor not found.")
        return _doctor_view(store, doctor)


def create_doctor(store: Store, name: str, specialty_id: int) -> DoctorCreated:
    with store.lock:
        _get_specialty(store, specialty_id)
        doctor_id = store.next_id("user")
        access_token = token_urlsafe(32)
        user = User(id=doctor_id, name=name, role=Role.DOCTOR)
        doctor = Doctor(id=doctor_id, specialty_id=specialty_id)
        store.users[doctor_id] = user
        store.doctors[doctor_id] = doctor
        store.tokens[access_token] = doctor_id
        return DoctorCreated(**_doctor_view(store, doctor).model_dump(), access_token=access_token)


def set_doctor_status(store: Store, doctor_id: int, is_active: bool) -> DoctorView:
    with store.lock:
        doctor = _get_doctor(store, doctor_id)
        updated = replace(doctor, is_active=is_active)
        store.doctors[doctor_id] = updated
        return _doctor_view(store, updated)


def _in_date_range(visit_date: date, start_date: date | None, end_date: date | None) -> bool:
    return (start_date is None or visit_date >= start_date) and (
        end_date is None or visit_date <= end_date
    )


def get_statistics(
    store: Store, start_date: date | None, end_date: date | None
) -> StatisticsView:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise DomainError(422, "invalid_date_range", "start_date must be on or before end_date.")

    with store.lock:
        counts = Counter(
            appointment.status
            for appointment in store.appointments.values()
            if _in_date_range(appointment.starts_at.astimezone(CLINIC_TZ).date(), start_date, end_date)
        )
        total_doctors = len(store.doctors)
        active_doctors = sum(doctor.is_active for doctor in store.doctors.values())
        return StatisticsView(
            start_date=start_date,
            end_date=end_date,
            total_doctors=total_doctors,
            active_doctors=active_doctors,
            blocked_doctors=total_doctors - active_doctors,
            total_specialties=len(store.specialties),
            total_appointments=sum(counts.values()),
            appointments_by_status=AppointmentCounts(
                booked=counts[AppointmentStatus.BOOKED],
                cancelled=counts[AppointmentStatus.CANCELLED],
                done=counts[AppointmentStatus.DONE],
            ),
        )
