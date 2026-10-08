"""ClauseExtractor end to end with a fake LLM: chunking, concurrency, alignment, statuses."""

import asyncio
import re

import pytest

from app.schemas.enums import ClauseType, Confidence, DocumentStatus, FileType, WarningCode
from app.schemas.llm import ChunkExtraction, LLMClause
from app.services.extractor import ClauseExtractor
from app.services.llm import ChunkResult, LLMError
from app.services.parsing import ParsedDocument

PAGES = [f"{n}. Clause {n}. " + "body " * 40 for n in range(1, 7)]


class FakeLLM:
    """Returns every 'N. Clause N.' heading in the chunk; can fail on chunks with a marker."""

    model = "fake-model"

    def __init__(self, fail_if_contains: str | None = None):
        self.fail_if_contains = fail_if_contains
        self.calls = 0

    async def extract_chunk(self, chunk_text: str) -> ChunkResult:
        self.calls += 1
        if self.fail_if_contains and self.fail_if_contains in chunk_text:
            raise LLMError("simulated timeout", input_tokens=7, output_tokens=1)
        clauses = [
            LLMClause(
                number=number,
                title=f"Clause {number}",
                clause_type=ClauseType.OTHER,
                start_anchor=f"{number}. Clause {number}.",
                subsection_numbers=[],
                confidence=Confidence.HIGH,
            )
            for number in re.findall(r"(\d+)\. Clause \1\.", chunk_text)
        ]
        return ChunkResult(
            ChunkExtraction(clauses=clauses), self.model, input_tokens=50, output_tokens=5
        )


def _extract(llm: FakeLLM, chunk_chars: int = 600):
    extractor = ClauseExtractor(llm, chunk_chars=chunk_chars, concurrency=2, chunk_timeout_s=5)
    return asyncio.run(extractor.extract(ParsedDocument(FileType.PDF, PAGES, True)))


def test_multi_chunk_document_yields_each_clause_once() -> None:
    llm = FakeLLM()
    result = _extract(llm)

    assert llm.calls > 1
    assert result.status is DocumentStatus.COMPLETED
    assert [c.number for c in result.clauses] == ["1", "2", "3", "4", "5", "6"]
    assert [c.start_page for c in result.clauses] == [1, 2, 3, 4, 5, 6]
    assert result.input_tokens == 50 * llm.calls
    assert result.warnings == []


def test_failed_chunk_gives_partial_result_with_warning() -> None:
    result = _extract(FakeLLM(fail_if_contains="6. Clause 6."))

    assert result.status is DocumentStatus.PARTIAL
    assert result.clauses  # the other chunks still produced clauses
    assert WarningCode.CHUNK_FAILED in [w.code for w in result.warnings]
    assert "simulated timeout" in (result.error or "")


def test_all_chunks_failing_gives_failed_result() -> None:
    result = _extract(FakeLLM(fail_if_contains="Clause"))

    assert result.status is DocumentStatus.FAILED
    assert result.clauses == []
    assert result.error
    assert result.input_tokens > 0  # failed attempts still cost money and are reported


def test_unexpected_exceptions_are_not_reported_as_llm_failures() -> None:
    class BuggyLLM(FakeLLM):
        async def extract_chunk(self, chunk_text: str) -> ChunkResult:
            raise TypeError("bug in our code")

    with pytest.raises(TypeError):
        _extract(BuggyLLM())


def test_slow_chunk_times_out_as_a_chunk_failure() -> None:
    class SlowLLM(FakeLLM):
        async def extract_chunk(self, chunk_text: str) -> ChunkResult:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    extractor = ClauseExtractor(SlowLLM(), chunk_chars=10**6, concurrency=1, chunk_timeout_s=0.05)
    result = asyncio.run(extractor.extract(ParsedDocument(FileType.PDF, PAGES, True)))
    assert result.status is DocumentStatus.FAILED
    assert "timed out" in (result.error or "")
