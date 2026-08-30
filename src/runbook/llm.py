"""The single place model calls go through.

Provider: **OpenRouter** (OpenAI-compatible), free models — see `docs/adr/0009`.
Deliberately thin — no agent framework (ADR-0001). Routing, retry, S5 redaction
(`_redact_outgoing`, the choke point — ADR-0011), and (later) tracing hook in
here rather than being scattered across call sites.

Three primitives, provider-neutral return types so the loop never imports
`openai`:

- `complete`  — one-shot text (the Week 0 demo endpoint).
- `run_turn`  — one turn of a tool-use loop; returns a `Turn`. The caller owns
  the loop and executes the tools (see `core/loop.py`).
- `parse`     — one structured-output call, validated against a Pydantic model.
  Raises `LLMParseError` when the model can't produce valid output.

Free-tier reality (ADR-0009): 20 requests/min, and free endpoints on shared
capacity 5xx more than a paid API. `_call_with_retry` backs off on 429/5xx
(honouring `Retry-After`); `parse` additionally retries a refusal / unparseable
response a few times before giving up.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from langfuse.openai import AsyncOpenAI  # drop-in wrapper: auto-traces every call (ADR-0017)
from openai import APIConnectionError, APIStatusError, RateLimitError
from pydantic import BaseModel, ValidationError

from .config import get_settings
from .redact import redact as _redact

_client: AsyncOpenAI | None = None

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMParseError(RuntimeError):
    """The model returned no output that validates against the requested schema
    (a refusal, a truncation, or malformed JSON), after retries."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # the model that actually served the call (OpenRouter's echoed `resp.model`) —
    # not always the one requested, since the fallback chain may have walked past
    # it. `core/loop.py` attributes cost per this. See `core/cost.py`.
    model: str = ""


@dataclass
class ToolRequest:
    """A tool the model wants executed this turn."""

    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """The result of one tool-loop turn, provider-neutral."""

    text: str
    tool_requests: list[ToolRequest] = field(default_factory=list)
    stop_reason: Literal["tool_calls", "stop", "length", "other"] = "stop"
    usage: Usage = field(default_factory=Usage)
    # the assistant message to append to history, in OpenAI chat shape
    assistant_message: dict = field(default_factory=dict)


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            base_url=s.openrouter_base_url,
            api_key=s.openrouter_api_key,
            default_headers={"HTTP-Referer": s.openrouter_referer, "X-Title": s.openrouter_title},
            max_retries=0,  # we own the retry loop (429-aware, Retry-After honoured)
        )
    return _client


def _with_system(messages: list[dict], system: str | None) -> list[dict]:
    if not system:
        return messages
    return [{"role": "system", "content": system}, *messages]


def _redact_outgoing(messages: list[dict]) -> list[dict]:
    """S5 choke point (ADR-0011): scrub secrets / PII from every string that
    leaves for the provider — `system` included, since `_with_system` has
    already folded it in. Idempotent, so re-scrubbing content `core/loop.py`
    already redacted is a no-op. Non-string content (an assistant tool-call
    message carries `content: None`) passes through untouched."""
    out: list[dict] = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and c:
            r = _redact(c)
            if r.count:
                m = {**m, "content": r.text}
        out.append(m)
    return out


def _usage(u: object | None, model: str = "") -> Usage:
    if u is None:
        return Usage(model=model)
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        model=model,
    )


def _served_model(resp: object) -> str:
    """The model OpenRouter actually routed to, for cost attribution."""
    return (getattr(resp, "model", "") or "").strip()


def _norm_finish(reason: str | None) -> Literal["tool_calls", "stop", "length", "other"]:
    if reason in ("tool_calls", "stop", "length"):
        return reason  # type: ignore[return-value]
    return "other"


_MAX_CHAIN = 3  # OpenRouter caps the `models` fallback array at 3


def _extra_body(model: str, fallbacks: Sequence[str], reasoning_effort: str | None) -> dict:
    """OpenRouter request extras: a model-fallback chain (free `:free` endpoints
    each sit on one shared provider pool and 429 often — OpenRouter walks this
    list on error), and reasoning kept internal so it never bleeds into
    `.content` / structured output."""
    body: dict = {"reasoning": {"exclude": True}}
    if reasoning_effort:
        body["reasoning"]["effort"] = reasoning_effort
    chain = list(dict.fromkeys([model, *fallbacks]))[:_MAX_CHAIN]  # de-dup, keep order, cap at 3
    if len(chain) > 1:
        body["models"] = chain
    return body


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def _call_with_retry(make_call, *, what: str):
    """Await `make_call()`, retrying 429/5xx/connection errors with backoff."""
    settings = get_settings()
    last_exc: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return await make_call()
        except RateLimitError as exc:
            last_exc = exc
        except APIStatusError as exc:
            if exc.status_code not in _RETRYABLE_STATUS:
                raise
            last_exc = exc
        except APIConnectionError as exc:
            last_exc = exc

        if attempt >= settings.llm_max_retries:
            break
        delay = _retry_after(last_exc) or min(30.0, 1.5 * (2**attempt))
        await asyncio.sleep(delay + random.uniform(0, 0.5))
    assert last_exc is not None
    raise last_exc


