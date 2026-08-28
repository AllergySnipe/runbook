"""Corpus sources.

Each source yields `RawDoc`s. Local sources read from the repo; remote sources
download a GitHub tarball into `data/raw/` (gitignored) once and reuse it — so a
re-ingest is offline unless `--refresh` is passed.

Postmortems (danluu/post-mortems, external HTML) are a separate source added in a
later commit.
"""

from __future__ import annotations

import tarfile
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RAW_CACHE = _REPO_ROOT / "data" / "raw"
_SYNTHETIC_DIR = _REPO_ROOT / "corpus" / "synthetic"


@dataclass
class RawDoc:
    source: str  # corpus bucket: 'runbook' | 'synthetic-runbook' | 'postmortem'
    origin: str  # repo slug or 'paymentsvc'
    title: str
    url: str | None
    path: str  # provenance path, repo-relative or within the source repo
    text: str


def _title_from(path: str, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(path).stem.replace("-", " ").replace("_", " ")


# --- local: synthetic paymentsvc runbooks ------------------------------------


def synthetic_docs() -> Iterator[RawDoc]:
    for md in sorted(_SYNTHETIC_DIR.rglob("*.md")):
        rel = md.relative_to(_REPO_ROOT).as_posix()
        text = md.read_text()
        yield RawDoc(
            source="synthetic-runbook",
            origin=md.parent.name,
            title=_title_from(rel, text),
            url=None,
            path=rel,
            text=text,
        )


# --- remote: GitHub repos of runbooks --------------------------------------


@dataclass(frozen=True)
class GitHubRepo:
    slug: str  # "owner/repo"
    branch: str
    subdirs: tuple[str, ...]  # only ingest .md under these (empty = whole repo)


_GITHUB_REPOS = {
    "scoutflo-sre": GitHubRepo(
        slug="Scoutflo/Scoutflo-SRE-Playbooks",
        branch="master",
        subdirs=("AWS Playbooks/", "K8s Playbooks/", "Sentry Playbooks/"),
    ),
    "techlearn-runbooks": GitHubRepo(
        slug="techlearn-center/incident-response-runbooks",
        branch="main",
        subdirs=("modules/", "templates/", "examples/"),
    ),
}


def _tarball(repo: GitHubRepo, *, refresh: bool) -> Path:
    _RAW_CACHE.mkdir(parents=True, exist_ok=True)
    dest = _RAW_CACHE / f"{repo.slug.replace('/', '__')}@{repo.branch}.tar.gz"
    if dest.exists() and not refresh:
        return dest
    url = f"https://codeload.github.com/{repo.slug}/tar.gz/refs/heads/{repo.branch}"
    req = urllib.request.Request(url, headers={"User-Agent": "runbook-ingest"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest


def github_docs(key: str, *, refresh: bool = False) -> Iterator[RawDoc]:
    repo = _GITHUB_REPOS[key]
    tar_path = _tarball(repo, refresh=refresh)
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile() or not member.name.endswith(".md"):
                continue
            # strip the "<repo>-<sha>/" prefix github adds
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if repo.subdirs and not any(rel.startswith(d) for d in repo.subdirs):
                continue
            if rel.split("/")[-1].lower() in {"readme.md", "contributing.md", "license.md"}:
                continue
            fh = tf.extractfile(member)
            if fh is None:
                continue
            text = fh.read().decode("utf-8", errors="replace")
            if not text.strip():
                continue
            yield RawDoc(
                source="runbook",
                origin=repo.slug,
                title=_title_from(rel, text),
                url=f"https://github.com/{repo.slug}/blob/{repo.branch}/{rel}",
                path=rel,
                text=text,
            )


# --- registry -------------------------------------------------------------

ALL_SOURCES = ("synthetic", *_GITHUB_REPOS.keys())


def load_source(name: str, *, refresh: bool = False) -> Iterator[RawDoc]:
    if name == "synthetic":
        return synthetic_docs()
    if name in _GITHUB_REPOS:
        return github_docs(name, refresh=refresh)
    raise ValueError(f"unknown source: {name!r} (known: {', '.join(ALL_SOURCES)})")
