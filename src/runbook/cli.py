"""The `runbook` CLI. Thin dispatch; each subcommand's work lives in its own module.

    runbook migrate [--dry-run]    apply pending SQL migrations
"""

from __future__ import annotations

import argparse

from . import migrate as _migrate


def _cmd_migrate(args: argparse.Namespace) -> int:
    applied = _migrate.run(dry_run=args.dry_run)
    if not applied:
        print("migrate: nothing pending")
        return 0
    verb = "would apply" if args.dry_run else "applied"
    for version in applied:
        print(f"migrate: {verb} {version}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runbook")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="apply pending SQL migrations")
    migrate.add_argument(
        "--dry-run", action="store_true", help="list what would run; apply nothing"
    )
    migrate.set_defaults(func=_cmd_migrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
