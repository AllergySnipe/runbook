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

    # LLM provider — OpenRouter (OpenAI-compatible), free models (ADR-0009).
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Retrieval provider — Jina (embeddings + reranking), hosted (ADR-0013,
    # superseding the local-model parts of ADR-0002/0003). New key: 10M free
    # tokens, no card. `src/runbook/jina.py` is the one call site.
    jina_api_key: str
    jina_base_url: str = "https://api.jina.ai/v1"
    # OpenRouter attribution headers (optional; show up on the OpenRouter dashboard).
    openrouter_referer: str = "https://github.com/nudgethink/runbook"
    openrouter_title: str = "Runbook"
    # Free tier: 20 req/min + (with >=$10 ever spent) 1000 req/day. The loop makes
    # ~6-10 calls per diagnose, so retry 429s rather than fail the run.
    llm_max_retries: int = 5

    # Postgres (Neon). `database_url` is the pooled connection (PgBouncer) — used by
    # the app at runtime. `database_url_unpooled` is the direct connection — used by
    # the migration applier, which needs session-level features the pooler drops.
    # Default "" so `get_settings()` works with no DB (CI, offline unit runs) — the
    # `*_integration.py` suites and the retrieval-quality gate skip on a falsy
    # `database_url`; anything that actually opens a connection fails loudly.
    database_url: str = ""
    database_url_unpooled: str = ""

    # Embeddings (ADR-0002 → ADR-0013): hosted Jina model. Changing either value
    # means a new migration for the vector dimension + a full re-embed
    # (`runbook embed --all`) — corpus vectors and query vectors must share a model.
    embedding_model: str = "jina-embeddings-v5-text-small"
    embedding_dim: int = 1024

    # Retrieval (ADR-0003 → ADR-0013): hybrid = pgvector + Postgres full-text, fused
    # with RRF, then a cross-encoder rerank pass (hosted Jina) over the shortlist.
    # Bigger quality jump available via "jina-reranker-v3.5" at more tokens/call.
    rerank_model: str = "jina-reranker-v2-base-multilingual"
    retrieve_candidates: int = 30  # per-list depth pulled before fusion / rerank
    rerank_enabled: bool = True

    # Semantic cache (ADR-0014). A proceeding alert within `similarity_threshold`
    # cosine AND `ttl_s` of a prior one reuses its triage verdict + retrieved
    # runbook set (never its diagnosis). The threshold is deliberately tight — a
    # false hit serves the wrong runbook for a real, distinct incident. See the
    # calibration table in ADR-0014. `cache_enabled` is the prod kill-switch;
    # `diagnose(use_cache=...)` is off by default so evals/red-team never cache.
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.97
    cache_ttl_s: int = 3600

    # Incident memory (ADR-0015). After a terminal run a human records the actual
    # root cause (`runbook outcome` / the dashboard form); it is embedded into
    # `incident_memory` and retrieved on future similar alerts as *context* (never
    # a grounding source — S3 is unchanged). `memory_similarity_floor` is a real
    # gate: below it the loop sees no similar incidents rather than a weak match.
    # Calibration (`scripts/calibrate_memory_threshold.py`, ADR-0015): recurrences
    # of the same incident embed at min 0.905, cross-scenario alerts at max 0.752,
    # diverse paraphrases at max 0.776 — so at 0.88 memory catches every
    # recurrence with zero false hits, but does NOT fire on a merely-similar
    # different incident (the paraphrase and cross-scenario bands overlap, so
    # "loosely similar" cannot be caught safely). `memory_dedupe_threshold` is the
    # tight store-time bar that stops a recurring page filling memory with
    # near-identical rows. `memory_enabled` is the prod kill-switch; the loop only
    # consults memory when `diagnose(use_memory=...)` is on (CLI + dashboard).
    memory_enabled: bool = True
    memory_similarity_floor: float = 0.88
    memory_dedupe_threshold: float = 0.97
    memory_top_n: int = 2

    # Observability — Langfuse tracing (ADR-0017). One trace per `diagnose()` run:
    # the tool-loop model calls (auto-captured by the `langfuse.openai` wrapper in
    # `llm.py`) nested under manual spans for triage / retrieve / tool-loop /
    # synthesis / guardrail. `src/runbook/obs.py` is the one integration point.
    # Empty keys ⇒ a silent no-op (CI / deterministic tests need nothing set);
    # `langfuse_enabled` is the explicit kill-switch on top of that. S5: the
    # `mask` / `mask_otel_spans` hooks route every trace field through
    # `redact.redact()` before export, backstopping `llm._redact_outgoing`.
    langfuse_enabled: bool = True
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_sample_rate: float = 1.0
    # `development` locally, `production` on Render (render.yaml) — keeps local
    # experiments out of the prod dashboards / evaluators.
    langfuse_environment: str = "development"

    # Model routing (ADR-0009 — free OpenRouter models). Free `:free` endpoints
    # each sit on ONE shared provider pool and 429 often, so every role is a
    # *chain*: OpenRouter walks it on a 429/5xx (`extra_body.models`).
    #
    #   triage_model / diagnosis_model — first choice (classification / tool loop)
    #   loop_fallbacks       — for the tool loop; needs function calling, not strict JSON
    #   structured_fallbacks — for every `llm.parse` (triage, guardrail 2nd pass,
    #                          synthesis); MUST be models that actually enforce a
    #                          json_schema (`structured_outputs`), or you get prose
    #   judge_model / judge_fallbacks — the eval judge; a different family from the
    #                          diagnosis model (self-preference), still strict-structured
    # nemotron-super is the parse workhorse — it reliably enforces a json_schema
    # on the free tier; GLM is stronger but its one free endpoint 429s constantly.
    triage_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    diagnosis_model: str = (
        "z-ai/glm-5.2:free"  # tool loop — GLM's agentic ability, MiniMax fallback
    )
    loop_fallbacks: list[str] = ["minimax/minimax-m3:free", "minimax/minimax-m2.7:free"]
    structured_fallbacks: list[str] = [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "z-ai/glm-5.2:free",
    ]
    judge_model: str = "z-ai/glm-5.2:free"  # a different family from the usual synthesis server
    judge_fallbacks: list[str] = ["nvidia/nemotron-3-super-120b-a12b:free"]

    # Difficulty routing (ADR-0014). A high-confidence `known-runbook` alert has an
    # unambiguous runbook to follow — it doesn't need the strongest agentic model
    # for the tool loop. Anything else (novel, low-confidence) keeps the full
    # `diagnosis_model` chain. The cost/latency payoff is LATENT on the free tier
    # (every model bills $0, latency is dominated by 429s) — this is policy +
    # plumbing now, a real lever once there's a paid tier or a local model.
    routing_enabled: bool = True
    fast_loop_model: str = "minimax/minimax-m3:free"
    fast_loop_fallbacks: list[str] = ["minimax/minimax-m2.7:free", "z-ai/glm-5.2:free"]


@lru_cache
def get_settings() -> Settings:
    """Cached accessor. Lazy on purpose: importing the app must not require secrets,
    so deterministic tests and CI can run without a key."""
    return Settings()  # type: ignore[call-arg]  # fields come from the environment
