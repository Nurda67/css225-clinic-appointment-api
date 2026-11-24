from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.config import get_database_url, get_jwt_secret
from app.database import Database
from app.errors import (
    DomainError,
    ErrorResponse,
    handle_database_error,
    handle_domain_error,
    handle_http_error,
    handle_integrity_error,
    handle_validation_error,
)
from app.routers import auth, booking_workflows, directory, encounters, outcomes, schedule, visits


def create_app(database: Database | None = None) -> FastAPI:
    application = FastAPI(
        title="Clinic Appointment API",
        version="4.0.0",
        description=(
            "Find doctors, book appointments, and manage clinic schedules. "
            "Open /clinic for the clinic desk or /docs for the API."
        ),
        responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
    )
    if database is None:
        database = Database(get_database_url())
    application.state.database = database
    application.state.jwt_secret = get_jwt_secret()

    application.add_exception_handler(DomainError, handle_domain_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(HTTPException, handle_http_error)
    application.add_exception_handler(IntegrityError, handle_integrity_error)
    application.add_exception_handler(OperationalError, handle_database_error)

    @application.get("/", tags=["Service"])
    def root() -> dict[str, str]:
        return {"service": "Clinic Appointment API", "docs": "/docs"}

    web_dir = Path(__file__).resolve().parent / "web"
    application.mount("/clinic-assets", StaticFiles(directory=web_dir), name="clinic-assets")

    @application.get("/clinic", include_in_schema=False)
    def clinic() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    application.include_router(auth.router)
    application.include_router(schedule.router)
    application.include_router(visits.router)
    application.include_router(directory.router)
    application.include_router(booking_workflows.router)
    application.include_router(encounters.router)
    application.include_router(outcomes.router)
    return application


app = create_app()
