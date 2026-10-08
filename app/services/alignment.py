"""Deterministic post-processing of LLM output. The LLM only says where clauses start;
this module finds those anchors in the source, cuts the verbatim text, and reports any
source text that no clause accounts for."""

import bisect
import re
from dataclasses import dataclass

from app.schemas.api import ExtractionWarning
from app.schemas.enums import ClauseIssue, ClauseType, Confidence, WarningCode
from app.schemas.extraction import ExtractedClause
from app.schemas.llm import ChunkExtraction, LLMClause
from app.services.chunking import Chunk, SourceText

MIN_ANCHOR_CHARS = 6  # shorter anchors (whitespace excluded) are too ambiguous to search
MIN_PREFIX_CHARS = 15  # shortest truncated anchor prefix we still trust
ANCHOR_PREFIX_RATIOS = (1.0, 0.75, 0.5)  # shorter retries, e.g. when a page header splits it
DUPLICATE_DISTANCE = 50  # same clause re-extracted by an overlapping chunk lands this close
MIN_UNCOVERED_CHARS = 200  # leading text below this size is not worth a warning

_CHAR_MAP = str.maketrans(  # curly quotes and en/em dashes -> ASCII
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)
_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
_DIGITS = re.compile(r"\d+")
_SUBSECTION_NUMBER = re.compile(r"^\s*(\d+)\.\d+")  # "5.13", "28.1.2"; not "5." / "ARTICLE 5"


class AnchorIndex:
    """Whitespace- and case-insensitive search over the source text, returning source offsets."""

    def __init__(self, text: str):
        self._positions = [i for i, char in enumerate(text) if not char.isspace()]
        self._compact = "".join(_normalize(text[i]) for i in self._positions)

    def find(self, anchor: str, start: int, end: int) -> int | None:
        """First offset in [start, end) where `anchor`, or a long enough prefix of it, occurs."""
        needle = "".join(_normalize(c) for c in anchor if not c.isspace())
        if len(needle) < MIN_ANCHOR_CHARS:
            return None
        lo = bisect.bisect_left(self._positions, start)
        hi = bisect.bisect_left(self._positions, end)
        for ratio in ANCHOR_PREFIX_RATIOS:
            length = int(len(needle) * ratio)
            if ratio < 1.0 and length < MIN_PREFIX_CHARS:
                break
            hit = self._compact.find(needle[:length], lo, hi)
            if hit != -1:
                return self._positions[hit]
        return None


@dataclass
class PlacedClause:
    """A clause with its source offset (None if its anchor could not be located)."""

    offset: int | None
    clause: ExtractedClause


def align(
    source: SourceText, chunk_outputs: list[tuple[Chunk, ChunkExtraction]]
) -> list[PlacedClause]:
    """Locate every LLM clause, merge duplicates from overlapping chunks, and cut the text.

    Each located clause runs from its anchor to the next located anchor, so its text is
    verbatim source by construction. Unlocated clauses are kept (empty text, flagged) right
    after the clause the LLM listed before them: nothing the LLM reported is dropped."""
    index = AnchorIndex(source.text)
    located: dict[int, tuple[LLMClause, Chunk]] = {}
    unlocated: list[tuple[int, LLMClause, Chunk]] = []  # (offset it follows, clause, chunk)

    for chunk, extraction in chunk_outputs:
        previous = chunk.start - 1
        for item in extraction.clauses:
            offset = index.find(item.start_anchor, max(chunk.start, previous + 1), chunk.end)
            if offset is None:  # the LLM may have listed clauses out of order
                offset = index.find(item.start_anchor, chunk.start, chunk.end)
            if offset is None:
                unlocated.append((previous, item, chunk))
                continue
            duplicate = _find_duplicate(located, offset, item, chunk)
            if duplicate is None:
                located[offset] = (item, chunk)
            else:
                offset = duplicate
                if (
                    _CONFIDENCE_RANK[item.confidence]
                    > _CONFIDENCE_RANK[located[offset][0].confidence]
                ):
                    located[offset] = (item, chunk)
            previous = max(previous, offset)

    starts = _merge_subsections(located, unlocated_after={after for after, _, _ in unlocated})
    ends = [*starts[1:], len(source.text)] if starts else []
    entries = [
        (
            (start, 0, seq),
            PlacedClause(start, _located_clause(source, located[start][0], start, end)),
        )
        for seq, (start, end) in enumerate(zip(starts, ends, strict=True))
    ]
    entries += [
        ((after, 1, seq), PlacedClause(None, _unlocated_clause(item)))
        for seq, (after, item, chunk) in enumerate(unlocated)
        if not _located_by_overlap(located, item, chunk)
    ]
    return [placed for _, placed in sorted(entries, key=lambda entry: entry[0])]


