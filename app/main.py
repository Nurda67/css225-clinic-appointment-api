from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.errors import DomainError
from app.routers import directory, visits
from app.schemas.errors import ErrorResponse
from app.store import Store


def create_app(store: Store | None = None) -> FastAPI:
    application = FastAPI(
        title="Clinic Appointment API",
        version="1.0.0",
        description=(
            "Find doctors, book appointments, and manage clinic schedules. "
            "Use the Authorize button with a demo token from the README."
        ),
        responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
    )
    application.state.store = store if store is not None else Store(seed_demo_visit=True)

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

    @application.get("/", tags=["Service"])
    def root() -> dict[str, str]:
        return {"service": "Clinic Appointment API", "docs": "/docs"}

    application.include_router(visits.router)
    application.include_router(directory.router)
    return application


app = create_app()
