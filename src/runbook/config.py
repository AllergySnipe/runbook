"""Runtime configuration.

Loaded from environment variables (and a local `.env` in development). In production
these come from the Render dashboard (Environment). Never put real values in code or in
`.env.example`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str

    # Postgres (Neon). `database_url` is the pooled connection (PgBouncer) — used by
    # the app at runtime. `database_url_unpooled` is the direct connection — used by
    # the migration applier, which needs session-level features the pooler drops.
    database_url: str
    database_url_unpooled: str

    # Embeddings (ADR-0002): local model via fastembed. Changing either value means
    # a new migration for the vector dimension + a full re-embed.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Retrieval (ADR-0003): hybrid = pgvector + Postgres full-text, fused with RRF,
    # then a cross-encoder rerank pass over the fused shortlist.
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    retrieve_candidates: int = 30  # per-list depth pulled before fusion / rerank
    rerank_enabled: bool = True

    # Model routing: a cheap model for triage / classification, a capable model
    # for diagnosis / synthesis.
    triage_model: str = "claude-haiku-4-5"
    diagnosis_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor. Lazy on purpose: importing the app must not require secrets,
    so deterministic tests and CI can run without a key."""
    return Settings()  # type: ignore[call-arg]  # fields come from the environment
