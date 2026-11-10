from http import HTTPStatus

from pydantic import BaseModel


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
