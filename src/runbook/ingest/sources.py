"""Corpus sources.

Each source yields `RawDoc`s. Local sources read from the repo; remote sources
cache their fetches under `data/raw/` (gitignored) and reuse them — so a re-ingest
is offline unless `--refresh` is passed.

- `synthetic`  — hand-written paymentsvc runbooks in the repo.
- GitHub repos — a downloaded tarball of `.md` files.
- `postmortems` — the ~200 external links in danluu/post-mortems, fetched
  best-effort and reduced to article text; dead/blocked links are skipped.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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


# --- remote: danluu/post-mortems (external articles) ----------------------

_POSTMORTEMS_README = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"
_PM_CACHE = _RAW_CACHE / "postmortems"
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_MIN_ARTICLE_CHARS = 400
_FETCH_DELAY_S = 0.3
_PM_FETCH_TIMEOUT_S = 12
# Hosts to skip outright: archive snapshots are slow/rate-limited and dominate the
# failure/timeout budget for little gain.
_PM_SKIP_HOSTS = ("web.archive.org", "webcache.googleusercontent.com")


def _http_get(url: str, *, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; runbook-ingest/0.1; "
                "+https://github.com/AllergySnipe/runbook)"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_readme(md: str) -> list[tuple[str, str, str]]:
    """Return (name, url, category) for every external link, skipping the
    meta sections that list other collections rather than incidents."""
    skip = {"other lists of postmortems", "contributors"}
    entries: list[tuple[str, str, str]] = []
    category = "uncategorized"
    seen: set[str] = set()
    for line in md.splitlines():
        h = re.match(r"#{1,6}\s+(.*)", line)
        if h:
            category = h.group(1).strip().lower()
            continue
        if category in skip:
            continue
        for name, url in _MD_LINK.findall(line):
            if "github.com/danluu/post-mortems" in url or url in seen:
                continue
            seen.add(url)
            entries.append((name.strip(), url, category))
    return entries


def postmortem_docs(*, refresh: bool = False) -> Iterator[RawDoc]:
    from trafilatura import extract  # heavy import; keep it lazy

    _PM_CACHE.mkdir(parents=True, exist_ok=True)
    readme_path = _RAW_CACHE / "danluu-post-mortems.md"
    if not readme_path.exists() or refresh:
        _RAW_CACHE.mkdir(parents=True, exist_ok=True)
        readme_path.write_bytes(_http_get(_POSTMORTEMS_README))

    entries = _parse_readme(readme_path.read_text())
    ok = failed = 0
    for name, url, category in entries:
        if any(host in url for host in _PM_SKIP_HOSTS):
            failed += 1
            continue
        key = hashlib.sha1(url.encode()).hexdigest()[:16]  # cache key, not security
        cache = _PM_CACHE / f"{key}.txt"

        if cache.exists() and not refresh:
            text = cache.read_text()
        else:
            time.sleep(_FETCH_DELAY_S)
            try:
                html = _http_get(url, timeout=_PM_FETCH_TIMEOUT_S).decode("utf-8", errors="replace")
                text = extract(html, url=url, include_comments=False) or ""
            except (urllib.error.URLError, OSError, ValueError, UnicodeError):
                # dead links, timeouts, TLS errors, paywalls, malformed responses — all expected
                text = ""
            cache.write_text(text)

        if len(text.strip()) < _MIN_ARTICLE_CHARS:
            failed += 1
            continue
        ok += 1
        yield RawDoc(
            source="postmortem",
            origin=urlparse(url).netloc,
            title=f"{name} — postmortem",
            url=url,
            path=url,
            text=text,
        )

    print(
        f"ingest: postmortems — {ok} extracted, {failed} skipped (dead/blocked/thin) "
        f"of {len(entries)} links",
        file=sys.stderr,
    )


# --- registry -------------------------------------------------------------

# Every source that can be named with `--source`.
ALL_SOURCES = ("synthetic", *_GITHUB_REPOS.keys(), "postmortems")
# What a bare `runbook ingest` runs. `postmortems` is opt-in: the danluu list is
# ~200 external links, many dead or archive-only, so a full run is slow and flaky.
DEFAULT_SOURCES = ("synthetic", *_GITHUB_REPOS.keys())


def load_source(name: str, *, refresh: bool = False) -> Iterator[RawDoc]:
    if name == "synthetic":
        return synthetic_docs()
    if name in _GITHUB_REPOS:
        return github_docs(name, refresh=refresh)
    if name == "postmortems":
        return postmortem_docs(refresh=refresh)
    raise ValueError(f"unknown source: {name!r} (known: {', '.join(ALL_SOURCES)})")
