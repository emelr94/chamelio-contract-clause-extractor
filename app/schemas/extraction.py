"""Internal result of the extraction pipeline, before it is persisted."""

from pydantic import BaseModel, Field

from app.schemas.api import ExtractionWarning
from app.schemas.enums import ClauseIssue, ClauseType, Confidence, DocumentStatus


class ExtractedClause(BaseModel):
    number: str | None
    title: str | None
    clause_type: ClauseType
    text: str
    start_page: int | None
    end_page: int | None
    subsection_numbers: list[str] = Field(default_factory=list)
    confidence: Confidence
    needs_review: bool = False
    issues: list[ClauseIssue] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    status: DocumentStatus
    clauses: list[ExtractedClause]
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
