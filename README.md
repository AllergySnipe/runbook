# Runbook

An on-call incident-response copilot: triage an alert, retrieve the right runbook and
similar past postmortems, gather signal from a simulated environment, and propose a
grounded diagnosis — pausing for human approval before any state-changing action.

- Design & scope: [`docs/SPEC.md`](docs/SPEC.md)
- Decisions: [`docs/adr/`](docs/adr/)
- Is it good enough for on-call? [`docs/design/eval-report.md`](docs/design/eval-report.md)

**Live:** https://runbook-cgkn.onrender.com (`/health`, `/docs`) — may cold-start after idle.

**Status:** Week 0 — walking skeleton (health check + one live model call).

## Local development

```bash
uv sync                        # create the venv from the lockfile
cp .env.example .env            # then fill in ANTHROPIC_API_KEY
uv run pytest                   # deterministic tests (no key needed)
uv run uvicorn runbook.app:app --reload --port 8000
```

Then:

```bash
curl localhost:8000/health
curl -X POST localhost:8000/api/demo -H 'content-type: application/json' \
  -d '{"prompt": "In one sentence, what is a runbook?"}'
```

## Deployment

Render, Docker runtime, configured via [`render.yaml`](render.yaml). Pushes to `main` deploy
automatically. Secrets are set in the Render dashboard.
