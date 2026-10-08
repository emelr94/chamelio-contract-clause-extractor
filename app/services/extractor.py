"""Pipeline: source text -> chunks -> LLM (concurrently) -> alignment -> coverage check."""

import asyncio
import logging
from typing import Protocol

from app.schemas.enums import DocumentStatus
from app.schemas.extraction import ExtractionResult
from app.services.alignment import align, check_coverage
from app.services.chunking import Chunk, SourceText, build_chunks
from app.services.llm import PROMPT_VERSION, ChunkResult, LLMError
from app.services.parsing import ParsedDocument

logger = logging.getLogger(__name__)


class Extractor(Protocol):
    async def extract(self, document: ParsedDocument) -> ExtractionResult: ...


class ChunkSegmenter(Protocol):
    model: str

    async def extract_chunk(self, chunk_text: str) -> ChunkResult: ...


class ClauseExtractor:
    def __init__(
        self, llm: ChunkSegmenter, *, chunk_chars: int, concurrency: int, chunk_timeout_s: float
    ):
        self._llm = llm
        self._chunk_chars = chunk_chars
        self._concurrency = concurrency
        self._chunk_timeout_s = chunk_timeout_s

    async def extract(self, document: ParsedDocument) -> ExtractionResult:
        source = SourceText.from_document(document)
        chunks = build_chunks(source, self._chunk_chars)
        semaphore = asyncio.Semaphore(self._concurrency)  # per call: bound to this event loop

        async def run(chunk: Chunk) -> ChunkResult:
            async with semaphore:
                try:  # caps SDK retries too, so a request cannot hang for many minutes
                    async with asyncio.timeout(self._chunk_timeout_s):
                        return await self._llm.extract_chunk(chunk.text)
                except TimeoutError as exc:  # tokens of the cancelled attempt are unknown
                    raise LLMError(f"timed out after {self._chunk_timeout_s:.0f}s") from exc

        outcomes = await asyncio.gather(*(run(chunk) for chunk in chunks), return_exceptions=True)

        succeeded: list[tuple[Chunk, ChunkResult]] = []
        failed: list[Chunk] = []
        errors: list[str] = []
        input_tokens = output_tokens = 0
        for chunk, outcome in zip(chunks, outcomes, strict=True):
            if isinstance(outcome, ChunkResult):
                succeeded.append((chunk, outcome))
            elif isinstance(outcome, LLMError):
                logger.warning("Chunk %d failed: %s", chunk.index, outcome)
                failed.append(chunk)
                errors.append(f"chunk {chunk.index}: {outcome}")
            else:  # a bug or a cancellation, not an LLM failure: let it surface as a 500
                raise outcome
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens

        models_used = sorted({result.model for _, result in succeeded})
        common = {
            "model": ",".join(models_used) or self._llm.model,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if not succeeded:
            return ExtractionResult(
                status=DocumentStatus.FAILED, clauses=[], error="; ".join(errors), **common
            )

        placed = align(source, [(chunk, result.extraction) for chunk, result in succeeded])
        warnings = check_coverage(placed, source, [c for c, _ in succeeded], failed)
        return ExtractionResult(
            status=DocumentStatus.PARTIAL if failed else DocumentStatus.COMPLETED,
            clauses=[p.clause for p in placed],
            warnings=warnings,
            error="; ".join(errors) or None,
            **common,
        )
