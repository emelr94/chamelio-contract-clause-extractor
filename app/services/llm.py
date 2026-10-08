"""The only module that talks to the LLM. Everything else depends on `ClauseLLM` (through the
`ChunkSegmenter` protocol), so tests can replace it with a fake."""

import logging
from dataclasses import dataclass
from typing import Any

import anthropic
from pydantic import ValidationError

from app.config import Settings
from app.schemas.enums import ClauseType
from app.schemas.llm import ChunkExtraction

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v3"  # v2: slices may start inside a clause; v3: confidence rubric
MAX_OUTPUT_TOKENS = 16_000
TRUNCATED_STOP_REASONS = {"max_tokens", "model_context_window_exceeded"}
# Sampling: no temperature is sent. Claude Sonnet 5.5 rejects non-default values (verified:
# temperature=0 -> 400 "`temperature` is deprecated for this model"), and SDK 1.x removed the
# parameter, so calls run at the API default (1.0). Results can vary between runs; stability
# comes from the output schema and the deterministic alignment, and should be measured by an eval.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OUTPUT_FORMAT = {"type": "json_schema", "schema": anthropic.transform_schema(ChunkExtraction)}

SYSTEM_PROMPT = f"""You segment legal contracts into clauses.

You receive a slice of a contract's extracted text. Page boundaries are marked as [[PAGE n]].
Return every TOP-LEVEL clause that STARTS in this slice, in document order.

What counts as a clause:
- Each top-level numbered or headed section ("1.", "5. Term and Termination", "ARTICLE 2",
  "TERM AND TERMINATION."). Subsections (2.1, (a), (i)) stay inside their parent clause;
  list their numbers in subsection_numbers instead of returning them as clauses.
- The opening part before the first numbered clause (title, parties, recitals): one clause of
  type "preamble".
- The signature block: one clause of type "signature_block".
- Each exhibit, schedule, appendix or attachment: one clause of type "exhibit"; do not split
  its contents further.

Ignore:
- Table-of-contents entries (headings followed by dots and page numbers). They are NOT clauses.
- Running page headers/footers and page numbers.
- A clause that started before this slice and merely continues at its top. A slice can begin
  in the middle of a long article: subsections such as "5.13" or "28.1.2" whose parent heading
  ("ARTICLE 5", "28.") is not in the slice are continuations, not clauses.

start_anchor must be copied character-for-character from the text (same words, same order,
including the number), so it can be located by exact search. Do not fix typos or spacing.

clause_type is one of: {", ".join(t.value for t in ClauseType)}.
Pick the main topic; use "general_provisions" for boilerplate such as severability, entire
agreement, amendments, waiver, counterparts; "other" only if nothing fits.
confidence (it triggers human review, so be calibrated):
- "high": the clause start is clear and the type fits. This is the normal case for clean,
  numbered text.
- "medium": the start is clear but the type is a judgment call between two types.
- "low": you doubt the clause START itself, e.g. garbled text, a missing or ambiguous heading,
  or you cannot tell whether it is a new clause or a continuation."""


class LLMError(Exception):
    """The LLM call failed, or never produced a usable result. Carries the tokens spent."""

    def __init__(self, message: str, *, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class ChunkResult:
    extraction: ChunkExtraction
    model: str  # may differ from the requested model if a refusal fallback ran
    input_tokens: int
    output_tokens: int


class ClauseLLM:
    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self._client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,  # SDK backs off on 429/5xx/timeouts
        )

    async def extract_chunk(self, chunk_text: str) -> ChunkResult:
        """Segment one chunk. Invalid output is retried once, showing the model its answer and
        the validation error. Truncation and refusals fail the chunk immediately."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"<contract_text>\n{chunk_text}\n</contract_text>"}
        ]
        tokens = {"input_tokens": 0, "output_tokens": 0}
        for attempt in range(2):
            try:
                response = await self._client.beta.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=messages,
                    output_config={"effort": self.effort, "format": OUTPUT_FORMAT},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",  # rerun on a substitute model if a safeguard declines
                )
            except anthropic.APIError as exc:  # the SDK has already retried transient errors
                raise LLMError(f"{type(exc).__name__}: {exc}", **tokens) from exc

            usage = response.usage  # count before validating: failed attempts are billed too
            tokens["input_tokens"] += (
                usage.input_tokens
                + (usage.cache_read_input_tokens or 0)
                + (usage.cache_creation_input_tokens or 0)
            )
            tokens["output_tokens"] += usage.output_tokens
            logger.info(
                "LLM call: model=%s stop=%s input=%d cache_read=%d cache_write=%d output=%d",
                response.model,
                response.stop_reason,
                usage.input_tokens,
                usage.cache_read_input_tokens or 0,
                usage.cache_creation_input_tokens or 0,
                usage.output_tokens,
            )

            if response.stop_reason == "refusal":
                raise LLMError("The model declined to process this text.", **tokens)
            if response.stop_reason in TRUNCATED_STOP_REASONS:
                raise LLMError(f"The answer was cut off ({response.stop_reason}).", **tokens)

            text = "".join(block.text for block in response.content if block.type == "text")
            try:
                extraction = ChunkExtraction.model_validate_json(text)
            except ValidationError as exc:
                problems = "; ".join(  # loc + msg only: never echo model output into errors
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]
                )
                logger.warning("Invalid LLM output (attempt %d): %s", attempt + 1, problems)
                messages += [
                    {"role": "assistant", "content": response.content},  # append-only history
                    {
                        "role": "user",
                        "content": f"That answer failed validation ({problems}). "
                        "Return the complete, corrected result.",
                    },
                ]
                continue
            return ChunkResult(extraction, response.model, **tokens)
        raise LLMError("The model returned invalid output twice.", **tokens)
