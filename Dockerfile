# --- frontend build --------------------------------------------------------
# The Vite/React dashboard is compiled to static files here and copied into the
# app image below, so prod ships one artifact and does no Node work at runtime.
FROM node:20-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build   # → /web/dist

# --- app ------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

# uv: fast, reproducible installs straight from the committed lockfile
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

# Create the unprivileged user up front and do everything as it — a late
# `chown -R /app` would duplicate the whole venv + model cache into a new layer
# (~500 MB). uv runs fine as non-root.
RUN useradd -m -u 1000 appuser
WORKDIR /app
RUN chown appuser /app
USER appuser

# Dependencies first — this layer is cached unless pyproject.toml / uv.lock change
COPY --chown=appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Then the application code
COPY --chown=appuser src ./src
COPY --chown=appuser README.md ./
RUN uv sync --frozen

# Read at runtime: docs/adr by GET /api/decisions; corpus/ by the grounding
# hydration in core/loop.py and by GET /api/runbooks (quote highlighting).
COPY --chown=appuser docs ./docs
COPY --chown=appuser corpus ./corpus

# The built dashboard. app.py serves it as the SPA when this directory exists.
COPY --from=frontend --chown=appuser /web/dist ./web/dist

# Bake the retrieval models into the image so prod does no download at runtime and
# has no network dependency on the query path (ADR-0002 / ADR-0003). Model names
# must match src/runbook/config.py (embedding_model, rerank_model).
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
RUN uv run --no-sync python -c "\
from fastembed import TextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5'); \
TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2')"

# The platform (Render) injects $PORT; default to 8000 for a bare `docker run`.
# --no-sync: the venv is already built above; don't re-sync on every container start.
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn runbook.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
