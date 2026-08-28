"""The `runbook` CLI. Thin dispatch; each subcommand's work lives in its own module.

runbook migrate [--dry-run]              apply pending SQL migrations
runbook ingest [--source N] [--refresh]  fetch + chunk + load the corpus
runbook embed [--all]                    embed documents.chunk_text into documents.embedding
runbook search <query> [-k N] [--mode]   hybrid retrieval over the corpus
runbook sim <action> [scenario] ...      poke the fixture-backed sim by hand
"""

from __future__ import annotations

import argparse

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
