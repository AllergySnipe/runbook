"""The provider layer (ADR-0009): retry/backoff, the model-fallback chain, and
`parse` refusing to accept prose. Deterministic — a fake OpenAI client, no
network. The real end-to-end check is `runbook diagnose` / the eval.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from runbook import llm


class Tiny(BaseModel):
    ok: bool


# --- fake OpenAI client -----------------------------------------------------


def _msg(*, content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _resp(*, finish_reason="stop", prompt=10, completion=5, no_choice=False, **msg_kw):
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    if no_choice:  # OpenRouter 200 whose body is a mid-stream provider error
        return SimpleNamespace(choices=None, usage=usage)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=_msg(**msg_kw), finish_reason=finish_reason)],
        usage=usage,
    )


def _tool_call(id_, name, arguments):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=arguments))


def _rate_limit():
    r = httpx.Response(429, headers={"retry-after": "0"}, request=httpx.Request("POST", "http://x"))
    return openai.RateLimitError("rate limited", response=r, body=None)


def _status(code):
    r = httpx.Response(code, request=httpx.Request("POST", "http://x"))
    return openai.APIStatusError(f"http {code}", response=r, body=None)


class _FakeCompletions:
    """Every llm primitive goes through `chat.completions.create` now."""

    def __init__(self):
        self.create_seq: list = []
        self.create_calls: list[dict] = []

    async def create(self, **kw):
        self.create_calls.append(kw)
        seq = self.create_seq
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def fake(monkeypatch):
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm, "get_client", lambda: client)

    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    return completions


def _await(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --- _extra_body ------------------------------------------------------------


def test_extra_body_chain_and_reasoning():
    body = llm._extra_body("primary", ["fb1", "fb2"], None)
    assert body["models"] == ["primary", "fb1", "fb2"]
    assert body["reasoning"] == {"exclude": True}

    assert "models" not in llm._extra_body("primary", [], None)  # no chain when no fallbacks
    # de-dup, order preserved (a caller's fallbacks list often repeats the primary)
    assert llm._extra_body("a", ["a", "b", "a"], None)["models"] == ["a", "b"]
    assert "models" not in llm._extra_body("a", ["a"], None)  # collapses to one → no chain
    assert llm._extra_body("a", ["b", "c", "d", "e"], None)["models"] == [
        "a",
        "b",
        "c",
    ]  # capped at 3
    assert llm._extra_body("m", [], "high")["reasoning"] == {"exclude": True, "effort": "high"}


# --- run_turn mapping ------------------------------------------------------


def test_run_turn_text_answer(fake):
    fake.create_seq = [_resp(content="had a look", finish_reason="stop")]
    turn = _await(llm.run_turn([], model="m", system="s", tools=[]))
    assert turn.text == "had a look"
    assert turn.stop_reason == "stop"
    assert turn.tool_requests == []
    assert turn.usage.input_tokens == 10 and turn.usage.output_tokens == 5
    assert turn.assistant_message == {"role": "assistant", "content": "had a look"}


def test_run_turn_tool_calls(fake):
    fake.create_seq = [
        _resp(
            content=None,
            tool_calls=[_tool_call("t1", "query_metrics", '{"metric": "x"}')],
            finish_reason="tool_calls",
        )
    ]
    turn = _await(llm.run_turn([], model="m", system="s", tools=[]))
    assert turn.stop_reason == "tool_calls"
    assert turn.tool_requests == [llm.ToolRequest("t1", "query_metrics", {"metric": "x"})]
    assert turn.assistant_message["tool_calls"][0]["function"]["name"] == "query_metrics"


def test_run_turn_bad_tool_json_is_empty_args(fake):
    fake.create_seq = [
        _resp(
            tool_calls=[_tool_call("t1", "search_logs", "{not valid")], finish_reason="tool_calls"
        )
    ]
    turn = _await(llm.run_turn([], model="m", system="s", tools=[]))
    assert turn.tool_requests[0].arguments == {}


def test_run_turn_sends_the_fallback_chain(fake):
    fake.create_seq = [_resp(content="ok")]
    _await(llm.run_turn([], model="glm", system="s", tools=[], fallbacks=["mm3", "mm2"]))
    assert fake.create_calls[0]["extra_body"]["models"] == ["glm", "mm3", "mm2"]


# --- retry / backoff -----------------------------------------------------


def test_retry_recovers_after_a_429(fake):
    fake.create_seq = [_rate_limit(), _resp(content="recovered")]
    assert _await(llm.complete("hi", model="m")) == "recovered"
    assert len(fake.create_calls) == 2


def test_retry_gives_up_and_reraises(fake, monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(llm_max_retries=2))
    fake.create_seq = [_rate_limit()]
    with pytest.raises(openai.RateLimitError):
        _await(llm.complete("hi", model="m"))
    assert len(fake.create_calls) == 3  # initial + 2 retries


def test_retry_does_not_touch_a_400(fake):
    fake.create_seq = [_status(400)]
    with pytest.raises(openai.APIStatusError):
        _await(llm.complete("hi", model="m"))
    assert len(fake.create_calls) == 1


def test_retry_retries_a_502(fake):
    fake.create_seq = [_status(502), _resp(content="ok")]
    assert _await(llm.complete("hi", model="m")) == "ok"


# --- parse: create + manual validation, won't accept prose ------------------


def test_parse_validates_the_json_content(fake):
    fake.create_seq = [_resp(content='{"ok": true}')]
    obj, usage = _await(llm.parse([], model="m", system="s", schema=Tiny))
    assert obj == Tiny(ok=True)
    assert usage.input_tokens == 10


def test_parse_sets_require_parameters_and_chain(fake):
    fake.create_seq = [_resp(content='{"ok": true}')]
    _await(llm.parse([], model="glm", system="s", schema=Tiny, fallbacks=["nemo"]))
    body = fake.create_calls[0]["extra_body"]
    assert body["provider"]["require_parameters"] is True
    assert body["models"] == ["glm", "nemo"]
    assert fake.create_calls[0]["response_format"]["type"] == "json_schema"


def test_parse_retries_prose_then_raises(fake, monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(llm_max_retries=3))
    fake.create_seq = [_resp(content="known-runbook — this is prose, not JSON")]
    with pytest.raises(llm.LLMParseError):
        _await(llm.parse([], model="m", system="s", schema=Tiny))
    assert len(fake.create_calls) == 4  # initial + 3 retries, then give up


def test_parse_retries_off_schema_json_then_succeeds(fake):
    fake.create_seq = [_resp(content='{"ok": "high"}'), _resp(content='{"ok": false}')]
    obj, _ = _await(llm.parse([], model="m", system="s", schema=Tiny))
    assert obj == Tiny(ok=False)
    assert len(fake.create_calls) == 2


def test_parse_retries_a_no_choice_body_then_raises(fake, monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(llm_max_retries=1))
    fake.create_seq = [_resp(no_choice=True)]  # OpenRouter mid-stream error body
    with pytest.raises(llm.LLMParseError):
        _await(llm.parse([], model="m", system="s", schema=Tiny))
    assert len(fake.create_calls) == 2


def test_parse_retries_an_empty_content_then_succeeds(fake):
    fake.create_seq = [_resp(content="   "), _resp(content='{"ok": true}')]
    obj, _ = _await(llm.parse([], model="m", system="s", schema=Tiny))
    assert obj == Tiny(ok=True)
