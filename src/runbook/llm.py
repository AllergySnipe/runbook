"""The single place model calls go through.

Deliberately thin — no agent framework (see docs/adr/0001). Tracing, redaction,
and routing will hook in here later rather than being scattered across call sites.

Three primitives:
- `complete`  — one-shot text (the Week 0 demo endpoint).
- `run_turn`  — one turn of a tool-use loop; the caller owns the loop and executes
  the tools (see `core/loop.py`). Kept here so every model call has one choke point.
- `parse`     — one structured-output call, validated against a Pydantic model.
"""

from __future__ import annotations

import anthropic
from pydantic import BaseModel

from .config import get_settings

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


async def complete(
    prompt: str,
    *,
    model: str,
    system: str | None = None,
    max_tokens: int = 512,
) -> str:
    """One-shot completion. Returns the concatenated text blocks of the response."""
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system

    response = await get_client().messages.create(**kwargs)
    return "".join(block.text for block in response.content if block.type == "text")


async def run_turn(
    messages: list[dict],
    *,
    model: str,
    system: str,
    tools: list[dict],
    max_tokens: int = 2048,
) -> anthropic.types.Message:
    """One turn of a tool-use loop. Returns the raw response — the caller inspects
    `stop_reason`, executes any `tool_use` blocks, and calls again. Adaptive
    thinking is on (Sonnet 5 accepts no other on-mode)."""
    return await get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        thinking={"type": "adaptive"},
        messages=messages,
    )


async def parse[M: BaseModel](
    messages: list[dict],
    *,
    model: str,
    system: str,
    schema: type[M],
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
) -> tuple[M, anthropic.types.Usage]:
    """One structured-output call. Returns `(validated instance, usage)`.

    `tools` can be passed (with `tool_choice=none`) when the message history
    already contains `tool_use` blocks — the API wants the definitions present
    even though no tool may be called on this turn."""
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_format": schema,
    }
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = {"type": "none"}
    response = await get_client().messages.parse(**kwargs)
    return response.parsed_output, response.usage
