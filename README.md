# Clinic Desk

An English clinic workspace and FastAPI backend. Patients book visits and manage offers, reviews and certificates. Doctors manage their schedules and consultations. Administrators manage shift replacements, publish reviews and approve certificates.

## Assignment versions

- **Assignment 5** implements the REST API with an in-memory store. Restarting the server resets the demo data. [Assignment 5 source and setup](https://github.com/Nurda67/css225-clinic-appointment-api/tree/b55686f23eaad180df8a47d232069b06a303b106)
- **Assignment 6** added PostgreSQL, SQLAlchemy, and Alembic. [Assignment 6 source](https://github.com/Nurda67/css225-clinic-appointment-api/tree/89c780b)
- **Assignment 7** adds registration, email and password login, and JWT permissions. The clinic workspace uses those same accounts and permissions.

To open the in-memory version in a separate folder, run this command from the Git repository. Then follow the README in that folder.

```powershell
git worktree add --detach ../Assignment_5_InMemory b55686f
```

## Run locally

Use Python 3.12 and PostgreSQL. In pgAdmin's Query Tool or psql, connect as a PostgreSQL administrator and run these statements separately. Choose your own local password.

```sql
CREATE ROLE clinic_app WITH LOGIN PASSWORD 'replace_with_your_local_password';
CREATE DATABASE clinic_db OWNER clinic_app;
```

From the repository root in PowerShell, create the environment if needed and install the dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set the database values in `.env`. Generate a random signing key and paste it into `JWT_SECRET`. Keep the key in your local environment.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Run the demo seed to create fictional patient, doctor and administrator accounts. The terminal asks for a password of 8 to 128 characters. Scripts can supply `DEMO_PASSWORD` in the process environment.

```powershell
.\.venv\Scripts\python.exe -m app.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

`DATABASE_URL` can override the individual `DB_*` values. Seeding preserves existing credentials, schedule edits, doctor blocking and appointments. An Assignment 6 database can be upgraded in place. The migration adds the credential fields while keeping the existing user IDs and clinic data. Existing demo accounts gain credentials when seeded. For any other existing account, run the following command with its user ID and email. It prompts for a password and keeps the account's role.

```powershell
.\.venv\Scripts\python.exe -m app.activate_user 6 doctor@example.org
```

On Windows environments that require the installed PostgreSQL client libraries, use the optional `PSYCOPG_IMPL=python` and `POSTGRES_BIN` settings in `.env.example`. Set `POSTGRES_BIN` to the actual PostgreSQL `bin` folder. `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1` provides the optional pure-Python SQLAlchemy fallback.

Open [Clinic Desk](http://127.0.0.1:8000/clinic) for the browser workspace. The API is documented in [Swagger UI](http://127.0.0.1:8000/docs) and the [OpenAPI schema](http://127.0.0.1:8000/openapi.json).

### Update an existing installation

Keep the database settings and JWT key in your existing `.env`. From the repository root, install the latest dependencies and apply the Alembic migration before starting the server.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

The current migration is `0003_clinic_workflows`. It adds workflow records and appointment fields alongside the existing clinic data. ReportLab generates attendance PDFs and is installed from `requirements.txt`.

## Sign in

Select **Sign In** in Clinic Desk and use a demo account below. **Register** creates a patient account. The email must be unique, and the password must be 8 to 128 characters.

In Swagger, the equivalent operations are `POST /auth/register` and `POST /auth/login`. Copy `access_token` from the login response and paste it into **Authorize**. Swagger adds the `Bearer` prefix. Use **Sign Out** in Clinic Desk or log out in the Swagger authorization dialog before switching accounts.

| Demo role | User ID | Email |
| --- | --- | --- |
| Patient | 1 | `patient@example.com` |
| Second patient | 2 | `patient2@example.com` |
| General practice doctor | 3 | `doctor@example.com` |
| Cardiology doctor | 4 | `doctor2@example.com` |
| Administrator | 5 | `admin@example.com` |

The demo accounts use the password you chose during their first seed. Passwords are stored as Argon2id hashes. JWTs expire after 30 minutes. The authentication dependency verifies the JWT and fetches the user's current role from PostgreSQL. Missing, invalid and expired tokens return `401`. A valid user without permission receives `403`.

## Try the clinic workflows

Dates and slots use clinic time (UTC+05:00). The demo doctors initially work weekdays. Use one of their future slots for booking scenarios. On a newly seeded database, the sample past booking belongs to the first patient and the general practice doctor. Use that booking to exercise completed-visit workflows, and use a separate started booking to demonstrate a no-show.

1. **Reschedule and accept a waitlist offer.** As the first patient, open **Find a Doctor**, choose **View Availability** for the general practice doctor and book a time. As the second patient, open the same doctor and date and select **Join Waitlist**. Sign in again as the first patient and use **Reschedule** under **Appointments** to move the visit to another time. As the second patient, open **Notifications**, find the offer and accept it. The released slot goes first to the earliest eligible waitlist member. Availability is checked again on acceptance.
2. **Record attendance and complete a consultation.** As the patient, fill in the intake questionnaire for a booked visit under **Appointments**. As the assigned doctor, open the questionnaire and record attendance once the visit starts. Select **Mark Arrived** and then **Complete Visit** to save the consultation result to the patient's history. For a missed visit, choose **Mark No-Show**. No-show is a final status and the visit stays outside the completion, review and certificate workflows.
3. **Link a follow-up.** As the assigned doctor, recommend a follow-up on a completed visit and choose a date range. As its patient, open the recommendation from **Notifications** or **Requests** and book a free slot with the same doctor within the recommended dates. The new appointment links to the original consultation. Use **View Previous Consultation** on the follow-up appointment.
4. **Confirm a shift replacement.** Prepare a second General Practice doctor because the two seeded doctors have different specialties. In Swagger, sign in as the administrator and use `POST /doctors` to create the second doctor with `specialty_id=1`, a unique email and a password. Sign in as that doctor and use `PUT /doctors/me/schedule/{weekday}` to set hours matching the original doctor's booked times. Monday is `0` and Sunday is `6`. With a future visit on the original doctor's schedule, sign in as the administrator and open **Shift Replacements**. Select the original doctor, replacement doctor and date. Both doctors must have the same specialty, and every affected visit must have a matching free slot with the replacement. As the patient, open the offer under **Notifications** or **Requests** and choose **Confirm Replacement**. The appointment keeps its time and moves to the replacement doctor's schedule after confirmation.
5. **Moderate a review.** As the patient, submit a rating of 1 to 5 on a completed visit. Each visit allows one review. As the administrator, open **Review Moderation** and publish it. The review and the updated average appear on the doctor's card under **Find a Doctor**.
6. **Approve and download proof of attendance.** As the patient, select **Request Proof of Attendance** for a completed visit. As the administrator, open **Certificates** and approve the request. The patient can then download the PDF from their **Requests**. It lists the patient, doctor and visit time.

## Endpoints

| Access | Method and path | Purpose |
| --- | --- | --- |
| Public | `GET /` | API information |
| Public | `POST /auth/register` | Create a patient account |
| Public | `POST /auth/login` | Authenticate with email and password and obtain a JWT |
| Signed in | `GET /auth/me` | Read your profile and role |
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
| Admin | `POST /doctors` | Add a doctor account with an email and password |
| Admin | `PATCH /doctors/{doctor_id}` | Block or unblock a doctor |
| Admin | `GET /statistics` | Count doctors, specialties and visits by status. Visit counts accept inclusive `start_date` and `end_date` filters. |

The workflow operations appear in the appointment, waitlist, notification, shift replacement, encounter, review and attendance sections of [Swagger UI](http://127.0.0.1:8000/docs).

## Swagger walkthrough

Try registration with a new email. Repeat it with uppercase characters in the same address for `409`. Try login with an incorrect password for `401`, then use the correct one for `200`. Call `GET /appointments` before authorizing for `401`.

1. Call `GET /` for API information. Open `GET /specialties`, `GET /doctors` with `specialty_id=1`, and `GET /doctors/3`. Try `GET /doctors/999` for a `404`. Pick an upcoming weekday in the clinic time zone (UTC+05:00). Call `GET /doctors/3/slots` with that `date`, then copy a `starts_at` value from the response.
2. Authorize as `patient@example.com` and send `POST /appointments` with `doctor_id` set to `3` and the copied `starts_at` timestamp. Expect `201`. List your visits with `GET /appointments?status=booked`. Retry the same booking as `patient2@example.com` for `409`. A timestamp without an offset gives `422`. Try `PATCH /appointments/{appointment_id}` as the second patient with `{"status":"cancelled"}` for `403`. As `patient@example.com`, cancel the booking and check that its slot is available again.
3. Authorize as `doctor@example.com` and view `GET /doctors/me/schedule` and `GET /appointments`. Set Saturday (`5`) with `PUT /doctors/me/schedule/5` and `{"start":"09:00","end":"12:00","slot_minutes":30}`. Add an upcoming Saturday via `POST /doctors/me/days-off` with `{"date":"YYYY-MM-DD"}`. Confirm the date has zero public slots, then delete it via `DELETE /doctors/me/days-off/{day}` and check that the slots return. An `end` earlier than `start` gives `422`.
4. Still as `doctor@example.com`, find the seeded past booked appointment in `GET /appointments` and complete it via `POST /appointments/{appointment_id}/medical-record` with `{"diagnosis":"Fictional observation","notes":"Follow-up planned"}`. Expect `201`; repeating the request gives `409`. View `GET /patients/1/medical-records` as `doctor@example.com` and `patient@example.com`. Try it as `doctor2@example.com`, `patient2@example.com`, or `admin@example.com` for `403`.
5. Authorize as `admin@example.com`. Create a specialty with `{"name":"Dermatology"}`, rename it using its returned ID, then delete it. Deleting specialty `1`, which a doctor uses, gives `409`. Add a doctor with `name`, `specialty_id`, a new `email`, and a `password`. Test their login through `POST /auth/login`. Block the new doctor with `{"is_active":false}`, check that the public doctor detail returns `404`, then unblock with `{"is_active":true}`. Call `GET /statistics` with the dates of the tested visits.

## Business rules and architecture

- Each slot comes from a weekday schedule in clinic time. Days off, elapsed times and occupied intervals are excluded. A doctor cannot make a schedule change or add a day off that would displace an upcoming booking.
- Booking checks doctor availability and the patient's other visits in the same locked operation that saves the appointment. Concurrent requests for the same slot yield one booking. Cancellation preserves the visit in history and releases the slot.
- The assigned doctor can complete a booked visit once it has started. Saving the medical record also moves the appointment to `done`. A patient can read their own records. A doctor can read only the records from their own visits with that patient.
- Rescheduling and replacement confirmation check for conflicts inside the booking transaction. Patients can act on their own waitlist and replacement offers.
- Completed visits qualify for reviews and attendance certificates. Publishing a review includes it in the public rating, and staff approval enables PDF download for the patient.
- Blocking a doctor removes them from public search and prevents new bookings. Existing visits remain available to the doctor and the patient.
- Errors use a JSON `error` object with `code` and `message`. Request validation errors also include `details`.

## Read the code

1. [main.py](app/main.py) registers the routers and error handlers. The [routers](app/routers) define URLs and HTTP responses. [schemas.py](app/schemas.py) validates the JSON request bodies and defines the response fields.
2. Follow `create_specialty` from [the directory router](app/routers/directory.py) into [the directory service](app/services/directory.py). The service checks for duplicate names and saves the row.
3. Follow `post_appointment` from [the visits router](app/routers/visits.py) into `book_appointment` in [the visits service](app/services/visits.py). The service checks availability, finds the slot, checks for overlaps, and saves the visit. [The schedule service](app/services/schedule.py) calculates slots and checks for conflicts before working hours change.
4. [The auth router](app/routers/auth.py) validates registration and login. [The accounts service](app/services/accounts.py) checks credentials and saves users. [security.py](app/security.py) handles password hashing and JWT signing and verification.
5. [dependencies.py](app/dependencies.py) verifies the JWT, loads the user and checks their role. It also gives each request a database session. A successful request commits its changes. Errors roll them back. [models.py](app/models.py) defines the tables and relationships.

### Compare with other FastAPI projects

- The Hero API uses a session dependency and Pydantic models. Compare the list and create database operations with the clinic's directory service. [FastAPI Hero API tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/) · [Hero API source](https://github.com/fastapi/fastapi/blob/master/docs_src/sql_databases/tutorial002_py310.py)
- The Full Stack FastAPI Template uses separate routers and shared dependencies for the session and authorization. Compare its item routes with the clinic's visits router and role checks. [Template item routes](https://github.com/fastapi/full-stack-fastapi-template/blob/master/backend/app/api/routes/items.py) · [Template dependencies](https://github.com/fastapi/full-stack-fastapi-template/blob/master/backend/app/api/deps.py)

## Persistent data model

PostgreSQL stores the clinic and workflow records through SQLAlchemy ORM. A specialty has many doctors. Each doctor belongs to one user and has many schedules, days off and appointments. A patient user has many appointments and access tokens. An appointment has at most one medical record, enforced by the record's appointment primary key and foreign key.

The workflow migration adds intake forms, follow-up recommendations, waitlist entries, replacement offers, notifications, reviews and attendance certificates. A follow-up links to the appointment that prompted it. Reviews and certificates each reference a completed appointment.

Foreign keys preserve resource references. Check constraints validate schedule ranges, slot durations, appointment windows and enum values. A case-insensitive unique index prevents duplicate specialty names. A partial unique index on doctor and start time applies to active appointments so cancellation releases the slot. Application transactions also prevent overlapping patient bookings and conflicting schedule edits.

The Alembic credential migration adds a unique index on lowercase email and a constraint requiring email and password hash to be set together. An older account can have both fields empty until it is activated. Doctor creation commits the user and profile together. Consultation completion commits the record and appointment status together.

The project uses PostgreSQL for development and tests. To reverse the initial migration in a disposable database, run `python -m alembic downgrade base`. This removes the application tables and their data. Apply `upgrade head` again before seeding.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The integration tests use the configured PostgreSQL database and require permission to create schemas. Each testcase creates a UUID-named schema, applies the migrations, seeds it, and drops only that schema during cleanup. Existing application tables and records stay outside these test schemas. Tests cover registration, login, password hashing, JWT validation, permissions, invalid input, and the original clinic workflows. They also check persistence, concurrent bookings, rollback, constraints, idempotent seeding, and migration upgrades.
