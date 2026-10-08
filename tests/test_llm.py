"""ClauseLLM against a mocked Anthropic client: no network, no API key.

The fake mimics `beta.messages.create` at the response level (content blocks, stop_reason,
usage), so our own stop_reason handling and Pydantic validation are what is under test."""

import asyncio
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.schemas.enums import ClauseType, Confidence
from app.schemas.llm import ChunkExtraction, LLMClause
from app.services.llm import ClauseLLM, LLMError

VALID = ChunkExtraction(
    clauses=[
        LLMClause(
            number="1",
            title="Scope",
            clause_type=ClauseType.OTHER,
            start_anchor="1. Scope. This Agreement",
            subsection_numbers=[],
            confidence=Confidence.HIGH,
        )
    ]
)


def _response(text: str, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5"):
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    content = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ]
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage, model=model)


class FakeClient:
    """Mimics `AsyncAnthropic().beta.messages.create`, replaying scripted outcomes."""

    def __init__(self, *outcomes: Any):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _extract(client: FakeClient):
    llm = ClauseLLM(Settings(anthropic_api_key="test"), client=client)  # type: ignore[arg-type]
    return asyncio.run(llm.extract_chunk("[[PAGE 1]]\n1. Scope. This Agreement covers ..."))


def test_valid_output_is_returned_with_usage_and_actual_model() -> None:
    client = FakeClient(_response(VALID.model_dump_json(), model="fallback-model"))
    result = _extract(client)

    assert result.extraction == VALID
    assert (result.input_tokens, result.output_tokens) == (100, 10)
    assert result.model == "fallback-model"
    call = client.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in call  # forced tool use is rejected by current models


def test_invalid_output_is_retried_once_with_the_answer_and_error() -> None:
    bad = _response('{"clauses": [{"number": "1"}]}')
    client = FakeClient(bad, _response(VALID.model_dump_json()))
    result = _extract(client)

    assert result.extraction == VALID
    assert result.input_tokens == 200  # the failed attempt is billed and counted
    retry = client.calls[1]["messages"]
    assert retry[1] == {"role": "assistant", "content": bad.content}  # append-only history
    assert "failed validation" in retry[2]["content"]
    assert "clauses.0.start_anchor" in retry[2]["content"]


def test_invalid_output_twice_raises_with_tokens() -> None:
    client = FakeClient(_response("not json"), _response("still not json"))
    with pytest.raises(LLMError, match="invalid output twice") as exc_info:
        _extract(client)
    assert exc_info.value.input_tokens == 200


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
def test_truncated_output_fails_immediately(stop_reason: str) -> None:
    client = FakeClient(_response('{"clauses": [', stop_reason=stop_reason))
    with pytest.raises(LLMError, match="cut off") as exc_info:
        _extract(client)
    assert len(client.calls) == 1
    assert exc_info.value.output_tokens == 10


def test_refusal_fails_immediately() -> None:
    client = FakeClient(_response("I can't help with that.", stop_reason="refusal"))
    with pytest.raises(LLMError, match="declined"):
        _extract(client)
    assert len(client.calls) == 1


def test_api_errors_raise_llm_error() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(LLMError, match="APITimeoutError"):
        _extract(FakeClient(anthropic.APITimeoutError(request=request)))
