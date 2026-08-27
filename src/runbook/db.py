"""Postgres connection helpers.

Two DSNs (see `config.py`): the **pooled** URL for the app at runtime, the
**direct** URL for migrations and anything that needs session-level features the
PgBouncer pooler drops (advisory locks, `SET`, some DDL).

Sync-only for now — the migration applier is the only caller. The async pool for
request handlers arrives with the retrieval slice.
"""

from __future__ import annotations

import psycopg

from .config import get_settings


def connect(*, direct: bool = False) -> psycopg.Connection:
    """Open a new connection. `direct=True` uses the unpooled DSN."""
    settings = get_settings()
    dsn = settings.database_url_unpooled if direct else settings.database_url
    return psycopg.connect(dsn)
