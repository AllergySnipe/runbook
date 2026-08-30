"""`core/cost.py` — the $/incident estimate.

Deterministic rate arithmetic: tokens x published price, summed over every model
that served part of the run (the fallback chain means that's often more than one).
"""

from __future__ import annotations

from runbook.core.cost import _DEFAULT_RATE, RATES, estimate_cost


def test_empty_usage_is_free():
    assert estimate_cost({}) == 0.0
    assert estimate_cost(None) == 0.0


def test_single_model_matches_hand_calc():
    model = "z-ai/glm-5.2"
    rate_in, rate_out = RATES[model]
    by_model = {f"{model}:free": {"input_tokens": 1_000_000, "output_tokens": 500_000}}
    expected = round(rate_in + 0.5 * rate_out, 6)
    assert estimate_cost(by_model) == expected


def test_free_suffix_is_stripped_before_rate_lookup():
    a = estimate_cost({"z-ai/glm-5.2:free": {"input_tokens": 10_000, "output_tokens": 2_000}})
    b = estimate_cost({"z-ai/glm-5.2": {"input_tokens": 10_000, "output_tokens": 2_000}})
    assert a == b > 0


def test_multi_model_run_sums_each_leg():
    by_model = {
        "nvidia/nemotron-3-super-120b-a12b:free": {"input_tokens": 4_000, "output_tokens": 400},
        "minimax/minimax-m3:free": {"input_tokens": 20_000, "output_tokens": 3_000},
    }
    parts = sum(estimate_cost({m: u}) for m, u in by_model.items())
    assert estimate_cost(by_model) == round(parts, 6)


def test_unknown_model_falls_back_to_default_rate():
    cost = estimate_cost({"some/brand-new-model": {"input_tokens": 1_000_000, "output_tokens": 0}})
    assert cost == round(_DEFAULT_RATE[0], 6)