def check_coverage(
    placed: list[PlacedClause],
    source: SourceText,
    succeeded: list[Chunk],
    failed: list[Chunk],
) -> list[ExtractionWarning]:
    """Report source text that may not be represented by any clause.

    Side effect: a located clause whose slice runs over text that may hold another clause
    (an unlocated clause, or a range only a failed chunk saw) is flagged
    MAY_CONTAIN_MISSING_CLAUSE, because its slice runs on to the next located anchor."""
    return [
        *_numbering_gaps(placed),
        *_uncovered_prefix(placed, source),
        *_unlocated_clauses(placed),
        *_failed_pages(placed, source, succeeded, failed),
    ]


# --- alignment helpers ---------------------------------------------------------------------


def _normalize(char: str) -> str:
    return char.translate(_CHAR_MAP).lower()


def _identity(item: LLMClause) -> tuple[str | int, ...]:
    """What makes two LLM clauses 'the same clause': the digits of the number, so "ARTICLE 5"
    and "5." match while "5.13" and "1.2" stay distinct from "5" and "1.1". Without digits
    ("Exhibit A", "ARTICLE V") the whole label, type and title are compared."""
    digits = tuple(int(d) for d in _DIGITS.findall(item.number or ""))
    if digits:
        return ("number", *digits)
    label = "".join((item.number or "").split()).strip(".").lower()
    return ("unnumbered", item.clause_type.value, label, (item.title or "").strip().lower())


def _merge_subsections(
    located: dict[int, tuple[LLMClause, Chunk]], unlocated_after: set[int]
) -> list[int]:
    """Sorted clause starts, with subsections that leaked out as top-level clauses folded into
    their parent. A chunk that begins inside ARTICLE 5 may report "5.13" as a clause; dropping
    its start leaves its text inside ARTICLE 5 and its number in the parent's subsections.

    Not folded when an unlocated clause sits in between (e.g. a "SCHEDULE B" heading the model
    reported but we could not find): then "5.1" may belong to the schedule, not to clause 5.
    The parent keeps the lower confidence of the two, so a doubtful child still gets reviewed."""
    kept: list[int] = []
    for start in sorted(located):
        item = located[start][0]
        if (
            kept
            and _is_subsection_of(item, located[kept[-1]][0])
            and not any(kept[-1] <= after < start for after in unlocated_after)
        ):
            parent, parent_chunk = located[kept[-1]]
            confidence = min(parent.confidence, item.confidence, key=_CONFIDENCE_RANK.__getitem__)
            merged = parent.model_copy(
                update={
                    "subsection_numbers": [*parent.subsection_numbers, item.number or ""],
                    "confidence": confidence,
                }
            )
            located[kept[-1]] = (merged, parent_chunk)
            continue
        kept.append(start)
    return kept


def _is_subsection_of(item: LLMClause, parent: LLMClause) -> bool:
    child = _SUBSECTION_NUMBER.match(item.number or "")
    return (
        child is not None
        and _SUBSECTION_NUMBER.match(parent.number or "") is None
        and _first_int(parent.number) == int(child.group(1))
    )


def _find_duplicate(
    located: dict[int, tuple[LLMClause, Chunk]], offset: int, item: LLMClause, chunk: Chunk
) -> int | None:
    """The nearest clause already located at the same offset, or within DUPLICATE_DISTANCE with
    the same identity (overlap re-extraction, e.g. "ARTICLE 5" vs "5."). Short neighbours like
    "12. [Reserved]." / "13. [Reserved]." differ in identity and are never merged."""
    del chunk  # identity, not chunk membership, decides (see _located_by_overlap for that)
    candidates = [
        other_offset
        for other_offset, (other, _) in located.items()
        if other_offset == offset
        or (abs(other_offset - offset) < DUPLICATE_DISTANCE and _identity(other) == _identity(item))
    ]
    return min(candidates, key=lambda o: abs(o - offset), default=None)


def _located_by_overlap(
    located: dict[int, tuple[LLMClause, Chunk]], item: LLMClause, chunk: Chunk
) -> bool:
    """True if another chunk located this clause inside the range this chunk also saw, i.e.
    it is the same clause seen twice, not a different clause that reuses the number."""
    return any(
        other_chunk.index != chunk.index
        and chunk.start <= offset < chunk.end
        and _identity(other) == _identity(item)
        for offset, (other, other_chunk) in located.items()
    )


def _issues_for(confidence: Confidence) -> list[ClauseIssue]:
    return [ClauseIssue.LOW_CONFIDENCE] if confidence is Confidence.LOW else []


def _located_clause(source: SourceText, item: LLMClause, start: int, end: int) -> ExtractedClause:
    text = source.text[start:end].rstrip()
    issues = _issues_for(item.confidence)
    return ExtractedClause(
        number=item.number,
        title=item.title,
        clause_type=item.clause_type,
        text=text,
        start_page=source.page_at(start),
        end_page=source.page_at(start + max(len(text) - 1, 0)),
        subsection_numbers=item.subsection_numbers,
        confidence=item.confidence,
        needs_review=bool(issues),
        issues=issues,
    )


