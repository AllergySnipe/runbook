"""Shared test setup.

The deterministic suite must run with no real secrets (CLAUDE.md golden rule 6,
`.github/workflows/ci.yml`). `config.Settings` requires `openrouter_api_key` and
`jina_api_key`, so provide throwaway values unless the environment already set
real ones. No test in the default suite makes a real model or embedding call —
they monkeypatch `llm.*` / `jina.*` / `diagnose` — so fake keys are correct here.

`DATABASE_URL` is deliberately *not* faked: the `*_integration.py` suites and the
retrieval-quality gate key their skip on it, so it must stay genuinely unset in
CI and genuinely set (via `.env`) locally. Same for a real `JINA_API_KEY` — the
retrieval-quality gate and `test_embed`'s live tests skip without one.
"""

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
os.environ.setdefault("JINA_API_KEY", "test-key-not-real")
