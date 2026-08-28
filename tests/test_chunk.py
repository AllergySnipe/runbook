"""Deterministic tests for the markdown chunker — no DB, no network."""

from runbook.ingest.chunk import OVERLAP_CHARS, TARGET_CHARS, chunk_markdown, split_frontmatter


def test_split_frontmatter():
    fm, body = split_frontmatter("---\nservice: paymentsvc\nseverity: SEV1\n---\n# Title\ntext")
    assert fm == {"service": "paymentsvc", "severity": "SEV1"}
    assert body.startswith("# Title")


def test_no_frontmatter_is_passthrough():
    fm, body = split_frontmatter("# Title\ntext")
    assert fm == {}
    assert body == "# Title\ntext"


def test_sections_carry_heading_path():
    raw = "# A\nintro\n## B\nunder b\n## C\nunder c\n"
    _, chunks = chunk_markdown(raw)
    paths = [c.heading_path for c in chunks]
    assert ["A"] in paths
    assert ["A", "B"] in paths
    assert ["A", "C"] in paths


def test_hash_comments_in_code_fences_are_not_headings():
    raw = "# Real\nintro\n\n```bash\n# not a heading\ntop -bn1\n```\n\n## Also Real\ntext\n"
    _, chunks = chunk_markdown(raw)
    paths = [c.heading_path for c in chunks]
    assert ["Real"] in paths
    assert ["Real", "Also Real"] in paths
    assert not any("not a heading" in h for p in paths for h in p)
    assert any("# not a heading" in c.text for c in chunks)


def test_chunk_indexes_are_sequential():
    _, chunks = chunk_markdown("# A\nx\n## B\ny\n## C\nz\n")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_oversized_section_is_windowed_with_overlap():
    big = "\n\n".join(["para " * 40] * 20)  # well over TARGET_CHARS
    _, chunks = chunk_markdown(f"# Big\n{big}\n")
    assert len(chunks) > 1
    assert all(len(c.text) <= TARGET_CHARS + OVERLAP_CHARS + 50 for c in chunks)


def test_parse_danluu_readme():
    from runbook.ingest.sources import _parse_readme

    md = (
        "# Config Errors\n"
        "[Allegro](https://allegro.tech/2018/08/postmortem.html) - blah\n"
        "[Amazon](https://aws.amazon.com/message/74876-2/)\n"
        "## Other lists of postmortems\n"
        "[some list](https://example.com/list)\n"
        "# Database\n"
        "[GitHub](https://github.blog/dns-outage-post-mortem/)\n"
        "[dup](https://aws.amazon.com/message/74876-2/)\n"
    )
    entries = _parse_readme(md)
    urls = [u for _, u, _ in entries]
    assert "https://allegro.tech/2018/08/postmortem.html" in urls
    assert "https://github.blog/dns-outage-post-mortem/" in urls
    assert "https://example.com/list" not in urls  # meta section skipped
    assert urls.count("https://aws.amazon.com/message/74876-2/") == 1  # deduped
    assert ("GitHub", "https://github.blog/dns-outage-post-mortem/", "database") in entries


def test_real_synthetic_runbook_chunks():
    from runbook.ingest.sources import synthetic_docs

    docs = list(synthetic_docs())
    assert len(docs) == 6
    for doc in docs:
        fm, chunks = chunk_markdown(doc.text)
        assert fm.get("service") == "paymentsvc"
        assert chunks
        assert any("Diagnosis" in c.heading_path for c in chunks)