async def complete(
    prompt: str,
    *,
    model: str,
    system: str | None = None,
    max_tokens: int = 512,
    fallbacks: Sequence[str] = (),
    trace_name: str = "complete",
) -> str:
    """One-shot completion. Returns the response text. `trace_name` labels the
    generation in Langfuse (ADR-0017); the wrapper strips it before the API call."""
    msgs = _redact_outgoing(_with_system([{"role": "user", "content": prompt}], system))
    resp = await _call_with_retry(
        lambda: get_client().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=msgs,
            extra_body=_extra_body(model, fallbacks, None),
            name=trace_name,
        ),
        what="complete",
    )
    return resp.choices[0].message.content or ""


async def run_turn(
    messages: list[dict],
    *,
    model: str,
    system: str,
    tools: list[dict],
    max_tokens: int = 2048,
    reasoning_effort: str | None = None,
    fallbacks: Sequence[str] = (),
    trace_name: str = "tool-turn",
) -> Turn:
    """One turn of a tool-use loop. The caller inspects `stop_reason`, executes
    any `tool_requests`, appends the tool results + `assistant_message` to
    history, and calls again."""
    msgs = _redact_outgoing(_with_system(messages, system))
    resp = await _call_with_retry(
        lambda: get_client().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=msgs,
            tools=tools,
            extra_body=_extra_body(model, fallbacks, reasoning_effort),
            name=trace_name,
        ),
        what="run_turn",
    )
    choice = resp.choices[0]
    msg = choice.message

    requests: list[ToolRequest] = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        requests.append(
            ToolRequest(
                id=tc.id, name=tc.function.name, arguments=args if isinstance(args, dict) else {}
            )
        )

    assistant_message: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        assistant_message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]

    return Turn(
        text=msg.content or "",
        tool_requests=requests,
        stop_reason=_norm_finish(choice.finish_reason),
        usage=_usage(resp.usage, _served_model(resp)),
        assistant_message=assistant_message,
    )


def _json_schema_format(schema: type[BaseModel]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "strict": True,
            "schema": schema.model_json_schema(),
        },
    }


def _content(resp: object) -> str | None:
    """The assistant text, or None if the provider returned no usable choice
    (OpenRouter can hand back a 200 whose body is a mid-stream provider error)."""
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return None
    return choices[0].message.content


async def parse[M: BaseModel](
    messages: list[dict],
    *,
    model: str,
    system: str,
    schema: type[M],
    max_tokens: int = 4096,
    fallbacks: Sequence[str] = (),
    trace_name: str = "parse",
) -> tuple[M, Usage]:
    """One structured-output call. Returns `(validated instance, usage)`.

    Uses `create` + manual validation rather than the SDK's `.parse()` helper —
    that helper `TypeError`s on OpenRouter's non-standard error bodies, and free
    models emit off-schema JSON often enough that we need to own the retry.
    Retries a refusal / truncation / off-schema / no-choice response, then raises
    `LLMParseError` (callers that can degrade — the loop's synthesis — catch it)."""
    settings = get_settings()
    msgs = _redact_outgoing(_with_system(messages, system))
    extra_body = _extra_body(model, fallbacks, None)
    # only route to endpoints that honour response_format — else a free model
    # cheerfully replies in prose
    extra_body.setdefault("provider", {})["require_parameters"] = True
    fmt = _json_schema_format(schema)
    last_reason = "no output"

    for attempt in range(settings.llm_max_retries + 1):
        resp = await _call_with_retry(
            lambda: get_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=msgs,
                response_format=fmt,
                extra_body=extra_body,
                name=trace_name,
            ),
            what="parse",
        )
        content = _content(resp)
        if content is None:
            last_reason = "provider returned no choice (mid-stream error)"
        elif not content.strip():
            last_reason = "empty response (likely truncated on reasoning)"
        else:
            try:
                return schema.model_validate_json(content), _usage(resp.usage, _served_model(resp))
            except ValidationError as exc:
                last_reason = f"off-schema output ({str(exc)[:200]})"

        if attempt < settings.llm_max_retries:
            await asyncio.sleep(1.0 + attempt)

    raise LLMParseError(f"{model}: no valid {schema.__name__} after retries — {last_reason}")
