"""HTTP + SSE surface for the incident loop — the dashboard's backend.

The CLI drives `core/` directly; this module is the *other* face of the same
core (SPEC: "the CLI and the dashboard both drive this same orchestration
function"). It adds exactly one thing the CLI doesn't need: live progress while
a run is in flight, streamed to the browser over Server-Sent Events.

No job queue (ADR-0010). `POST /api/incidents` starts `diagnose()` as a
fire-and-forget `asyncio.Task` on the event loop and returns an id immediately;
progress is published through an in-memory registry (`_RUNS`); the finished run
is written to Postgres by `core.store.record_run` — *that* row is the durable
audit record (SPEC S6). The registry is disposable: a restart loses in-flight
runs, and that is an accepted demo-scope tradeoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .core import events as ev
from .core.events import Event
from .core.loop import diagnose
from .core.store import RunRecord, get_run, list_runs, record_run, resolve_approvals
from .sim import load_scenario

log = logging.getLogger("runbook.web")

router = APIRouter(prefix="/api")

_MAX_RETAINED = 50  # cap the in-memory registry; evict oldest finished runs beyond this
_KEEPALIVE_S = 15  # SSE comment ping so idle proxies don't drop the stream


# --- in-memory registry (the thing a job queue would replace) ----------------


@dataclass
class IncidentRun:
    id: str
    alert: str
    scenario: str
    created_at: datetime
    events: list[Event] = field(default_factory=list)
    subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)
    task: asyncio.Task | None = None
    done: bool = False

    def publish(self, e: Event) -> None:
        """Append to the replay buffer and fan out to every live SSE stream.
        Called synchronously from `diagnose()`'s `on_event` hook — which runs on
        this event loop, never a worker thread, so `put_nowait` is safe."""
        self.events.append(e)
        for q in self.subscribers:
            q.put_nowait(e)

    def finish(self) -> None:
        self.done = True
        for q in list(self.subscribers):
            q.put_nowait(None)  # sentinel — tells each stream generator to close


_RUNS: dict[str, IncidentRun] = {}


def _evict() -> None:
    if len(_RUNS) <= _MAX_RETAINED:
        return
    done = sorted((r for r in _RUNS.values() if r.done), key=lambda r: r.created_at)
    for r in done[: len(_RUNS) - _MAX_RETAINED]:
        _RUNS.pop(r.id, None)


async def _run_incident(run: IncidentRun, k: int) -> None:
    """Fire-and-forget: run the loop, persist the result, narrate the outcome."""
    try:
        result = await diagnose(run.alert, run.scenario, k=k, on_event=run.publish, use_cache=True)
        rec = await asyncio.to_thread(record_run, result, run_id=run.id)
        run.publish(ev.event(ev.FINISHED, run_id=run.id, status=rec.status))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # fire-and-forget: narrate the failure, never crash the server
        log.exception("incident %s failed", run.id)
        run.publish(ev.event(ev.ERROR, message=str(exc)))
    finally:
        run.finish()


async def shutdown() -> None:
    """Cancel any in-flight incident tasks — called from the app lifespan."""
    tasks = [r.task for r in _RUNS.values() if r.task and not r.task.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# --- request / response models ---------------------------------------------


class StartIncident(BaseModel):
    scenario: str
    alert: str | None = None
    k: int = 4


class Decision(BaseModel):
    by: str
    note: str | None = None
    step: int | None = None  # 0-based step index; None targets every pending step


# --- routes ----------------------------------------------------------------


@router.post("/incidents", status_code=202)
async def start_incident(body: StartIncident) -> dict:
    """Kick off a run. Returns immediately with an id; the caller then opens
    `GET /api/incidents/{id}/events` to watch it."""
    try:
        sc = load_scenario(body.scenario)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    alert = body.alert or f"{sc.alert or 'incident'} — {sc.summary.strip()}"
    run_id = "run_" + secrets.token_hex(4)
    run = IncidentRun(
        id=run_id,
        alert=alert,
        scenario=body.scenario,
        created_at=datetime.now(UTC),
    )
    _RUNS[run_id] = run
    _evict()
    run.task = asyncio.create_task(_run_incident(run, body.k))
    return {"id": run_id, "status": "running"}


@router.get("/incidents")
async def list_incidents(
    status: str | None = None, featured: bool | None = None, limit: int = 20
) -> list[dict]:
    """Recent runs, newest first. In-flight runs (still in memory, not yet
    persisted) are prepended so the UI shows them the moment they start.
    `featured=1` returns only the curated exemplars."""
    rows = await asyncio.to_thread(list_runs, status=status, featured=featured, limit=limit)
    persisted = [
        {
            "id": r.id,
            "scenario": r.scenario,
            "disposition": r.disposition,
            "status": r.status,
            "featured": r.featured,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    if featured:
        return persisted

    persisted_ids = {r.id for r in rows}
    live = [
        {
            "id": r.id,
            "scenario": r.scenario,
            "disposition": None,
            "status": "running",
            "featured": False,
            "created_at": r.created_at.isoformat(),
        }
        for r in sorted(_RUNS.values(), key=lambda r: r.created_at, reverse=True)
        if not r.done and r.id not in persisted_ids and (status in (None, "running"))
    ]
    return live + persisted


@router.get("/incidents/{run_id}")
async def get_incident(run_id: str) -> dict | RunRecord:
    """One run. While it's in flight, returns the buffered events; once it's
    persisted, returns the full audit record from Postgres."""
    run = _RUNS.get(run_id)
    if run is not None and not run.done:
        return {
            "id": run.id,
            "status": "running",
            "scenario": run.scenario,
            "alert": run.alert,
            "created_at": run.created_at.isoformat(),
            "events": run.events,
        }
    rec = await asyncio.to_thread(get_run, run_id)
    if rec is None:
        raise HTTPException(404, f"no run {run_id!r}")
    return rec


def _sse(e: Event) -> str:
    return f"event: {e['type']}\ndata: {json.dumps(e['data'])}\n\n"


@router.get("/incidents/{run_id}/events")
async def incident_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of run progress. Replays what's happened so far, then streams
    live events until the run finishes (a `finished` or `error` event), then
    closes. Safe to (re)connect at any point — the client reconciles the
    authoritative record with a final `GET /api/incidents/{id}`."""
    run = _RUNS.get(run_id)

    if run is None:
        # Not in memory: either never existed, or finished and was evicted.
        rec = await asyncio.to_thread(get_run, run_id)
        if rec is None:
            raise HTTPException(404, f"no run {run_id!r}")

        async def one_shot() -> AsyncIterator[str]:
            yield _sse(ev.event(ev.FINISHED, run_id=run_id, status=rec.status))

        return StreamingResponse(one_shot(), media_type="text/event-stream")

    async def stream() -> AsyncIterator[str]:
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        run.subscribers.add(q)
        # Snapshot the replay buffer *after* subscribing, with no await in
        # between: events already here won't be in `q`, events from here on will.
        backlog = list(run.events)
        try:
            for e in backlog:
                yield _sse(e)
            if run.done:
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if e is None:  # finish sentinel
                    break
                yield _sse(e)
        finally:
            run.subscribers.discard(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _resolve(run_id: str, decision: str, body: Decision) -> RunRecord:
    rec = await asyncio.to_thread(get_run, run_id)
    if rec is None:
        raise HTTPException(404, f"no run {run_id!r}")
    if rec.status != "awaiting-approval":
        raise HTTPException(409, f"run {run_id} is {rec.status} — nothing to {decision}")
    try:
        return await asyncio.to_thread(
            resolve_approvals,
            run_id,
            decision=decision,  # type: ignore[arg-type]
            step=body.step,
            by=body.by,
            note=body.note,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/incidents/{run_id}/approve")
async def approve_incident(run_id: str, body: Decision) -> RunRecord:
    return await _resolve(run_id, "approve", body)


@router.post("/incidents/{run_id}/reject")
async def reject_incident(run_id: str, body: Decision) -> RunRecord:
    if not body.note:
        raise HTTPException(422, "a note is required to reject")
    return await _resolve(run_id, "reject", body)


@router.get("/scenarios")
async def scenarios() -> list[dict]:
    """The sim scenarios a run can be started against — feeds the new-incident
    launcher. The frontend merges editorial copy onto this by name."""
    from .sim import list_scenarios

    out = []
    for name in list_scenarios():
        sc = load_scenario(name)
        out.append(
            {
                "name": name,
                "title": sc.title,
                "summary": sc.summary.strip(),
                "severity": sc.severity or None,
                "alert": sc.alert or None,
                "expected_runbook": sc.expected_runbook,
                "metrics": sc.metric_names(),
            }
        )
    return out


_ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"
_ADR_FIELD = re.compile(r"^-\s+\*\*(Status|Date|Deciders):\*\*\s+(.+)$", re.MULTILINE)


# ADRs not surfaced on the public dashboard.
_ADR_HIDDEN: frozenset[int] = frozenset({9})


@router.get("/decisions")
async def decisions() -> list[dict]:
    """Index of the architecture decision records (docs/adr/*.md) — number,
    title, status, date, and the Context section as a teaser."""
    out = []
    for path in sorted(_ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        num = int(path.name[:4])
        if num in _ADR_HIDDEN:
            continue
        text = path.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        if " — " in title:
            title = title.split(" — ", 1)[1]
        fields = {k.lower(): v.strip() for k, v in _ADR_FIELD.findall(text)}
        context = ""
        if "## Context" in text:
            context = text.split("## Context", 1)[1].split("\n## ", 1)[0].strip()
        out.append(
            {
                "number": num,
                "slug": path.stem,
                "title": title,
                "status": fields.get("status"),
                "date": fields.get("date"),
                "context": context,
            }
        )
    return out


_CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"


@router.get("/runbooks")
async def runbook_markdown(path: str) -> dict:
    """Serve a runbook's markdown so the dashboard can highlight the exact line a
    remediation step quotes. Jailed to the corpus directory."""
    try:
        target = (_CORPUS_DIR.parent / path).resolve()
        target.relative_to(_CORPUS_DIR)  # raises if `path` escaped the corpus
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "path must be inside the corpus") from exc
    if target.suffix != ".md" or not target.is_file():
        raise HTTPException(404, f"no runbook at {path!r}")
    return {"path": path, "markdown": target.read_text()}


@router.get("/evals/baseline")
async def evals_baseline() -> dict:
    """The blessed eval baseline (evals/baseline.json) — feeds the Evals page."""
    path = Path(__file__).resolve().parent / "evals" / "baseline.json"
    if not path.is_file():
        raise HTTPException(404, "no baseline blessed yet")
    return json.loads(path.read_text())
