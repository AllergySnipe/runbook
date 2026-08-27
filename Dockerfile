FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

# uv: fast, reproducible installs straight from the committed lockfile
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app

# Dependencies first — this layer is cached unless pyproject.toml / uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Then the application code
COPY src ./src
COPY README.md ./
RUN uv sync --frozen

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

# The platform (Render) injects $PORT; default to 8000 for a bare `docker run`.
# --no-sync: the venv is already built above; don't re-sync on every container start.
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn runbook.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
