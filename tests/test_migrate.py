"""Deterministic checks on migration discovery — no DB, no secrets."""

import re

from runbook import migrate


def test_migrations_discovered_and_ordered():
    files = migrate.discover()
    assert files, "no migration files found"
    names = [p.name for p in files]
    assert names == sorted(names), "discover() must return files in filename order"


def test_migration_filenames_follow_convention():
    for path in migrate.discover():
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", path.name), path.name
