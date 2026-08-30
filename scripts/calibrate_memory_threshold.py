"""Measure the similarity separation incident-memory retrieval relies on (ADR-0015).

`memory.search` shows a past incident as context when its alert embedding is
within `memory_similarity_floor` cosine of the incoming alert. The floor has to
sit above the cross-scenario band (or memory surfaces an unrelated incident and
anchors the model wrong) while still catching what we actually want to catch.

The question this script answers: *what* can memory reliably catch?

- near-duplicate  — a canonical alert vs. small perturbations of itself (the same
                    incident re-firing / recurring later). HIGH similarity.
- paraphrase       — the golden set's deliberately-diverse rewordings of one
                    incident. The optimistic target — "a similar incident,
                    described differently".
- cross-scenario   — different failure modes. Must stay BELOW the floor.

If the paraphrase band overlaps cross-scenario (it does, per ADR-0014's cache
calibration), memory can only be trusted for *recurrences*, not loose
similarity — and the floor should be set accordingly. Run locally:

    uv run python scripts/calibrate_memory_threshold.py

Paste the rows into ADR-0015 / LEARNINGS.
"""

from __future__ import annotations

import itertools
import re
import statistics

from runbook.config import get_settings
from runbook.embed import embed_query
from runbook.evals.cases import CASES

_PERTURBATIONS = (
    lambda s: s + " (still firing)",
    lambda s: s + " — recurred, second time this month",
    lambda s: re.sub(
        r"\b(\d+)(ms|s|%)\b", lambda m: f"{int(m.group(1)) + 4}{m.group(2)}", s, count=1
    ),
    lambda s: s.replace("p99", "p95") if "p99" in s else s.replace("over", "above"),
)


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)


def main() -> None:
    incidents = [c for c in CASES if c.is_incident]
    canon: dict[str, str] = {}
    for c in incidents:
        canon.setdefault(c.scenario, c.alert)

    print(f"embedding {len(incidents)} paraphrases + {len(canon)} canon x perturbations ...")
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

    floor = get_settings().memory_similarity_floor
    print(f"\nat floor {floor}:")
    print(f"  recurrences caught:     {sum(s >= floor for s in near_dup)}/{len(near_dup)}")
    print(f"  paraphrases caught:     {sum(s >= floor for s in paraphrase)}/{len(paraphrase)}")
    print(f"  cross-scenario (bad):   {sum(s >= floor for s in cross)}/{len(cross)}")


if __name__ == "__main__":
    main()
