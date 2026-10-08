"""Domain errors. Raised anywhere; rendered as ErrorResponse by app.api.errors."""

from http import HTTPStatus
from typing import Any

from app.schemas.enums import ErrorCode

ERROR_STATUS: dict[ErrorCode, HTTPStatus] = {
    ErrorCode.MISSING_FILE: HTTPStatus.BAD_REQUEST,
    ErrorCode.EMPTY_FILE: HTTPStatus.BAD_REQUEST,
    ErrorCode.FILE_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.UNSUPPORTED_FILE_TYPE: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.UNREADABLE_DOCUMENT: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.SCANNED_PDF_UNSUPPORTED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.DOCUMENT_TOO_LARGE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.EXTRACTION_NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.LLM_ERROR: HTTPStatus.BAD_GATEWAY,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}


class AppError(Exception):
    """Domain error carrying a stable error code; mapped to an HTTP status by ERROR_STATUS."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]
