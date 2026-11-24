from collections.abc import Mapping
from http import HTTPStatus

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException


class DomainError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ValidationIssue(BaseModel):
    field: str
    message: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_responses(*codes: int) -> dict[int, dict[str, object]]:
    return {code: {"model": ErrorResponse, "description": HTTPStatus(code).phrase} for code in codes}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return _error_response(exc.status_code, exc.code, exc.message, headers=headers)


async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "field": ".".join(map(str, issue["loc"])),
            "message": issue["msg"],
            "type": issue["type"],
        }
        for issue in exc.errors()
    ]
    return _error_response(
        422, "validation_error", "One or more request fields are invalid.", details=details
    )


async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _error_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    # PostgreSQL still enforces uniqueness if two requests pass a check together.
    diagnostics = getattr(exc.orig, "diag", None)
    constraint = getattr(diagnostics, "constraint_name", None)
    if constraint == "uq_appointments_active_slot":
        return _error_response(409, "slot_taken", "This slot has already been booked.")
    if constraint == "uq_users_email_lower":
        return _error_response(409, "email_taken", "This email is already registered.")
    if constraint == "uq_specialties_name_lower":
        return _error_response(409, "specialty_name_taken", "A specialty with that name already exists.")
    workflow_errors = {
        "uq_review_appointment": ("review_exists", "You have already reviewed this visit."),
        "visit_certificates_pkey": ("certificate_exists", "You have already requested proof of attendance."),
        "uq_waitlist_active": ("waitlist_exists", "You already have a waitlist entry for this day."),
        "uq_follow_ups_original": ("follow_up_exists", "A follow-up has already been recommended."),
        "uq_pending_replacement": ("replacement_exists", "A replacement offer already exists for this visit."),
    }
    if constraint in workflow_errors:
        code, message = workflow_errors[constraint]
        return _error_response(409, code, message)
    return _error_response(
        409, "data_conflict", "This operation conflicts with existing or related data."
    )


async def handle_database_error(_: Request, exc: OperationalError) -> JSONResponse:
    return _error_response(503, "database_unavailable", "The database is temporarily unavailable.")
