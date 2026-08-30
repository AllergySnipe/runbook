"""Measure the similarity separation the semantic cache relies on (ADR-0014).

The cache treats two alerts as "the same question" when their query embeddings
are within `cache_similarity_threshold` cosine. The cache targets a *re-fire* of
one alert — same incident, text drifting only in the volatile fields (current
value, timestamp, a "(retry)" suffix) — NOT a reworded description. So this
script measures three distributions:

- near-duplicate  — a canonical alert vs. small perturbations of itself
                     → the cache-hit target; want HIGH similarity
- paraphrase       — the golden set's deliberately-diverse rewordings of one
                     incident → the cache is NOT expected to catch these
- cross-scenario   — different failure modes → want LOW similarity

Run locally with a real JINA_API_KEY:

    uv run python scripts/calibrate_cache_threshold.py

Paste the rows into ADR-0014 / LEARNINGS. If near-duplicate min drops near
cross-scenario max, raise the threshold or add a volatile-field-stripping
normalisation before embedding.
"""

from __future__ import annotations

import itertools
import re
import statistics

from runbook.embed import embed_query
from runbook.evals.cases import CASES

# text edits that model the same alert re-firing minutes later
_PERTURBATIONS = (
    lambda s: s + " (retry)",
    lambda s: s + " — still firing",
    lambda s: re.sub(
        r"\b(\d+)(ms|s|%)\b", lambda m: f"{int(m.group(1)) + 3}{m.group(2)}", s, count=1
    ),
    lambda s: re.sub(r"\b5m\b", "9m", s, count=1) if "5m" in s else s + " for 9m",
    lambda s: s.replace("p99", "p95") if "p99" in s else s.replace("above", "over"),
)


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)


def main() -> None:
    incidents = [c for c in CASES if c.is_incident]
    # one canonical alert per scenario (the first case listed for it)
    canon: dict[str, str] = {}
    for c in incidents:
        canon.setdefault(c.scenario, c.alert)

    print(f"embedding {len(incidents)} paraphrase alerts + {len(canon)} canon x perturbations ...")
    para_vecs = {c.id: embed_query(c.alert) for c in incidents}
    canon_vecs = {s: embed_query(a) for s, a in canon.items()}
    perturbed = {
        s: [embed_query(p(a)) for p in _PERTURBATIONS if p(a) != a] for s, a in canon.items()
    }

    near_dup = [_cos(canon_vecs[s], pv) for s, pvs in perturbed.items() for pv in pvs]
    paraphrase = [
        _cos(para_vecs[a.id], para_vecs[b.id])
        for a, b in itertools.combinations(incidents, 2)
        if a.scenario == b.scenario
    ]
    cross = [
        _cos(para_vecs[a.id], para_vecs[b.id])
        for a, b in itertools.combinations(incidents, 2)
        if a.scenario != b.scenario
    ]

    def row(label: str, xs: list[float]) -> None:
        print(
            f"  {label:16s} n={len(xs):3d}  "
            f"min={min(xs):.3f}  mean={statistics.mean(xs):.3f}  max={max(xs):.3f}"
        )

    print("\ncosine similarity between alert pairs:")
    row("near-duplicate", near_dup)
    row("paraphrase", paraphrase)
    row("cross-scenario", cross)

    gate = 0.97
    print(f"\nat threshold {gate}:")
    print(f"  near-duplicates caught: {sum(s >= gate for s in near_dup)}/{len(near_dup)}")
    print(f"  paraphrases caught:     {sum(s >= gate for s in paraphrase)}/{len(paraphrase)}")
    print(f"  cross-scenario merged:  {sum(s >= gate for s in cross)}/{len(cross)}")


if __name__ == "__main__":
    main()
