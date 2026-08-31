"""`online_scores` round-trip against real Postgres (Neon) — migration 0013,
ADR-0018. Needs `database_url`; skipped otherwise (CI, offline unit runs).
Cleans up every row it creates (scores cascade off the run).
"""

from __future__ import annotations

import pytest


def _has_db() -> bool:
    try:
        from runbook.config import get_settings

        return bool(get_settings().database_url)
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="needs a configured database_url")

from runbook.core import get_scores, list_recent_scores, record_online_scores, record_run
from runbook.core.loop import DiagnoseResult
from runbook.core.scoring import Score, score_run
from runbook.core.triage import TriageResult
from runbook.db import connect


def _bare_result() -> DiagnoseResult:
    """A short-circuited run — no diagnosis, no guardrail — enough to persist."""
    return DiagnoseResult(
        alert="scoring-integration-test alert",
        scenario="db-connection-pool-exhaustion",
        triage=TriageResult(category="noise-or-flapping", rationale="r", confidence="high"),
        diagnosis=None,
        guardrail=None,
        disposition=None,
        retrieved=[],
        tool_calls=[],
        iterations=0,
        hit_max_iters=False,
        grounding_issues=[],
        usage={"input_tokens": 0, "output_tokens": 0, "by_model": {}},
        elapsed_s=0.1,
    )


@pytest.fixture
def run_id():
    rec = record_run(_bare_result())
    yield rec.id
    with connect() as conn, conn.transaction():
        conn.execute("delete from incident_runs where id = %s", (rec.id,))


def test_record_get_roundtrip(run_id):
    scores = [
        Score("safety-invariants", "BOOLEAN", 1.0, comment=None),
        Score("grounding-coverage", "NUMERIC", 0.5, comment="1/2 steps cite a runbook line"),
        Score("disposition", "CATEGORICAL", "short-circuit", comment=None),
    ]
    record_online_scores(run_id, scores)

    got = {s.name: s for s in get_scores(run_id)}
    assert got["safety-invariants"].value_num == 1.0
    assert got["safety-invariants"].data_type == "BOOLEAN"
    assert got["grounding-coverage"].value == 0.5
    assert got["grounding-coverage"].comment == "1/2 steps cite a runbook line"
    assert got["disposition"].value_text == "short-circuit"
    assert got["disposition"].value == "short-circuit"


def test_rescore_upserts(run_id):
    record_online_scores(run_id, [Score("grounding-coverage", "NUMERIC", 0.5)])
    record_online_scores(run_id, [Score("grounding-coverage", "NUMERIC", 1.0)])

    rows = get_scores(run_id)
    assert len(rows) == 1
    assert rows[0].value == 1.0


def test_score_run_output_persists(run_id):
    record_online_scores(run_id, score_run(_bare_result()))
    names = {s.name for s in get_scores(run_id)}
    assert "safety-invariants" in names
    assert "disposition" in names


def test_list_recent_scores_includes_this_run(run_id):
    record_online_scores(run_id, [Score("safety-invariants", "BOOLEAN", 1.0)])
    recent = list_recent_scores(limit=50)
    assert run_id in recent
    assert recent[run_id][0].name == "safety-invariants"
