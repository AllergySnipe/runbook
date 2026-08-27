"""The single place model calls go through.

Deliberately thin — no agent framework (see docs/adr/0001). Tracing, redaction,
and routing will hook in here later rather than being scattered across call sites.
"""

import anthropic

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
