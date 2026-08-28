"""Forward-only SQL migration applier.

Plain `.sql` files in `migrations/`, named `NNNN_slug.sql`, applied in filename
order. Each file runs in its own transaction and is recorded in
`schema_migrations`; an already-recorded file is skipped. No down-migrations —
roll forward with a new file.

Caveat: a statement that cannot run inside a transaction (e.g.
`CREATE INDEX CONCURRENTLY`) does not belong in a migration file here. Use a
plain `CREATE INDEX`, or handle it out of band.

Run with `runbook migrate` (see `cli.py`).
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from .db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_ENSURE_TABLE = """
create table if not exists schema_migrations (
    version    text primary key,
    applied_at timestamptz not null default now()
)
"""


def discover() -> list[Path]:
    """Migration files in apply order."""
    return sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))


def _applied(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("select version from schema_migrations")}


def run(*, dry_run: bool = False) -> list[str]:
    """Apply every pending migration. Returns the versions applied (or, for
    `dry_run`, the versions that would be applied), in order."""
    pending: list[str] = []
    with connect(direct=True) as conn:
        conn.autocommit = True
        with conn.transaction():
            conn.execute(_ENSURE_TABLE)
        done = _applied(conn)

        for path in discover():
            version = path.name
            if version in done:
                continue
            if dry_run:
                pending.append(version)
                continue
            sql = path.read_text()
            with conn.transaction():
                conn.execute(sql)
                conn.execute("insert into schema_migrations (version) values (%s)", (version,))
            pending.append(version)

    return pending
