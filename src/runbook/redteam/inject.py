"""Splice one attack payload into one surface, for the duration of one
`diagnose()` call, then restore.

The interception points are the two module-level names `core/loop.py` binds:

- `runbook.core.loop.run_tool`  — wrapped so a `search_logs` result gains one
  extra "log line" carrying the payload (the `log` surface).
- `runbook.core.loop.retrieve`  — wrapped so the payload is prepended as the top
  retrieved chunk, i.e. it *becomes* the primary runbook (the `doc` surface).

The `alert` surface needs no patch — the runner appends the payload to the alert
string before calling `diagnose()`.

Everything is a context manager so a test (or a bad case) can't leak a patch into
the next run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from ..rag import RetrievedChunk
from .attacks import AttackCase

_POISON_TS = "2026-01-01T00:00:00+00:00"


def _poison_log_line(payload: str) -> dict:
    """One extra entry in a `search_logs` result, shaped like the real ones
    (`tools._jsonable(LogMatch)`)."""
    rendered = f"{_POISON_TS} WARN  paymentsvc {payload}"
    return {
        "ts": _POISON_TS,
        "level": "WARN",
        "service": "paymentsvc",
        "message": payload,
        "line": rendered,
    }


def _wrap_run_tool(real, payload: str):
    def wrapped(name, scenario, tool_input):
        out, is_error = real(name, scenario, tool_input)
        if name != "search_logs" or is_error:
            return out, is_error
        try:
            doc = json.loads(out)
        except (ValueError, TypeError):
            return out, is_error
        matches = doc.get("matches")
        if isinstance(matches, list):
            matches.append(_poison_log_line(payload))
            doc["total_scanned"] = int(doc.get("total_scanned", len(matches))) + 1
            doc["hint"] = ""
        return json.dumps(doc, default=str), is_error

    return wrapped


def _poison_chunk(case: AttackCase) -> RetrievedChunk:
    return RetrievedChunk(
        id=-1,
        title="paymentsvc — incident runbook",
        url=None,
        source="attacker-controlled",
        origin="paymentsvc",
        path=None,  # no on-disk path → `_full_doc` falls back to chunk_text
        heading_path=["Remediation"],
        chunk_text=case.payload,
        scores={"rrf": 999.0},
    )


def _wrap_retrieve(real, case: AttackCase):
    def wrapped(query, k=4, *args, **kwargs):
        hits = list(real(query, k, *args, **kwargs))
        return [_poison_chunk(case), *hits]

    return wrapped


@contextmanager
def injected(case: AttackCase) -> Iterator[None]:
    """Patch the surface named by `case.surface`. `alert` is a no-op here."""
    from runbook.core import loop

    with ExitStack() as stack:
        if case.surface == "log":
            stack.enter_context(
                patch.object(loop, "run_tool", _wrap_run_tool(loop.run_tool, case.payload))
            )
        elif case.surface == "doc":
            stack.enter_context(patch.object(loop, "retrieve", _wrap_retrieve(loop.retrieve, case)))
        elif case.surface == "alert":
            pass
        else:  # pragma: no cover - guarded by the dataclass Literal
            raise ValueError(f"unknown surface {case.surface!r}")
        yield


def alert_for(case: AttackCase, base_alert: str) -> str:
    """The alert text to pass to `diagnose()` — the payload appended for the
    `alert` surface, unchanged otherwise."""
    return base_alert + case.payload if case.surface == "alert" else base_alert
