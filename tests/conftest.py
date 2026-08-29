"""Shared test setup.

The deterministic suite must run with no real secrets (CLAUDE.md golden rule 6,
`.github/workflows/ci.yml`). `config.Settings` requires `openrouter_api_key`, so
provide a throwaway value unless the environment already set a real one. No test
in the default suite makes a real model call — they monkeypatch `llm.*` or
`diagnose` — so a fake key is correct here.

`DATABASE_URL` is deliberately *not* faked: the `*_integration.py` suites and the
retrieval-quality gate key their skip on it, so it must stay genuinely unset in
CI and genuinely set (via `.env`) locally.
"""

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