def _unlocated_clause(item: LLMClause) -> ExtractedClause:
    return ExtractedClause(
        number=item.number,
        title=item.title,
        clause_type=item.clause_type,
        text="",
        start_page=None,
        end_page=None,
        subsection_numbers=item.subsection_numbers,
        confidence=item.confidence,
        needs_review=True,
        issues=[ClauseIssue.ANCHOR_NOT_FOUND, *_issues_for(item.confidence)],
    )


# --- coverage helpers ----------------------------------------------------------------------


def _first_int(number: str | None) -> int | None:
    match = _DIGITS.search(number or "")
    return int(match.group()) if match else None


def _label(clause: ExtractedClause) -> str:
    return clause.number or clause.title or clause.clause_type.value


def _numbering_gaps(placed: list[PlacedClause]) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    previous: tuple[int, ExtractedClause] | None = None
    for clause in (p.clause for p in placed):
        value = _first_int(clause.number)
        if value is None or clause.clause_type is ClauseType.EXHIBIT:
            continue
        if previous is not None and value > previous[0] + 1:
            before = previous[1]
            warnings.append(
                ExtractionWarning(
                    code=WarningCode.NUMBERING_GAP,
                    message=f"Clause numbering jumps from {before.number} to {clause.number}; "
                    "a clause may be missing.",
                    start_page=before.start_page,
                    end_page=clause.start_page,
                    details={"after": before.number, "next": clause.number},
                )
            )
        previous = (value, clause)  # a decrease (numbering restarts) starts a new sequence
    return warnings


def _uncovered_prefix(placed: list[PlacedClause], source: SourceText) -> list[ExtractionWarning]:
    first = next((p for p in placed if p.offset is not None), None)
    end = first.offset if first is not None and first.offset is not None else len(source.text)
    chars = sum(1 for char in source.text[:end] if not char.isspace())
    if chars < MIN_UNCOVERED_CHARS:
        return []
    return [
        ExtractionWarning(
            code=WarningCode.UNCOVERED_TEXT,
            message=f"{chars} characters before the first clause are not part of any clause "
            "(often a cover page or table of contents).",
            start_page=source.page_at(0),
            end_page=source.page_at(max(end - 1, 0)),
            details={"chars": chars},
        )
    ]


def _unlocated_clauses(placed: list[PlacedClause]) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    container: ExtractedClause | None = None
    for p in placed:
        if p.offset is not None:
            container = p.clause
            continue
        if container is not None:
            _flag_may_contain_missing(container)
        where = f"clause '{_label(container)}'" if container else "the text before the first clause"
        warnings.append(
            ExtractionWarning(
                code=WarningCode.ANCHOR_NOT_FOUND,
                message=f"Clause '{_label(p.clause)}' was reported by the model, but its start "
                f"was not found in the source; its text is probably inside {where}.",
                start_page=container.start_page if container else None,
                end_page=container.end_page if container else None,
                details={
                    "clause": _label(p.clause),
                    "likely_inside": _label(container) if container else None,
                },
            )
        )
    return warnings


def _failed_pages(
    placed: list[PlacedClause], source: SourceText, succeeded: list[Chunk], failed: list[Chunk]
) -> list[ExtractionWarning]:
    """Source ranges that only failed chunks covered (by offsets, so a failed piece of a split
    page is caught even though a successful chunk covered the same page number)."""
    lost = _subtract([(c.start, c.end) for c in failed], [(c.start, c.end) for c in succeeded])
    lost = [_trim(source.text, start, end) for start, end in lost]
    lost = [(start, end) for start, end in lost if start < end]  # whitespace-only gaps
    for start, _ in lost:
        container = next(
            (p.clause for p in reversed(placed) if p.offset is not None and p.offset < start), None
        )
        if container is not None:
            _flag_may_contain_missing(container)
    return [
        ExtractionWarning(
            code=WarningCode.CHUNK_FAILED,
            message=(
                f"Pages {source.page_at(start)}-{source.page_at(end - 1)} could not be processed "
                "by the model; clauses starting there may be missing."
                if source.has_page_numbers
                else f"Characters {start}-{end} could not be processed by the model; "
                "clauses starting there may be missing."
            ),
            start_page=source.page_at(start),
            end_page=source.page_at(end - 1),
            details={"start_char": start, "end_char": end},
        )
        for start, end in lost
    ]


def _flag_may_contain_missing(clause: ExtractedClause) -> None:
    if ClauseIssue.MAY_CONTAIN_MISSING_CLAUSE not in clause.issues:
        clause.issues.append(ClauseIssue.MAY_CONTAIN_MISSING_CLAUSE)
    clause.needs_review = True


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _subtract(
    ranges: list[tuple[int, int]], covered: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Parts of `ranges` not inside any `covered` range, merged and sorted."""
    pieces = sorted(ranges)
    for c_start, c_end in covered:
        pieces = [
            part
            for start, end in pieces
            for part in ((start, min(end, c_start)), (max(start, c_end), end))
            if part[0] < part[1]
        ]
    merged: list[tuple[int, int]] = []
    for start, end in sorted(pieces):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged
