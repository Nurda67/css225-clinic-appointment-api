from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from app.config import get_database_url
from app.database import Database
from app.errors import DomainError
from app.routers import directory, visits
from app.schemas.errors import ErrorResponse


def create_app(database: Database | None = None) -> FastAPI:
    application = FastAPI(
        title="Clinic Appointment API",
        version="2.0.0",
        description=(
            "Find doctors, book appointments, and manage clinic schedules. "
            "Use the Authorize button with a demo token from the README."
        ),
        responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
    )
    application.state.database = database if database is not None else Database(get_database_url())

    @application.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(map(str, issue["loc"])),
                "message": issue["msg"],
                "type": issue["type"],
            }
            for issue in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "One or more request fields are invalid.",
                    "details": details,
                }
            },
        )

    @application.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail)}},
            headers=exc.headers,
        )

    @application.exception_handler(OperationalError)
    async def handle_database_error(_: Request, exc: OperationalError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": {
                "code": "database_unavailable",
                "message": "The database is temporarily unavailable.",
            }},
        )

    @application.get("/", tags=["Service"])
    def root() -> dict[str, str]:
        return {"service": "Clinic Appointment API", "docs": "/docs"}

    application.include_router(visits.router)
    application.include_router(directory.router)
    return application


app = create_app()
