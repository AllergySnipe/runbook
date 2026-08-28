"""The `runbook` CLI. Thin dispatch; each subcommand's work lives in its own module.

runbook migrate [--dry-run]              apply pending SQL migrations
runbook ingest [--source N] [--refresh]  fetch + chunk + load the corpus
runbook embed [--all]                    embed documents.chunk_text into documents.embedding
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
