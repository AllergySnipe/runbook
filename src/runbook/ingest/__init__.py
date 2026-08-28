"""Corpus ingestion: fetch → chunk → load into `documents`.

`embedding` is left NULL here; embedding is a separate slice. Re-ingesting a
source is idempotent: all rows for a given `(source, origin)` are replaced.

    runbook ingest [--source NAME ...] [--refresh]
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..db import connect
from .chunk import chunk_markdown
from .sources import ALL_SOURCES, RawDoc, load_source


@dataclass
class IngestStats:
    source: str
    documents: int
    chunks: int


def _rows_for(doc: RawDoc) -> list[tuple]:
    frontmatter, chunks = chunk_markdown(doc.text)
    rows: list[tuple] = []
    for ch in chunks:
        metadata = {
            "path": doc.path,
            "heading_path": ch.heading_path,
            "frontmatter": frontmatter,
        }
        rows.append(
            (
                doc.source,
                doc.origin,
                doc.title,
                doc.url,
                ch.index,
                ch.text,
                json.dumps(metadata),
            )
        )
    return rows


_INSERT = """
insert into documents (source, origin, title, url, chunk_index, chunk_text, metadata)
values (%s, %s, %s, %s, %s, %s, %s::jsonb)
"""


def ingest(sources: list[str] | None = None, *, refresh: bool = False) -> list[IngestStats]:
    names = sources or list(ALL_SOURCES)
    stats: list[IngestStats] = []

    with connect(direct=True) as conn:
        conn.autocommit = True
        for name in names:
            docs = list(load_source(name, refresh=refresh))
            pairs = {(d.source, d.origin) for d in docs}
            all_rows: list[tuple] = []
            for doc in docs:
                all_rows.extend(_rows_for(doc))

            with conn.transaction():
                for src, origin in pairs:
                    conn.execute(
                        "delete from documents where source = %s and origin = %s",
                        (src, origin),
                    )
                conn.cursor().executemany(_INSERT, all_rows)

            stats.append(IngestStats(source=name, documents=len(docs), chunks=len(all_rows)))

    return stats
