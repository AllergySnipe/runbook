"""$/incident — what a run would cost at paid model list prices (ADR-0014).

The free OpenRouter `:free` endpoints bill $0. This estimates the same token
usage at the models' normal rates — the portfolio-honest "~$X per incident on
production infrastructure" number, not a real invoice.

`RATES` is USD per 1M tokens `(input, output)`, keyed by model id with any
`:free` suffix stripped. A run touches three or four models (triage/parse
workhorse, tool loop, guardrail second pass), and the fallback chain means the
model that *served* a call isn't always the one requested — so cost is
attributed per `usage["by_model"]`, which `llm.Usage.model` populates from the
provider's echoed `resp.model`.

Not counted (each <1% of a run; documented gap in ADR-0014):
- Jina embedding + rerank tokens (retrieval path, ~$0.0001/run)
- the triage call (`triage()` discards its usage)

Rates are approximate list prices as of 2026-08 — refresh from the OpenRouter
model pages if the number needs to be defensible to the dollar.
"""

from __future__ import annotations

RATES: dict[str, tuple[float, float]] = {
    "z-ai/glm-5.2": (0.40, 1.75),
    "nvidia/nemotron-3-super-120b-a12b": (0.10, 0.40),
    "minimax/minimax-m3": (0.30, 1.20),
    "minimax/minimax-m2.7": (0.25, 1.00),
}
_DEFAULT_RATE = (0.50, 1.50)


def estimate_cost(by_model: dict[str, dict] | None) -> float:
    """Sum `(in/1e6 * rate_in) + (out/1e6 * rate_out)` over every model that
    served part of the run. Returns USD, rounded to the micro-dollar."""
    total = 0.0
    for raw_model, u in (by_model or {}).items():
        rate_in, rate_out = RATES.get(raw_model.removesuffix(":free"), _DEFAULT_RATE)
        total += u.get("input_tokens", 0) / 1e6 * rate_in
        total += u.get("output_tokens", 0) / 1e6 * rate_out
    return round(total, 6)
