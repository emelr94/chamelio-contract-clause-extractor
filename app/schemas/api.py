from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import (
    ClauseIssue,
    ClauseType,
    Confidence,
    DocumentStatus,
    ErrorCode,
    FileType,
    WarningCode,
)


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ExtractionWarning(BaseModel):
    """Document-level signal that some source text may not be represented by the clauses."""

    code: WarningCode
    message: str
    start_page: int | None = None
    end_page: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ClauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int = Field(description="0-based order of the clause in the document.")
    number: str | None = Field(description="Numbering as printed, e.g. '5', 'ARTICLE 2'.")
    title: str | None
    clause_type: ClauseType
    text: str = Field(description="Verbatim source text; empty if the clause could not be located.")
    start_page: int | None = Field(description="1-based; null for DOCX.")
    end_page: int | None
    subsection_numbers: list[str]
    confidence: Confidence
    needs_review: bool
    issues: list[ClauseIssue]


class ExtractionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    page_count: int | None
    status: DocumentStatus
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    processing_ms: int
    clause_count: int
    warnings: list[ExtractionWarning]
    error: str | None
    created_at: datetime


class ExtractionResponse(ExtractionSummary):
    clauses: list[ClauseOut]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
