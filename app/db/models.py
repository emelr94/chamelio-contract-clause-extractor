import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.schemas.enums import ClauseType, Confidence, DocumentStatus, FileType


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite stores datetimes without a timezone; re-attach UTC when reading."""

    impl = DateTime
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class Document(Base):
    """One uploaded file and the outcome of extracting it."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(String(10))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None]
    status: Mapped[DocumentStatus] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    processing_ms: Mapped[int]
    clause_count: Mapped[int] = mapped_column(default=0)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(UTC), index=True
    )

    clauses: Mapped[list["Clause"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Clause.position",
    )

    @property
    def document_id(self) -> str:
        return self.id


class Clause(Base):
    """One clause of a document, with its verbatim source text and location."""

    __tablename__ = "clauses"
    __table_args__ = (
        UniqueConstraint("document_id", "position"),
        Index("ix_clauses_type_document", "clause_type", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    number: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500))
    clause_type: Mapped[ClauseType] = mapped_column(String(40))
    text: Mapped[str]
    start_page: Mapped[int | None]
    end_page: Mapped[int | None]
    subsection_numbers: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[Confidence] = mapped_column(String(10))
    needs_review: Mapped[bool] = mapped_column(default=False)
    issues: Mapped[list[str]] = mapped_column(JSON, default=list)

    document: Mapped[Document] = relationship(back_populates="clauses")
