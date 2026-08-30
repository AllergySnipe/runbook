"""The baseline ("prompt defences off") condition.

`run_attacks(condition="baseline")` runs the loop with the *probabilistic*,
prompt-level defences neutralised, so we can measure what they buy:

- **Untrusted-content delimiting** — `core/loop.py`'s `load_prompt` is redirected
  to the stripped variants in `redteam/prompts_nodelim/` (no `<runbook>` fences,
  no "reference data, not instructions" paragraph).
- **The Haiku second pass** — `guardrail.second_pass` is short-circuited to "no
  concerns".

The *structural* invariants stay ON in both conditions — grounding enforcement,
`classify_steps`, the approval gate, and redaction. An attacker cannot disable
your code; the honest question is "with every prompt defence off, does the
structural gate still hold?" (ADR-0012).

Done by monkeypatch, not a `diagnose(harden=…)` flag: the production signature
stays clean and the ablation is a ~15-line, reviewable diff in one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from ..prompts import load as _real_load

_NODELIM_DIR = Path(__file__).resolve().parent / "prompts_nodelim"
_STRIPPED = {"diagnose", "synthesize", "guardrail"}


@lru_cache
def _nodelim_raw(name: str) -> str:
    return (_NODELIM_DIR / f"{name}.md").read_text().strip()


def _load_nodelim(name: str, **kw: object) -> str:
    """Drop-in for `prompts.load`: stripped text for the three loop prompts,
    the real prompt for everything else."""
    if name not in _STRIPPED:
        return _real_load(name, **kw)
    text = _nodelim_raw(name)
    return text.format(**kw) if kw else text


async def _noop_second_pass(steps, runbook_text, *, model, fallbacks=()):
    return [], None


@contextmanager
def prompt_defences_disabled() -> Iterator[None]:
    from runbook.core import loop

    with ExitStack() as stack:
        stack.enter_context(patch.object(loop, "load_prompt", _load_nodelim))
        stack.enter_context(patch.object(loop, "second_pass", _noop_second_pass))
        yield
