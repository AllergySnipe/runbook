"""The `runbook` CLI. Thin dispatch; each subcommand's work lives in its own module.

runbook migrate [--dry-run]              apply pending SQL migrations
runbook ingest [--source N] [--refresh]  fetch + chunk + load the corpus
runbook embed [--all]                    embed documents.chunk_text into documents.embedding
runbook search <query> [-k N] [--mode]   hybrid retrieval over the corpus
runbook triage "<alert>"                 classify an alert into a handling lane
runbook diagnose <scenario> [--alert]    run the incident loop against a sim scenario
runbook runs [--status S] [-n N]         list recent incident runs
runbook run <id>                         show one incident run (the audit record)
runbook approve <id> [--step N] [--by]   approve a run's pending state-changing steps
runbook reject <id> --note "why" [--by]  reject a run (whole run → rejected)
runbook feature <id> [--unfeature]       mark a run as a curated dashboard exemplar
runbook outcome <id> --root-cause "…"    record the confirmed root cause as incident memory
runbook promote <id>                     render a golden EvalCase stub from a real run
runbook sim <action> [scenario] ...      poke the fixture-backed sim by hand
runbook eval [--scenario N] [--no-judge]  run the golden eval set through the real loop
runbook redteam [--condition C] [-j N]    run the log-injection red-team harness
"""

from __future__ import annotations

import argparse
import os

from . import embed as _embed
from . import migrate as _migrate
from .ingest import ingest as _ingest
from .ingest.sources import ALL_SOURCES, DEFAULT_SOURCES


