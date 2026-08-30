"""Measure the similarity separation the semantic cache relies on (ADR-0014).

The cache treats two alerts as "the same question" when their query embeddings
are within `cache_similarity_threshold` cosine. That number is only safe if
restatements of one incident sit clearly above genuinely-different incidents.
This script embeds every golden-set alert (`evals/cases.py`) and prints:

- same-scenario pairs   — paraphrases of one incident   → want HIGH similarity
- cross-scenario pairs   — different failure modes        → want LOW similarity

Run locally with a real JINA_API_KEY:

    uv run python scripts/calibrate_cache_threshold.py

Paste the min/max/mean rows into ADR-0014. If the two distributions overlap near
0.97, raise the threshold (or narrow the cache normalisation).
"""

from __future__ import annotations

import itertools
import statistics

from runbook.embed import embed_query
from runbook.evals.cases import CASES


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)


def main() -> None:
    incidents = [c for c in CASES if c.is_incident]
    print(f"embedding {len(incidents)} incident alerts ...")
    vecs = {c.id: embed_query(c.alert) for c in incidents}

    same: list[float] = []
    cross: list[float] = []
    for a, b in itertools.combinations(incidents, 2):
        sim = _cos(vecs[a.id], vecs[b.id])
        (same if a.scenario == b.scenario else cross).append(sim)

    def row(label: str, xs: list[float]) -> None:
        print(
            f"  {label:16s} n={len(xs):3d}  "
            f"min={min(xs):.3f}  mean={statistics.mean(xs):.3f}  max={max(xs):.3f}"
        )

    print("\ncosine similarity between alert pairs:")
    row("same-scenario", same)
    row("cross-scenario", cross)

    gate = 0.97
    fn = sum(1 for s in same if s < gate)
    fp = sum(1 for s in cross if s >= gate)
    print(f"\nat threshold {gate}:")
    print(f"  false negatives (paraphrases missed):        {fn}/{len(same)}")
    print(f"  false positives (different incidents merged): {fp}/{len(cross)}")


if __name__ == "__main__":
    main()
