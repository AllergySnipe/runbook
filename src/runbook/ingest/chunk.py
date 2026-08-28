"""Markdown-aware chunking.

A document is split first on its heading structure, then any oversized section is
windowed at paragraph boundaries with a small overlap. Each chunk keeps the path
of headings above it (`heading_path`) so retrieval and prompt assembly can show
where a passage came from.

Deliberately simple — no markdown parser dependency. Good enough for runbooks and
postmortems, which are shallowly nested prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

TARGET_CHARS = 1500
OVERLAP_CHARS = 200


@dataclass
class Chunk:
    index: int
    text: str
    heading_path: list[str] = field(default_factory=list)


def split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). Only flat `key: value` lines are parsed —
    enough for the synthetic runbooks; anything else is ignored."""
    match = _FRONTMATTER.match(raw)
    if not match:
        return {}, raw
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
    return fm, raw[match.end() :]


def _sections(body: str) -> list[tuple[list[str], str]]:
    """Break the body into (heading_path, text) sections at heading lines."""
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    buf: list[str] = []
    path: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append((list(path), text))
        buf.clear()

    in_fence = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if not m:
            buf.append(line)
            continue
        flush()
        level = len(m.group(1))
        title = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = [t for _, t in stack]

    flush()
    return sections


def _window(text: str) -> list[str]:
    """Split an oversized section into overlapping windows at paragraph breaks."""
    if len(text) <= TARGET_CHARS:
        return [text]
    paras = re.split(r"\n\s*\n", text)
    windows: list[str] = []
    cur = ""
    for para in paras:
        if cur and len(cur) + len(para) + 2 > TARGET_CHARS:
            windows.append(cur.strip())
            tail = cur[-OVERLAP_CHARS:]
            cur = tail + "\n\n" + para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        windows.append(cur.strip())
    return windows


def chunk_markdown(raw: str) -> tuple[dict[str, str], list[Chunk]]:
    """Return (frontmatter, chunks) for one markdown document."""
    fm, body = split_frontmatter(raw)
    chunks: list[Chunk] = []
    for heading_path, text in _sections(body):
        for window in _window(text):
            chunks.append(Chunk(index=len(chunks), text=window, heading_path=heading_path))
    return fm, chunks
