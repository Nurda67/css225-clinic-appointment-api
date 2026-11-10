# Clinic Appointment API

A FastAPI backend for a clinic. Patients find doctors, reserve and cancel visits, and review their medical history. Doctors manage their availability and record consultation outcomes. Administrators manage the directory and view appointment statistics.

## Run locally

Use Python 3.12. From the repository root in PowerShell, run the following commands.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

Open [Swagger UI](http://127.0.0.1:8000/docs). The [OpenAPI schema](http://127.0.0.1:8000/openapi.json) is also available.

Select **Authorize** in Swagger and enter one of the demo tokens. Swagger adds the `Bearer` prefix. To switch roles, log out in the authorization dialog and enter the next token.

| Role | User ID | Demo token |
| --- | --- | --- |
| Patient | 1 | `demo-patient` |
| Second patient | 2 | `demo-patient-2` |
| General practice doctor | 3 | `demo-doctor` |
| Cardiology doctor | 4 | `demo-doctor-2` |
| Administrator | 5 | `demo-admin` |

The seeded accounts and visit are fictional. Use one server process so all requests share the same data. Restarting the server resets the in-memory store.

## Endpoints

| Access | Method and path | Purpose |
| --- | --- | --- |
| Public | `GET /` | API information |
| Public | `GET /specialties` | Browse specialties |
| Public | `GET /doctors` | Find active doctors with optional `specialty_id` and `q` filters |
| Public | `GET /doctors/{doctor_id}` | View an active doctor |
| Public | `GET /doctors/{doctor_id}/slots` | Find open slots on the requested `date` |
| Patient | `POST /appointments` | Book a doctor and slot |
| Patient or doctor | `GET /appointments` | List your visits, optionally filtered by `status` |
| Patient | `PATCH /appointments/{appointment_id}` | Cancel your upcoming booking |
| Doctor | `GET /doctors/me/schedule` | View your working hours and days off |
| Doctor | `PUT /doctors/me/schedule/{weekday}` | Set hours for a weekday, with Monday as `0` |
| Doctor | `POST /doctors/me/days-off` | Set a date off |
| Doctor | `DELETE /doctors/me/days-off/{day}` | Reopen a date |
| Doctor | `POST /appointments/{appointment_id}/medical-record` | Record an assigned consultation and mark it done |
| Patient or doctor | `GET /patients/{patient_id}/medical-records` | Read patient history within your access scope |
| Admin | `POST /specialties` | Create a specialty |
| Admin | `PATCH /specialties/{specialty_id}` | Rename a specialty |
| Admin | `DELETE /specialties/{specialty_id}` | Delete an unused specialty |
| Admin | `POST /doctors` | Add a doctor and generate their access token |
| Admin | `PATCH /doctors/{doctor_id}` | Block or unblock a doctor |
| Admin | `GET /statistics` | Count doctors, specialties and visits by status. Visit counts accept inclusive `start_date` and `end_date` filters. |

## Swagger walkthrough

1. Call `GET /specialties`, `GET /doctors` with `specialty_id=1`, and `GET /doctors/3`. Pick an upcoming weekday in the clinic time zone (UTC+05:00). Call `GET /doctors/3/slots` with that `date`, then copy a `starts_at` value from the response.
2. Authorize as `demo-patient` and send `POST /appointments` with `doctor_id` set to `3` and the copied `starts_at` timestamp. Expect `201`. List your visits with `GET /appointments?status=booked`. Retry the same booking as `demo-patient-2` for `409`. A timestamp without an offset gives `422`. Try `PATCH /appointments/{appointment_id}` as the second patient with `{"status":"cancelled"}` for `403`. As `demo-patient`, cancel the booking and check that its slot is available again.
3. Authorize as `demo-doctor` and view `GET /doctors/me/schedule` and `GET /appointments`. Set Saturday (`5`) with `PUT /doctors/me/schedule/5` and `{"start":"09:00","end":"12:00","slot_minutes":30}`. Add an upcoming Saturday via `POST /doctors/me/days-off` with `{"date":"YYYY-MM-DD"}`. Confirm the date has zero public slots, then delete it via `DELETE /doctors/me/days-off/{day}` and check that the slots return. An `end` earlier than `start` gives `422`.
4. Still as `demo-doctor`, complete the seeded past appointment via `POST /appointments/1/medical-record` with `{"diagnosis":"Fictional observation","notes":"Follow-up planned"}`. Expect `201`; repeating the request gives `409`. View `GET /patients/1/medical-records` as `demo-doctor` and `demo-patient`. Try it as `demo-doctor-2`, `demo-patient-2`, or `demo-admin` for `403`.
5. Authorize as `demo-admin`. Create a specialty with `{"name":"Dermatology"}`, rename it using its returned ID, then delete it. Deleting specialty `1`, which a doctor uses, gives `409`. Add a doctor with `{"name":"Dr. Morgan","specialty_id":1}`. Block the new doctor with `{"is_active":false}`, check that the public doctor detail returns `404`, then unblock with `{"is_active":true}`. Call `GET /statistics` with the dates of the tested visits.

## Business rules and architecture

- Each slot comes from a weekday schedule in clinic time. Days off, elapsed times and occupied intervals are excluded. A doctor cannot make a schedule change or add a day off that would displace an upcoming booking.
- Booking checks doctor availability and the patient's other visits in the same locked operation that saves the appointment. Concurrent requests for the same slot yield one booking. Cancellation preserves the visit in history and releases the slot.
- The assigned doctor can complete a booked visit once it has started. Saving the medical record also moves the appointment to `done`. A patient can read their own records. A doctor can read only the records from their own visits with that patient.
- Blocking a doctor removes them from public search and prevents new bookings. Existing visits remain available to the doctor and the patient.
- Routers handle HTTP and authorization. Pydantic schemas validate requests and responses. Services implement the business rules using the lock-protected store. Errors use a JSON `error` object with `code` and `message`, plus `details` for request validation errors.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests exercise HTTP endpoints with FastAPI's TestClient. They use a controllable clock for visit completion and cover invalid requests, role boundaries, date filtering, and concurrent booking.