def _cmd_migrate(args: argparse.Namespace) -> int:
    applied = _migrate.run(dry_run=args.dry_run)
    if not applied:
        print("migrate: nothing pending")
        return 0
    verb = "would apply" if args.dry_run else "applied"
    for version in applied:
        print(f"migrate: {verb} {version}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    stats = _ingest(args.source or None, refresh=args.refresh)
    for s in stats:
        print(f"ingest: {s.source:20s} {s.documents:4d} docs  {s.chunks:5d} chunks")
    print(f"ingest: total {sum(s.chunks for s in stats)} chunks")
    return 0


def _cmd_embed(args: argparse.Namespace) -> int:
    written = _embed.backfill(only_missing=not args.all)
    scope = "all" if args.all else "missing"
    print(f"embed: wrote {written} embeddings ({scope})")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    from .rag import retrieve

    hits = retrieve(
        args.query,
        k=args.k,
        mode=args.mode,
        rerank=False if args.no_rerank else None,
    )
    if not hits:
        print("search: no matches")
        return 0
    for i, h in enumerate(hits, 1):
        scores = "  ".join(f"{name}={val:.4g}" for name, val in h.scores.items())
        snippet = " ".join(h.chunk_text.split())[:200]
        print(f"\n{i}. {h.title}  [{h.source}/{h.origin}]")
        print(f"   {h.heading_display}")
        print(f"   {scores}")
        print(f"   {snippet}…")
    return 0


def _cmd_diagnose(args: argparse.Namespace) -> int:
    """alert → retrieve runbook → tool-use investigation → grounded diagnosis."""
    import asyncio

    from .core import diagnose
    from .core.cost import estimate_cost
    from .sim import load_scenario

    sc = load_scenario(args.scenario)
    alert = args.alert or f"{sc.alert or 'incident'} — {sc.summary.strip()}"

    result = asyncio.run(diagnose(alert, args.scenario, k=args.k, use_cache=True, use_memory=True))

    print(f"\nalert:    {alert}")
    print(f"scenario: {result.scenario}")
    t = result.triage
    print(f"triage:   {t.category}  ({t.confidence})  — {t.rationale}")
    if result.cache_hit:
        print("cache:    hit — reused triage + retrieval from a recent near-duplicate alert")
    if result.memories:
        print(f"memory:   {len(result.memories)} similar past incident(s) shown as context")
        for m in result.memories:
            print(f"          [{m.similarity:.0%}] {m.scenario}: {m.actual_root_cause[:80]}")

    if result.short_circuited:
        print("\n→ triage short-circuited this alert — the diagnosis loop did not run")
        _persist_run(result)
        return 0

    d = result.diagnosis
    print(
        f"\nretrieved (k={len(result.retrieved)}): "
        + ", ".join(dict.fromkeys((c.path or c.source) for c in result.retrieved))
    )
    print("\ntool calls:")
    for tc in result.tool_calls:
        flag = " [error]" if tc.is_error else ""
        args_str = ", ".join(f"{k}={v}" for k, v in tc.input.items())
        print(f"  {tc.name}({args_str}){flag}")
    if not result.tool_calls:
        print("  (none)")

    print(f"\n── diagnosis ──  confidence={d.confidence}  failure_mode={d.failure_mode}")
    print(f"root cause: {d.root_cause}")
    print(f"summary:    {d.summary}")
    print("\nevidence:")
    for e in d.evidence:
        print(f"  - {e}")
    g = result.guardrail
    verdicts = {v.step_index: v for v in g.verdicts} if g else {}
    print("\nremediation:")
    for i, step in enumerate(d.remediation_steps):
        v = verdicts.get(i)
        cls = v.classification if v else ("state-changing" if step.state_changing else "read-only")
        tag = "STATE-CHANGING (needs approval)" if cls == "state-changing" else "read-only"
        print(f"  {i + 1}. [{tag}] {step.action}")
        print(f'       ⤷ runbook: "{step.runbook_quote}"')
        if v and v.model_disagreed:
            print(
                f"       ⚠ model self-labelled {'state-changing' if step.state_changing else 'read-only'}"
                f"; guardrail: {v.classification} — {v.reason}"
            )
    if not d.remediation_steps:
        print("  (none)")

    if g and g.regenerated_for_grounding:
        note = (
            f", then dropped {g.dropped_ungrounded} ungrounded step(s)"
            if g.dropped_ungrounded
            else ""
        )
        print(f"\n⚠ S3: remediation regenerated once for grounding{note}")
    for c in g.second_pass_concerns if g else []:
        print(f"⚠ second pass — step {c.step_index + 1}: {c.kind} — {c.detail}")

    banner = {
        "auto": "→ disposition: AUTO — steps are read-only and grounded",
        "needs-approval": "→ disposition: NEEDS APPROVAL — a human must approve the state-changing step(s) before this run resolves",
        "escalate": "→ disposition: ESCALATE — no grounded remediation; hand to a human with the evidence above",
    }
    print("\n" + banner.get(result.disposition or "", f"→ disposition: {result.disposition}"))

    if result.hit_max_iters:
        print("\n⚠ hit the tool-call iteration cap — diagnosis is on partial evidence")
    print(
        f"\n{result.iterations} turns · {result.usage['input_tokens']}in/"
        f"{result.usage['output_tokens']}out tokens · {result.elapsed_s}s"
        f" · ~${estimate_cost(result.usage.get('by_model')):.4f} (est. at paid model prices)"
    )
    _persist_run(result)
    return 0


def _persist_run(result) -> None:
    """Write the run to Postgres (the audit record + any pending approvals).
    A DB failure is surfaced but not fatal — the diagnosis already printed."""
    from .core import record_run

    try:
        run = record_run(result)
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort at the CLI
        print(f"\n(run not persisted: {exc})")
        return
    print(f"\nrun {run.id}  ·  status: {run.status}")
    if run.status == "awaiting-approval":
        n = len(run.approvals)
        print(f"  {n} state-changing step(s) need a human decision:")
        print(f"    runbook approve {run.id} --by <you>")
        print(f"    runbook reject  {run.id} --by <you> --note '<why>'")


def _cmd_triage(args: argparse.Namespace) -> int:
    """Classify one alert into a handling lane (no loop, one cheap model call)."""
    import asyncio

    from .core import triage

    result = asyncio.run(triage(args.alert))
    print(f"category:   {result.category}")
    print(f"confidence: {result.confidence}")
    print(f"rationale:  {result.rationale}")
    print(
        f"\n→ {'proceed to the diagnosis loop' if result.proceed else 'short-circuit — loop does not run'}"
        + ("  (low prior — novel incident)" if result.low_prior else "")
    )
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    from .core import list_runs

    runs = list_runs(status=args.status, limit=args.n)
    if not runs:
        print("no runs")
        return 0
    for r in runs:
        disp = r.disposition or "—"
        print(f"{r.id}  {r.created_at:%Y-%m-%d %H:%M}  {r.scenario:34.34s}  {disp:14s}  {r.status}")
    return 0


def _cmd_run_show(args: argparse.Namespace) -> int:
    from .core import get_run

    r = get_run(args.id)
    if r is None:
        print(f"no run {args.id!r}")
        return 1

    print(f"run {r.id}   {r.created_at:%Y-%m-%d %H:%M:%S}   status: {r.status}")
    print(f"  scenario:   {r.scenario}")
    print(f"  alert:      {r.alert}")
    print(f"  triage:     {r.triage_category} ({r.triage_confidence}) — {r.triage_rationale}")
    print(f"  disposition:{r.disposition or ' — (short-circuited)'}")
    if r.retrieved:
        print("  retrieved:  " + ", ".join(c.get("path") or c.get("title") for c in r.retrieved))
    if r.memories:
        print(
            "  memory:     "
            + ", ".join(f"{m['scenario']} ({m['similarity']:.0%})" for m in r.memories)
        )
    if r.tool_calls:
        print(
            "  tool calls: "
            + ", ".join(tc["name"] + ("[err]" if tc.get("is_error") else "") for tc in r.tool_calls)
        )
    d = r.diagnosis
    if d:
        print(f"\n  root cause: {d.get('root_cause', '')}")
        print(f"  confidence: {d.get('confidence')}   failure_mode: {d.get('failure_mode')}")
        print("  remediation:")
        for i, step in enumerate(d.get("remediation_steps", [])):
            print(f"    {i + 1}. {step['action']}")
    if r.approvals:
        print("\n  approvals:")
        for a in r.approvals:
            who = f" — {a.resolved_by}" if a.resolved_by else ""
            note = f'  note: "{a.note}"' if a.note else ""
            print(f"    step {a.step_index + 1}: {a.state}{who}{note}")
            print(f"       {a.action}")
    from .core import get_outcome

    oc = get_outcome(r.id)
    if oc is not None:
        verdict = (
            "model was right"
            if oc.model_was_correct
            else ("model was wrong" if oc.model_was_correct is False else "not judged")
        )
        print(f"\n  confirmed outcome ({oc.created_by}, {verdict}):")
        print(f"    {oc.actual_root_cause}")
        if oc.actual_failure_mode:
            print(f"    failure_mode: {oc.actual_failure_mode}")

    if r.usage.get("by_model"):
        print("  cost by model (est. at paid prices):")
        for name, u in r.usage["by_model"].items():
            print(f"    {name:44.44s}  {u['input_tokens']}in/{u['output_tokens']}out")
    print(
        f"\n  {r.iterations} turns · {r.usage.get('input_tokens', 0)}in/"
        f"{r.usage.get('output_tokens', 0)}out · {r.elapsed_s}s"
        f" · ~${r.cost_usd:.4f}"
        + ("  · cache hit" if r.cache_hit else "")
        + (f"  ·  resolved {r.resolved_at:%Y-%m-%d %H:%M}" if r.resolved_at else "")
    )
    return 0


def _resolve_run(args: argparse.Namespace, decision: str) -> int:
    from .core import get_run, resolve_approvals

    r = get_run(args.id)
    if r is None:
        print(f"no run {args.id!r}")
        return 1
    if r.status != "awaiting-approval":
        print(f"run {args.id} is {r.status} — nothing to {decision}")
        return 0

    by = args.by or os.environ.get("USER") or "cli"
    step = (args.step - 1) if args.step else None
    r = resolve_approvals(args.id, decision=decision, step=step, by=by, note=args.note)

    print(f"run {r.id}  ·  status: {r.status}")
    for a in r.approvals:
        who = f" ({a.resolved_by})" if a.resolved_by else ""
        print(f"  step {a.step_index + 1}: {a.state}{who}")
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    return _resolve_run(args, "approve")


def _cmd_reject(args: argparse.Namespace) -> int:
    if not args.note:
        print("reject: --note is required (say why)")
        return 2
    return _resolve_run(args, "reject")


def _cmd_feature(args: argparse.Namespace) -> int:
    """Mark (or unmark) a run as a curated exemplar shown first on the dashboard."""
    from .core import set_featured

    on = not args.unfeature
    if not set_featured(args.id, on):
        print(f"no run {args.id!r}")
        return 1
    print(f"run {args.id}  ·  featured: {on}")
    return 0


def _cmd_outcome(args: argparse.Namespace) -> int:
    """Record what actually turned out to be the root cause of a terminal run
    (SPEC step 7). The confirmed outcome is embedded into `incident_memory` and
    retrieved as context on future similar alerts (ADR-0015). Real embed +
    `DATABASE_URL`."""
    from .core import get_run, record_outcome

    r = get_run(args.id)
    if r is None:
        print(f"no run {args.id!r}")
        return 1

    model_correct = True if args.model_correct else (False if args.model_wrong else None)
    by = args.by or os.environ.get("USER") or "cli"
    try:
        res = record_outcome(
            args.id,
            actual_root_cause=args.root_cause,
            actual_failure_mode=args.failure_mode,
            model_was_correct=model_correct,
            by=by,
        )
    except (LookupError, ValueError) as exc:
        print(f"outcome: {exc}")
        return 1
    print(f"run {args.id}  ·  {res.summary_line()}")
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    """Render a golden `EvalCase` stub from a real incident run (ADR-0016). Prints
    to stdout for the human to review + paste into `evals/cases.py` — labels are
    hand-set ground truth, never auto-generated."""
    from .core import get_outcome, get_run
    from .evals import render_case_stub

    r = get_run(args.id)
    if r is None:
        print(f"no run {args.id!r}")
        return 1
    if r.diagnosis is None:
        print(f"run {args.id} has no diagnosis (triage short-circuited it) — nothing to promote")
        return 1

    outcome = get_outcome(args.id)
    if outcome is None and not args.force:
        print(
            f"promote: run {args.id} has no recorded outcome. The eval's "
            f"reference_root_cause must be human-confirmed, not the model's guess — "
            f'run `runbook outcome {args.id} --root-cause "…"` first, or pass --force '
            f"to promote with the model's guess (marked TODO)."
        )
        return 1

    print(render_case_stub(r, outcome))
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    """Run the golden eval set (`evals/cases.py`) through the real `diagnose()`
    path, score + judge each case, print a scorecard, compare to the baseline.

    Exit 1 on any hard-check failure, errored case, below-target metric, or
    regression vs `evals/baseline.json`. Real model + retrieval calls — needs
    `ANTHROPIC_API_KEY` + `DATABASE_URL`."""
    import asyncio
    import json as _json
    from pathlib import Path

    from .evals import CASES, bless_from_json, load_baseline, run_evals, write_baseline

    if args.bless:
        try:
            metrics = bless_from_json(args.bless)
        except (ValueError, OSError) as exc:
            print(f"eval: cannot bless — {exc}")
            return 1
        print(f"eval: baseline blessed from {args.bless} — commit evals/baseline.json\n  {metrics}")
        return 0

    cases = list(CASES)
    if args.scenario:
        cases = [c for c in cases if c.scenario in set(args.scenario)]
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("eval: no cases match the filter")
        return 2

    judge_state = "off" if args.no_judge else "on"
    print(f"eval: {len(cases)} case(s) · judge {judge_state} · concurrency {args.jobs}")
    report = asyncio.run(
        run_evals(cases, use_judge=not args.no_judge, concurrency=args.jobs, progress=print)
    )

    baseline = load_baseline()
    print("\n" + report.format(baseline))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(report.as_dict(), indent=2) + "\n")
        print(f"\neval: wrote {args.json}")

    if args.update_baseline:
        if report.hard_findings or report.n_errored:
            print("\neval: refusing to bless a baseline with hard failures / errored cases")
            return 1
        write_baseline(report)
        print("\neval: baseline blessed — commit evals/baseline.json")
        return 0

    return 0 if report.passed(baseline) else 1


