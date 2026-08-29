"""The guardrail's deterministic action classifier — a safety component, so its
behaviour is pinned by an explicit table, adversarial rows included. The
second-model pass is faked; whether the real Haiku pass is any good is a Week 2
eval.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runbook.core import guardrail as gd

RUNBOOK = (
    "## Remediation\n"
    "- **[read-only] Confirm scope** — is it one pod or all? One pod suggests a leak.\n"
    "- **[state-changing — needs approval] Roll back the implicated deploy** if step 3 found one.\n"
    "- **[state-changing — needs approval] Raise the per-pod pool size** only if Postgres has\n"
    "  headroom; otherwise you move the exhaustion into the database.\n"
    "- **[read-only] File a follow-up** to move the acquirer-gw call outside the transaction.\n"
)


# action, expected classification
STATE_CHANGING = [
    "Roll back the implicated deploy",
    "Restart the affected paymentsvc pod",
    "Scale out paymentsvc (add pods)",
    "Raise the per-pod connection pool size",
    "Disable the new charge-lookup feature flag",
    "Fail over to the Postgres replica",
    "Flush the Redis idempotency cache",
    "Rotate the acquirer-gw API credential",
    "Handle it appropriately",  # unknown verb → fail-safe
    "Do whatever the runbook says",  # unknown → fail-safe
    "Gently restart your assumptions about the root cause",  # adversarial: 'restart' wins
]

READ_ONLY = [
    "Confirm scope — is this one pod or all pods?",
    "Check paymentsvc_db_pool_checked_out against pool size",
    "Page the payments service owner",
    "Escalate to the DBA on-call",
    "File a follow-up ticket to move the acquirer-gw call outside the DB transaction",
    "Review pg_stat_activity for long-running queries",
    "Compare query p99 before and after the deploy",
]


@pytest.mark.parametrize("action", STATE_CHANGING)
def test_state_changing_actions(action):
    v = gd.classify_action(action, runbook_quote="", model_flag=True)
    assert v.classification == "state-changing", v.reason


@pytest.mark.parametrize("action", READ_ONLY)
def test_read_only_actions(action):
    v = gd.classify_action(action, runbook_quote="", model_flag=False)
    assert v.classification == "read-only", v.reason


def test_unknown_action_defaults_to_state_changing():
    v = gd.classify_action("Frobnicate the widget", runbook_quote="", model_flag=False)
    assert v.classification == "state-changing"
    assert "fail-safe" in v.reason


def test_runbook_tag_is_authoritative_when_no_verb_matches():
    # action has no verb the scanner knows; the runbook tag decides
    v = gd.classify_action(
        "Per-pod pool size adjustment",
        runbook_quote="Raise the per-pod pool size",
        model_flag=True,
        runbook_text=RUNBOOK,
    )
    assert v.classification == "state-changing"
    assert "runbook tags" in v.reason


def test_state_changing_verb_overrides_a_read_only_tag():
    # the model rewrote a [read-only] step into something that restarts things
    v = gd.classify_action(
        "Restart the pod to clear the leak",
        runbook_quote="Confirm scope — is it one pod or all?",
        model_flag=False,
        runbook_text=RUNBOOK,
    )
    assert v.classification == "state-changing"
    assert v.model_disagreed


def test_model_underlabel_is_recorded_as_disagreement():
    v = gd.classify_action("Roll back the deploy", runbook_quote="", model_flag=False)
    assert v.classification == "state-changing"
    assert v.model_disagreed is True


def test_model_overlabel_is_also_a_disagreement_but_safe():
    v = gd.classify_action("Check the pool metric", runbook_quote="", model_flag=True)
    assert v.classification == "read-only"
    assert v.model_disagreed is True


def test_raise_ticket_vs_raise_limit():
    assert (
        gd.classify_action("Raise a follow-up ticket", "", model_flag=False).classification
        == "read-only"
    )
    assert (
        gd.classify_action("Raise the pool size limit", "", model_flag=True).classification
        == "state-changing"
    )


def test_runbook_tag_lookup_direct():
    assert gd._runbook_tag("Roll back the implicated deploy", RUNBOOK) == "state-changing"
    assert gd._runbook_tag("Confirm scope", RUNBOOK) == "read-only"
    assert gd._runbook_tag("something not in the runbook", RUNBOOK) is None


def test_classify_steps_sets_indices():
    steps = [
        SimpleNamespace(action="Check the metric", runbook_quote="", state_changing=False),
        SimpleNamespace(action="Roll back the deploy", runbook_quote="", state_changing=True),
    ]
    verdicts = gd.classify_steps(steps, RUNBOOK)
    assert [v.step_index for v in verdicts] == [0, 1]
    assert [v.classification for v in verdicts] == ["read-only", "state-changing"]


def test_apply_second_pass_upgrades_only():
    verdicts = [
        gd.ActionVerdict(
            0, "Check the metric", "read-only", "r", model_flag=False, model_disagreed=False
        ),
        gd.ActionVerdict(
            1, "Roll back", "state-changing", "r", model_flag=True, model_disagreed=False
        ),
    ]
    gd.apply_second_pass(
        verdicts,
        [
            gd.SecondPassConcern(
                step_index=0, kind="should-be-state-changing", detail="restarts things"
            ),
            gd.SecondPassConcern(
                step_index=1, kind="should-be-state-changing", detail="already is"
            ),
            gd.SecondPassConcern(step_index=1, kind="not-supported-by-runbook", detail="fyi"),
        ],
    )
    assert verdicts[0].classification == "state-changing"
    assert verdicts[0].upgraded_by_second_pass
    assert verdicts[0].model_disagreed  # model said read-only
    assert verdicts[1].classification == "state-changing"
    assert not verdicts[1].upgraded_by_second_pass  # was already state-changing


def test_report_properties():
    verdicts = [
        gd.ActionVerdict(0, "a", "read-only", "r", model_flag=False, model_disagreed=False),
        gd.ActionVerdict(1, "b", "state-changing", "r", model_flag=False, model_disagreed=True),
    ]
    report = gd.GuardrailReport(verdicts=verdicts)
    assert report.any_state_changing
    assert [v.step_index for v in report.disagreements] == [1]


def test_second_pass_returns_concerns(monkeypatch):
    import asyncio

    async def fake_parse(messages, *, schema, **kw):
        return schema(
            concerns=[
                gd.SecondPassConcern(step_index=0, kind="not-supported-by-runbook", detail="x")
            ]
        ), SimpleNamespace(input_tokens=1, output_tokens=1)

    monkeypatch.setattr(gd.llm, "parse", fake_parse)
    steps = [SimpleNamespace(action="Do a thing", runbook_quote="q", state_changing=False)]
    concerns, usage = asyncio.run(gd.second_pass(steps, RUNBOOK, model="fake"))
    assert concerns[0].kind == "not-supported-by-runbook"
    assert usage.input_tokens == 1


def test_second_pass_skips_the_call_when_no_steps():
    import asyncio

    concerns, usage = asyncio.run(gd.second_pass([], RUNBOOK, model="fake"))
    assert concerns == []
    assert usage is None
