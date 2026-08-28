"""Versioned prompt files, loaded by name (CLAUDE.md convention — prompts are not
inline string literals).

    from runbook.prompts import load
    system = load("diagnose")

Files are `<name>.md` in this directory. `{placeholders}` are filled by the caller
with `load(name, **kw)` (str.format — literal braces must be doubled).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache
def _raw(name: str) -> str:
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt named {name!r} in {_DIR}")
    return path.read_text().strip()


def load(name: str, **kw: object) -> str:
    text = _raw(name)
    return text.format(**kw) if kw else text