def _cmd_redteam(args: argparse.Namespace) -> int:
    """Drive the real `diagnose()` against crafted poisoned inputs (poisoned log
    lines, a poisoned retrieved doc, a poisoned alert) and report an
    attack-success-rate. `--condition both` (default) runs baseline (prompt
    defences off) and hardened (as shipped) and prints the before/after table.

    Real model + retrieval calls — needs `OPENROUTER_API_KEY` + `DATABASE_URL`.
    Not wired into CI (ADR-0012). Never persists a run."""
    import asyncio
    import json as _json
    from pathlib import Path

    from .redteam import ATTACKS, format_comparison, run_attacks

    cases = list(ATTACKS)
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    if args.surface:
        cases = [c for c in cases if c.surface in set(args.surface)]
    if args.goal:
        cases = [c for c in cases if c.goal in set(args.goal)]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("redteam: no cases match the filter")
        return 2

    conditions = ["baseline", "hardened"] if args.condition == "both" else [args.condition]
    print(f"redteam: {len(cases)} case(s) · conditions {conditions} · concurrency {args.jobs}")

    reports = {}
    for cond in conditions:
        print(f"\n── {cond} ──")
        reports[cond] = asyncio.run(
            run_attacks(cases, condition=cond, concurrency=args.jobs, progress=print)
        )
        print("\n" + reports[cond].format())

    if len(reports) == 2:
        print("\n" + format_comparison(reports["baseline"], reports["hardened"]))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps({c: r.as_dict() for c, r in reports.items()}, indent=2) + "\n")
        print(f"\nredteam: wrote {args.json}")

    errored = any(r.n_errored for r in reports.values())
    any_success = any(r.succeeded for r in reports.values() if r.condition == "hardened")
    return 1 if (errored or any_success) else 0


