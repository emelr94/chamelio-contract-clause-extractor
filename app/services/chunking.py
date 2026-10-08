"""Lay the document out as one string and cut it into page-aligned, overlapping chunks."""

import bisect
from dataclasses import dataclass

from app.services.parsing import ParsedDocument

PAGE_SEPARATOR = "\n"


@dataclass(frozen=True)
class SourceText:
    """All pages joined into one string, with the offset where each page starts."""

    text: str
    page_starts: list[int]
    has_page_numbers: bool

    @classmethod
    def from_document(cls, document: ParsedDocument) -> "SourceText":
        starts, offset = [], 0
        for page in document.pages:
            starts.append(offset)
            offset += len(page) + len(PAGE_SEPARATOR)
        return cls(PAGE_SEPARATOR.join(document.pages), starts, document.has_page_numbers)

    def page_at(self, offset: int) -> int | None:
        """1-based page number containing `offset`, or None when pages are meaningless."""
        if not self.has_page_numbers:
            return None
        return bisect.bisect_right(self.page_starts, offset)

    def page_range(self, page_index: int) -> tuple[int, int]:
        end = (
            self.page_starts[page_index + 1] - len(PAGE_SEPARATOR)
            if page_index + 1 < len(self.page_starts)
            else len(self.text)
        )
        return self.page_starts[page_index], end


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    page_index: int


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int  # offsets into SourceText.text; anchors are searched only inside [start, end)
    end: int
    text: str  # what the LLM sees: source slice with [[PAGE n]] markers
    first_page: int | None
    last_page: int | None


def build_chunks(source: SourceText, max_chars: int) -> list[Chunk]:
    """Greedily pack whole pages up to `max_chars`; the last page of each chunk is repeated at
    the start of the next one so a clause cut at a boundary is seen whole at least once."""
    segments = _segments(source, max_chars)
    groups: list[list[Segment]] = []
    i = 0
    while i < len(segments):
        j, size = i, 0
        while j < len(segments) and (j == i or size + _len(segments[j]) <= max_chars):
            size += _len(segments[j])
            j += 1
        groups.append(segments[i:j])
        if j >= len(segments):
            break
        i = j - 1 if j - 1 > i else j  # overlap one segment, but always make progress
    return [_to_chunk(index, group, source) for index, group in enumerate(groups)]


def _segments(source: SourceText, max_chars: int) -> list[Segment]:
    """One segment per page; a page longer than `max_chars` is split at line breaks."""
    segments = []
    for page_index in range(len(source.page_starts)):
        start, end = source.page_range(page_index)
        while end - start > max_chars:
            cut = source.text.rfind("\n", start + 1, start + max_chars)
            cut = cut if cut > start else start + max_chars
            segments.append(Segment(start, cut, page_index))
            start = cut
        segments.append(Segment(start, end, page_index))
    return segments


def _len(segment: Segment) -> int:
    return segment.end - segment.start


def _to_chunk(index: int, group: list[Segment], source: SourceText) -> Chunk:
    parts, previous_page = [], None
    for segment in group:
        if source.has_page_numbers and segment.page_index != previous_page:
            parts.append(f"[[PAGE {segment.page_index + 1}]]\n")
        parts.append(source.text[segment.start : segment.end] + "\n")
        previous_page = segment.page_index
    first, last = group[0], group[-1]
    return Chunk(
        index=index,
        start=first.start,
        end=last.end,
        text="".join(parts),
        first_page=source.page_at(first.start),
        last_page=source.page_at(max(last.start, last.end - 1)),
    )
