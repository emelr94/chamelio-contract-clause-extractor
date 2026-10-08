"""Schema the LLM must fill for each chunk. It is sent as the structured-output format,
so the API constrains decoding to it, and the SDK validates the reply with Pydantic."""

from pydantic import BaseModel, Field

from app.schemas.enums import ClauseType, Confidence


class LLMClause(BaseModel):
    number: str | None = Field(
        description="Numbering exactly as printed, e.g. '5', '5.', 'ARTICLE 2', 'Section 12'. "
        "null for preamble, signature block or unnumbered exhibits."
    )
    title: str | None = Field(description="Heading text without the number; null if none.")
    clause_type: ClauseType
    start_anchor: str = Field(
        description="The first 8-15 words of the clause copied VERBATIM from the text, "
        "starting with its number/heading. Must not span a [[PAGE n]] marker."
    )
    subsection_numbers: list[str] = Field(
        description="Numbers of subsections inside this clause, e.g. ['2.1', '2.2', '(a)']."
    )
    confidence: Confidence = Field(
        description="high = clear start and type (normal case); medium = type is a judgment "
        "call; low = the clause start itself is doubtful."
    )


class ChunkExtraction(BaseModel):
    clauses: list[LLMClause] = Field(
        description="Top-level clauses that START in this text, in document order."
    )