def _cmd_sim(args: argparse.Namespace) -> int:
    """Manual inspection of the sim — the same surface the read-only tools use.
    Not part of the product loop; a debugging aid for the tool-loop slice."""
    from . import tools
    from .sim import list_scenarios, load_scenario

    if args.action == "list":
        for name in list_scenarios():
            print(name)
        return 0

    if not args.scenario:
        print("sim: this action needs a <scenario> (see `runbook sim list`)")
        return 2
    sc = load_scenario(args.scenario)
    win = {"start": args.start, "end": args.end}

    if args.action == "show":
        lo, hi = sc.incident_window
        print(f"{sc.name}  [{sc.severity or 'no severity'}]  alert={sc.alert or '—'}")
        print(f"  anchor {sc.anchor.isoformat()}   window {lo.isoformat()} .. {hi.isoformat()}")
        print(f"  expected runbook: {sc.expected_runbook or '—'}")
        print(f"  {sc.summary.strip()}")
        print(f"  metrics: {', '.join(sc.metric_names())}")
        return 0

    if args.action == "metrics":
        if not args.name:
            print("sim metrics: needs a <metric> name")
            return 2
        res = tools.query_metrics(sc, args.name, **win)
        if not res.ok:
            print(f"  {res.error}\n  available: {', '.join(res.available)}")
            return 1
        for s in res.series:
            m = s.summary
            print(f"\n{s.selector}  ({s.unit}, {m.count} pts)")
            print(
                f"  p50={m.p50:g}  p95={m.p95:g}  p99={m.p99:g}  "
                f"min={m.min:g}  max={m.max:g}  first={m.first:g}  last={m.last:g}  "
                f"trend={m.trend}"
            )
        return 0

    if args.action == "logs":
        res = tools.search_logs(sc, args.grep or "", level=args.level, limit=args.limit, **win)
        for match in res.matches:
            print(match.line)
        print(
            f"\n  {len(res.matches)} shown / {res.total_scanned} scanned"
            + (f"  (truncated at {args.limit})" if res.truncated else "")
        )
        if res.hint:
            print(f"  {res.hint}")
        return 0

    if args.action == "deploys":
        res = tools.get_recent_deploys(sc, service=args.service, **win)
        for d in res.deploys:
            mig = f"  migration={','.join(d.migrations)}" if d.migration else ""
            print(f"{d.at.isoformat()}  {d.service:16s} {d.version:22s} {d.change}{mig}")
        print(
            f"\n  {len(res.deploys)} deploy(s) in {res.window[0].isoformat()} .. {res.window[1].isoformat()}"
        )
        return 0

    if args.action == "deps":
        g = tools.get_service_dependencies(sc, service=args.service)
        print(f"{g.service}")
        for label, deps in (("upstream", g.upstreams), ("downstream", g.downstreams)):
            for d in deps:
                extra = f"  {d.note}" if d.note else ""
                print(f"  {label:10s} {d.name:20s} {d.kind:12s} {d.health}{extra}")
        if g.neighbours:
            print(f"  neighbours: {', '.join(g.neighbours)}")
        return 0

    print(f"sim: unknown action {args.action!r}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runbook")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="apply pending SQL migrations")
    migrate.add_argument(
        "--dry-run", action="store_true", help="list what would run; apply nothing"
    )
    migrate.set_defaults(func=_cmd_migrate)

    ingest = sub.add_parser("ingest", help="fetch, chunk, and load the corpus")
    ingest.add_argument(
        "--source",
        action="append",
        choices=ALL_SOURCES,
        help=(
            f"limit to a source (repeatable). default run: {', '.join(DEFAULT_SOURCES)}. "
            f"also available: {', '.join(s for s in ALL_SOURCES if s not in DEFAULT_SOURCES)}"
        ),
    )
    ingest.add_argument(
        "--refresh", action="store_true", help="re-download remote sources, ignoring the cache"
    )
    ingest.set_defaults(func=_cmd_ingest)

    embed = sub.add_parser("embed", help="embed chunk_text into documents.embedding")
    embed.add_argument(
        "--all", action="store_true", help="re-embed every row (default: only rows missing one)"
    )
    embed.set_defaults(func=_cmd_embed)

    search = sub.add_parser("search", help="hybrid retrieval over the corpus")
    search.add_argument("query", help="the search query / alert text")
    search.add_argument("-k", type=int, default=5, help="results to return (default 5)")
    search.add_argument(
        "--mode",
        choices=("hybrid", "vector", "text"),
        default="hybrid",
        help="hybrid (default) fuses vector + full-text; vector/text run one leg",
    )
    search.add_argument(
        "--no-rerank", action="store_true", help="skip the cross-encoder rerank pass"
    )
    search.set_defaults(func=_cmd_search)

    triage = sub.add_parser("triage", help="classify an alert into a handling lane")
    triage.add_argument("alert", help="alert text or an Alertmanager JSON payload")
    triage.set_defaults(func=_cmd_triage)

    diagnose = sub.add_parser("diagnose", help="run the incident loop against a sim scenario")
    diagnose.add_argument("scenario", help="sim scenario name (see `runbook sim list`)")
    diagnose.add_argument(
        "--alert", help="alert text (default: the scenario's own alert + summary)"
    )
    diagnose.add_argument("-k", type=int, default=4, help="runbook chunks to retrieve (default 4)")
    diagnose.set_defaults(func=_cmd_diagnose)

    _STATUSES = ("short-circuited", "awaiting-approval", "resolved", "rejected", "escalated")

    runs = sub.add_parser("runs", help="list recent incident runs")
    runs.add_argument("--status", choices=_STATUSES, help="filter to one lifecycle state")
    runs.add_argument("-n", type=int, default=20, help="how many (default 20)")
    runs.set_defaults(func=_cmd_runs)

    run_show = sub.add_parser("run", help="show one incident run (the audit record)")
    run_show.add_argument("id", help="run id (e.g. run_a1b2c3d4)")
    run_show.set_defaults(func=_cmd_run_show)

    approve = sub.add_parser("approve", help="approve a run's pending state-changing steps")
    approve.add_argument("id", help="run id")
    approve.add_argument("--step", type=int, help="approve only this step (1-based); default all")
    approve.add_argument("--by", help="who is approving (default: $USER)")
    approve.add_argument("--note", help="optional note recorded with the approval")
    approve.set_defaults(func=_cmd_approve)

    reject = sub.add_parser("reject", help="reject a run (whole run → rejected)")
    reject.add_argument("id", help="run id")
    reject.add_argument("--step", type=int, help="reject only this step (1-based); default all")
    reject.add_argument("--by", help="who is rejecting (default: $USER)")
    reject.add_argument("--note", required=True, help="why — required")
    reject.set_defaults(func=_cmd_reject)

    feature = sub.add_parser("feature", help="mark a run as a curated dashboard exemplar")
    feature.add_argument("id", help="run id")
    feature.add_argument("--unfeature", action="store_true", help="clear the flag instead")
    feature.set_defaults(func=_cmd_feature)

    outcome = sub.add_parser(
        "outcome", help="record the confirmed root cause of a terminal run as incident memory"
    )
    outcome.add_argument("id", help="run id")
    outcome.add_argument(
        "--root-cause", required=True, help="what actually turned out to be the root cause"
    )
    outcome.add_argument("--failure-mode", help="the runbook failure_mode it matched, if any")
    verdict = outcome.add_mutually_exclusive_group()
    verdict.add_argument(
        "--model-correct", action="store_true", help="the run's proposed root cause was right"
    )
    verdict.add_argument(
        "--model-wrong", action="store_true", help="the run's proposed root cause was wrong"
    )
    outcome.add_argument("--by", help="who is recording this (default: $USER)")
    outcome.set_defaults(func=_cmd_outcome)

    promote = sub.add_parser(
        "promote", help="render a golden EvalCase stub from a real incident run"
    )
    promote.add_argument("id", help="run id")
    promote.add_argument(
        "--force", action="store_true", help="promote even without a recorded outcome"
    )
    promote.set_defaults(func=_cmd_promote)

    ev = sub.add_parser("eval", help="run the golden eval set through the real loop")
    ev.add_argument("--scenario", action="append", help="limit to a sim scenario (repeatable)")
    ev.add_argument("--case", action="append", help="limit to a case id (repeatable)")
    ev.add_argument("--limit", type=int, help="run only the first N matching cases")
    ev.add_argument("--no-judge", action="store_true", help="skip the LLM-judge pass")
    ev.add_argument("-j", "--jobs", type=int, default=4, help="concurrent cases (default 4)")
    ev.add_argument("--json", help="also write the full per-case results to this path")
    ev.add_argument(
        "--update-baseline",
        action="store_true",
        help="on a clean run, rewrite evals/baseline.json (the 'written justification')",
    )
    ev.add_argument(
        "--bless",
        metavar="RESULTS.json",
        help="bless evals/baseline.json from a prior --json result file, without re-running",
    )
    ev.set_defaults(func=_cmd_eval)

    rt = sub.add_parser("redteam", help="run the log-injection red-team harness")
    rt.add_argument("--case", action="append", help="limit to an attack case id (repeatable)")
    rt.add_argument(
        "--surface", action="append", choices=("log", "doc", "alert"), help="limit to a surface"
    )
    rt.add_argument("--goal", action="append", help="limit to an attack goal (repeatable)")
    rt.add_argument(
        "--condition",
        choices=("baseline", "hardened", "both"),
        default="both",
        help="baseline = prompt defences off; hardened = as shipped (default: both)",
    )
    rt.add_argument("--limit", type=int, help="run only the first N matching cases")
    rt.add_argument("-j", "--jobs", type=int, default=2, help="concurrent cases (default 2)")
    rt.add_argument("--json", help="also write the full per-case results to this path")
    rt.set_defaults(func=_cmd_redteam)

    sim = sub.add_parser("sim", help="inspect the fixture-backed sim by hand")
    sim.add_argument("action", choices=("list", "show", "metrics", "logs", "deploys", "deps"))
    sim.add_argument("scenario", nargs="?", help="scenario name (see `runbook sim list`)")
    sim.add_argument("name", nargs="?", help="for `metrics`: the metric name")
    sim.add_argument("--start", help="window start (ISO or a T±… offset)")
    sim.add_argument("--end", help="window end (ISO or a T±… offset)")
    sim.add_argument("--grep", help="for `logs`: substring to match")
    sim.add_argument("--level", help="for `logs`: filter to a severity")
    sim.add_argument("--limit", type=int, default=40, help="for `logs`: max lines (default 40)")
    sim.add_argument("--service", help="for `deploys`/`deps`: filter to a service")
    sim.set_defaults(func=_cmd_sim)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
