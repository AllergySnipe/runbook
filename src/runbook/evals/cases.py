"""The golden set: hand-labelled alerts, each with what a competent responder
would conclude.

Construction (ADR-0008):

- **Scenarios x paraphrases.** Each `sim/` scenario is one *world*. Real alerts
  describing that world are worded a hundred ways, so each scenario gets the
  canonical Alertmanager `alertname` **plus paraphrases** in deliberately
  different vocabulary. Paraphrase #1 of each incident is the one already in
  `tests/test_retrieval_quality.py` (kept in sync on purpose).
- **Negatives.** Cases that *should* short-circuit — a self-resolved flap
  (`noise-or-flapping`), a vague report (`need-more-info`), and the `healthy`
  world (the model must not invent a root cause).
- **Novel incidents.** A plausible real incident described in terms no runbook
  covers — triage should proceed but flag low-prior, and the run should escalate
  rather than force a bad fix.

Labels are ground truth. If a label is wrong the eval punishes a correct answer
and rewards a wrong one — worse than no eval. Every label here is set against the
scenario fixture + its runbook by hand; re-check them when a scenario changes.

`expect_disposition` values: `auto` (grounded, all steps read-only),
`needs-approval` (>=1 state-changing step), `escalate` (no grounded step or
synthesis failed), `short-circuit` (triage did not run the loop). A case may list
alternatives with `|` (e.g. `auto|escalate` for a novel incident, where the only
firm requirement is "not needs-approval").
"""

from __future__ import annotations

from dataclasses import dataclass

# triage categories, repeated here so cases.py has no import cycle with core/
TRIAGE_KNOWN = "known-runbook"
TRIAGE_NOVEL = "novel-incident"
TRIAGE_NOISE = "noise-or-flapping"
TRIAGE_NEEDINFO = "need-more-info"


@dataclass(frozen=True)
class EvalCase:
    id: str
    alert: str
    scenario: str
    expect_triage: str
    expect_runbook: str | None
    expect_failure_mode: str | None
    expect_disposition: str
    reference_root_cause: str
    notes: str = ""
    judge: bool = True  # run the root-cause LLM-judge? off for novel cases (escalation, not RCA)

    @property
    def is_incident(self) -> bool:
        """A real incident the loop should investigate (vs. noise / need-info)."""
        return self.expect_triage in (TRIAGE_KNOWN, TRIAGE_NOVEL)


# --------------------------------------------------------------------------
# 1. acquirer-gw-timeouts  — slow external card processor, retry storm
# --------------------------------------------------------------------------
_ACQUIRER_RC = (
    "The external card processor `acquirer-gw` slowed down (partial outage on their side). "
    "`paymentsvc` calls it synchronously on the charge path, so acquirer latency became "
    "paymentsvc 502/504s. A retry ratio above ~0.4 amplified load on the already-slow "
    "upstream. No paymentsvc deploy correlates — the change is upstream."
)
_ACQUIRER = [
    EvalCase(
        id="acquirer-gw/canonical",
        alert="PaymentsvcErrorRateHigh — 5xx rate on POST /charges over 2% for 5m",
        scenario="acquirer-gw-timeouts",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="acquirer-gw-timeouts.md",
        expect_failure_mode="acquirer-gw-timeouts",
        expect_disposition="needs-approval",
        reference_root_cause=_ACQUIRER_RC,
    ),
    EvalCase(
        id="acquirer-gw/paraphrase-1",
        alert=(
            "checkout is throwing 5xx on POST /charges, our external card processor "
            "looks slow and customers can't complete payments"
        ),
        scenario="acquirer-gw-timeouts",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="acquirer-gw-timeouts.md",
        expect_failure_mode="acquirer-gw-timeouts",
        expect_disposition="needs-approval",
        reference_root_cause=_ACQUIRER_RC,
    ),
    EvalCase(
        id="acquirer-gw/paraphrase-2",
        alert=(
            "spike in 502/504 responses from the charge endpoint. acquirer-gw p95 is "
            "climbing toward our client timeout and the retry ratio is way up. nothing "
            "shipped on our side today."
        ),
        scenario="acquirer-gw-timeouts",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="acquirer-gw-timeouts.md",
        expect_failure_mode="acquirer-gw-timeouts",
        expect_disposition="needs-approval",
        reference_root_cause=_ACQUIRER_RC,
    ),
    EvalCase(
        id="acquirer-gw/paraphrase-3",
        alert=(
            "payments failing intermittently — logs full of 'deadline exceeded' calling "
            "the card processor. their status page mentions degraded performance."
        ),
        scenario="acquirer-gw-timeouts",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="acquirer-gw-timeouts.md",
        expect_failure_mode="acquirer-gw-timeouts",
        expect_disposition="needs-approval",
        reference_root_cause=_ACQUIRER_RC,
    ),
]

# --------------------------------------------------------------------------
# 2. bad-migration-table-lock  — ALTER TABLE holding AccessExclusiveLock
# --------------------------------------------------------------------------
_MIGRATION_RC = (
    "A deploy shipped a migration (an ALTER TABLE that rewrites `charges`) which took an "
    "AccessExclusiveLock; backends are queued on Lock and Postgres CPU is low because "
    "everything is waiting, not working. Success rate collapsed within ~2m of the deploy. "
    "Fix path: terminate the blocking migration session, then roll back the deploy."
)
_MIGRATION = [
    EvalCase(
        id="bad-migration/canonical",
        alert="PaymentsvcAvailabilityLow — success rate on POST /charges below 95%",
        scenario="bad-migration-table-lock",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="bad-migration-table-lock.md",
        expect_failure_mode="bad-migration-table-lock",
        expect_disposition="needs-approval",
        reference_root_cause=_MIGRATION_RC,
    ),
    EvalCase(
        id="bad-migration/paraphrase-1",
        alert=(
            "right after the last deploy paymentsvc availability tanked, queries on the "
            "charges table seem stuck waiting on a lock from a schema change"
        ),
        scenario="bad-migration-table-lock",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="bad-migration-table-lock.md",
        expect_failure_mode="bad-migration-table-lock",
        expect_disposition="needs-approval",
        reference_root_cause=_MIGRATION_RC,
    ),
    EvalCase(
        id="bad-migration/paraphrase-2",
        alert=(
            "charges are mostly failing since ~16:42. deploy went out a couple minutes "
            "before. pg_stat_activity shows dozens of backends in 'Lock' wait, db cpu "
            "near zero. 'lock timeout' errors in the logs."
        ),
        scenario="bad-migration-table-lock",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="bad-migration-table-lock.md",
        expect_failure_mode="bad-migration-table-lock",
        expect_disposition="needs-approval",
        reference_root_cause=_MIGRATION_RC,
    ),
    EvalCase(
        id="bad-migration/paraphrase-3",
        alert=(
            "SEV1 — payment success rate fell off a cliff to ~40% right after release "
            "v… with migration 0043. everything is blocked on the charges table."
        ),
        scenario="bad-migration-table-lock",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="bad-migration-table-lock.md",
        expect_failure_mode="bad-migration-table-lock",
        expect_disposition="needs-approval",
        reference_root_cause=_MIGRATION_RC,
    ),
]

# --------------------------------------------------------------------------
# 3. db-connection-pool-exhaustion  — query regression, connections held longer
# --------------------------------------------------------------------------
_POOL_RC = (
    "A deploy refactored the charge-lookup query and its p99 stepped from ~50ms to ~800ms, "
    "so every request holds its Postgres connection ~15x longer and throughput no longer "
    "covers arrival rate. `paymentsvc_db_pool_checked_out` is pinned at pool size while "
    "Postgres CPU, replication lag and lock counts stay normal — the database is fine, the "
    "app cannot get a connection. Fix path: roll back the implicated deploy."
)
_POOL = [
    EvalCase(
        id="db-pool/canonical",
        alert="PaymentsvcP99LatencyHigh — p99 of POST /charges over 5m exceeds 2s",
        scenario="db-connection-pool-exhaustion",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="db-connection-pool-exhaustion.md",
        expect_failure_mode="db-connection-pool-exhaustion",
        expect_disposition="needs-approval",
        reference_root_cause=_POOL_RC,
    ),
    EvalCase(
        id="db-pool/paraphrase-1",
        alert=(
            "p99 latency spiked to several seconds but the database CPU and load are "
            "normal, looks like requests are waiting for a free connection"
        ),
        scenario="db-connection-pool-exhaustion",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="db-connection-pool-exhaustion.md",
        expect_failure_mode="db-connection-pool-exhaustion",
        expect_disposition="needs-approval",
        reference_root_cause=_POOL_RC,
    ),
    EvalCase(
        id="db-pool/paraphrase-2",
        alert=(
            "charge endpoint slow — p99 ~3s, p50 fine. 'pool timeout: no connection "
            "available after 5000ms' all over the logs. postgres looks healthy. a deploy "
            "landed ~10 min before it started."
        ),
        scenario="db-connection-pool-exhaustion",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="db-connection-pool-exhaustion.md",
        expect_failure_mode="db-connection-pool-exhaustion",
        expect_disposition="needs-approval",
        reference_root_cause=_POOL_RC,
    ),
    EvalCase(
        id="db-pool/paraphrase-3",
        alert=(
            "latency alarm on payments. checked-out connections sitting at the max (20) "
            "the whole time. query duration jumped after the last release."
        ),
        scenario="db-connection-pool-exhaustion",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="db-connection-pool-exhaustion.md",
        expect_failure_mode="db-connection-pool-exhaustion",
        expect_disposition="needs-approval",
        reference_root_cause=_POOL_RC,
    ),
]

# --------------------------------------------------------------------------
# 4. noisy-neighbour-cpu-throttling  — co-located workload saturating the node
# --------------------------------------------------------------------------
_NOISY_RC = (
    "A co-located workload (a batch-reconciler that scaled up) saturated the node (node CPU "
    "~92%), so `paymentsvc` is CFS-throttled (~35% of periods) even though its own CPU usage "
    "is only ~65% of its limit. Latency is bursty/sawtooth tracking the 100ms CFS period. No "
    "paymentsvc deploy, no dependency errors, no traffic change. Fix path: raise the CPU "
    "limit, scale out, or move paymentsvc off the contended node."
)
_NOISY = [
    EvalCase(
        id="noisy-neighbour/canonical",
        alert="PaymentsvcCpuThrottlingHigh — CFS throttled-periods ratio over 25%",
        scenario="noisy-neighbour-cpu-throttling",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="noisy-neighbour-cpu-throttling.md",
        expect_failure_mode="noisy-neighbour-cpu-throttling",
        expect_disposition="needs-approval",
        reference_root_cause=_NOISY_RC,
    ),
    EvalCase(
        id="noisy-neighbour/paraphrase-1",
        alert=(
            "latency rising in bursts with no traffic change and no deploy, cfs "
            "throttled periods are high but cpu usage is only moderate"
        ),
        scenario="noisy-neighbour-cpu-throttling",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="noisy-neighbour-cpu-throttling.md",
        expect_failure_mode="noisy-neighbour-cpu-throttling",
        expect_disposition="needs-approval",
        reference_root_cause=_NOISY_RC,
    ),
    EvalCase(
        id="noisy-neighbour/paraphrase-2",
        alert=(
            "paymentsvc p99 is sawtoothing between 200ms and 1.5s. no errors, deps all "
            "green, nothing deployed. the node it's on is pegged near 100% cpu though."
        ),
        scenario="noisy-neighbour-cpu-throttling",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="noisy-neighbour-cpu-throttling.md",
        expect_failure_mode="noisy-neighbour-cpu-throttling",
        expect_disposition="needs-approval",
        reference_root_cause=_NOISY_RC,
    ),
    EvalCase(
        id="noisy-neighbour/paraphrase-3",
        alert=(
            "intermittent slowness on the payments pod since ~11:05. container keeps "
            "getting throttled. we didn't change anything — think a neighbour on the box "
            "is hammering the CPU."
        ),
        scenario="noisy-neighbour-cpu-throttling",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="noisy-neighbour-cpu-throttling.md",
        expect_failure_mode="noisy-neighbour-cpu-throttling",
        expect_disposition="needs-approval",
        reference_root_cause=_NOISY_RC,
    ),
]

# --------------------------------------------------------------------------
# 5. payments-events-consumer-lag  — downstream consumer crash-looping
# --------------------------------------------------------------------------
_LAG_RC = (
    "A `ledger` deploy that refactored the event handler shipped a bug: "
    "`eventHandler.Process` nil-pointer-dereferences on the `occurred_at` field of the v2 "
    "schema envelope, so the consumer panics and crash-loops (CrashLoopBackOff, ~14 restarts "
    "in 10m). `payments-events` consumer-group lag climbs past 45k, even across all partitions "
    "(so it's the crashing consumer, not a poison message on one offset). The charge/pay path "
    "itself is healthy. Fix path: roll back the ledger deploy and restart the consumer; "
    "nothing shipped for paymentsvc. Naming the specific panic (nil deref on `occurred_at`) "
    "is correct — it's in the logs."
)
_LAG = [
    EvalCase(
        id="consumer-lag/canonical",
        alert="PaymentsEventsConsumerLagHigh — consumer-group lag over 10k, oldest-unacked over 10m",
        scenario="payments-events-consumer-lag",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="payments-events-consumer-lag.md",
        expect_failure_mode="payments-events-consumer-lag",
        expect_disposition="needs-approval",
        reference_root_cause=_LAG_RC,
    ),
    EvalCase(
        id="consumer-lag/paraphrase-1",
        alert=(
            "charges are succeeding but the ledger and merchant webhooks are delayed, "
            "consumer group lag on the events queue keeps climbing"
        ),
        scenario="payments-events-consumer-lag",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="payments-events-consumer-lag.md",
        expect_failure_mode="payments-events-consumer-lag",
        expect_disposition="needs-approval",
        reference_root_cause=_LAG_RC,
    ),
    EvalCase(
        id="consumer-lag/paraphrase-2",
        alert=(
            "webhook delivery running ~15 min behind. payments-events lag at 45k and "
            "growing evenly on every partition. ledger pod has restarted a dozen times "
            "since its deploy. panics in its logs."
        ),
        scenario="payments-events-consumer-lag",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="payments-events-consumer-lag.md",
        expect_failure_mode="payments-events-consumer-lag",
        expect_disposition="needs-approval",
        reference_root_cause=_LAG_RC,
    ),
    EvalCase(
        id="consumer-lag/paraphrase-3",
        alert=(
            "merchants complaining their settlement events are late. pay path metrics all "
            "look normal. something downstream is backed up on the events topic."
        ),
        scenario="payments-events-consumer-lag",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="payments-events-consumer-lag.md",
        expect_failure_mode="payments-events-consumer-lag",
        expect_disposition="needs-approval",
        reference_root_cause=_LAG_RC,
    ),
]

# --------------------------------------------------------------------------
# 6. redis-eviction-idempotency  — LRU evicting idempotency keys, double charges
# --------------------------------------------------------------------------
_REDIS_RC = (
    "Redis `used_memory` is at ~0.99 of maxmemory and the `allkeys-lru` policy is evicting "
    "idempotency keys before their TTL, so key lookups MISS (~4%) and retried charges are "
    "processed twice (duplicate-charge rows appear). A deploy added per-merchant rate-limit "
    "counters to the same Redis, pushing it over. The idempotency path is failing *open*. "
    "Fix path: make the check fail closed, raise Redis maxmemory / TTL, roll back the deploy."
)
_REDIS = [
    EvalCase(
        id="redis-evict/canonical",
        alert="PaymentsvcIdempotencyMissRateHigh — idempotency-key miss rate over 1%",
        scenario="redis-eviction-idempotency",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="redis-eviction-idempotency.md",
        expect_failure_mode="redis-eviction-idempotency",
        expect_disposition="needs-approval",
        reference_root_cause=_REDIS_RC,
    ),
    EvalCase(
        id="redis-evict/paraphrase-1",
        alert=(
            "idempotency key lookups are missing and we're at risk of double-charging "
            "customers on retries, redis is under memory pressure and evicting keys"
        ),
        scenario="redis-eviction-idempotency",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="redis-eviction-idempotency.md",
        expect_failure_mode="redis-eviction-idempotency",
        expect_disposition="needs-approval",
        reference_root_cause=_REDIS_RC,
    ),
    EvalCase(
        id="redis-evict/paraphrase-2",
        alert=(
            "seeing duplicate charge rows for a handful of customers. charges still "
            "succeed. redis memory at 99%, evicted_keys climbing. a deploy ~40 min ago "
            "started writing rate-limit counters to that redis."
        ),
        scenario="redis-eviction-idempotency",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="redis-eviction-idempotency.md",
        expect_failure_mode="redis-eviction-idempotency",
        expect_disposition="needs-approval",
        reference_root_cause=_REDIS_RC,
    ),
    EvalCase(
        id="redis-evict/paraphrase-3",
        alert=(
            "SEV1 double-charge risk. retries that should hit the idempotency cache are "
            "going through as new charges. cache instance looks full."
        ),
        scenario="redis-eviction-idempotency",
        expect_triage=TRIAGE_KNOWN,
        expect_runbook="redis-eviction-idempotency.md",
        expect_failure_mode="redis-eviction-idempotency",
        expect_disposition="needs-approval",
        reference_root_cause=_REDIS_RC,
    ),
]

# --------------------------------------------------------------------------
# 7. negatives — should short-circuit at triage
# --------------------------------------------------------------------------
_NEGATIVE = [
    EvalCase(
        id="noise/self-resolved-flap",
        alert=(
            '{"status":"resolved","commonLabels":{"alertname":"PaymentsvcP99LatencyHigh",'
            '"service":"paymentsvc","severity":"warning"},"alerts":[{"status":"resolved",'
            '"startsAt":"2026-08-30T02:14:05Z","endsAt":"2026-08-30T02:14:38Z"}]}'
        ),
        scenario="healthy",
        expect_triage=TRIAGE_NOISE,
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="short-circuit",
        reference_root_cause="No incident — a single latency blip that fired and resolved in 33s.",
        notes="Alertmanager 'resolved' envelope, <1min firing window = a flap.",
    ),
    EvalCase(
        id="noise/deploy-blip",
        alert=(
            "brief 5xx bump on the charge endpoint for about 20 seconds during the "
            "rollout, back to normal now. probably just the deploy cycling pods."
        ),
        scenario="healthy",
        expect_triage=TRIAGE_NOISE,
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="short-circuit",
        reference_root_cause="No incident — a short error bump during a normal rolling deploy, already recovered.",
    ),
    EvalCase(
        id="need-info/vague-payments",
        alert="something seems off with payments today, can someone take a look",
        scenario="healthy",
        expect_triage=TRIAGE_NEEDINFO,
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="short-circuit",
        reference_root_cause="Not actionable — no symptom, metric, time, or scope given.",
    ),
    EvalCase(
        id="need-info/no-symptom",
        alert="PagerDuty went off for paymentsvc but I can't tell why, dashboards look mostly fine",
        scenario="healthy",
        expect_triage=TRIAGE_NEEDINFO,
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="short-circuit",
        reference_root_cause="Not actionable — the reporter has no concrete symptom to investigate.",
    ),
]

# --------------------------------------------------------------------------
# 8. novel incidents — real, but no runbook covers them, and no sim world
#    models them. Run against `healthy` so the fixtures don't *contradict* the
#    alert: the tools show nothing unusual, and the only safe move is to
#    escalate on the alert text rather than force a fit to a retrieved runbook.
#    Judged on triage + failure_mode + disposition + the hard checks — NOT the
#    root-cause judge (there is nothing to diagnose; `judge=False`).
# --------------------------------------------------------------------------
_NOVEL = [
    EvalCase(
        id="novel/acquirer-cert-expiry",
        alert=(
            "all calls to the acquirer callback endpoint are failing TLS handshake since "
            "~09:00 — 'certificate has expired'. charges that need the callback are stuck."
        ),
        scenario="healthy",
        expect_triage=TRIAGE_NOVEL,
        expect_runbook=None,
        expect_failure_mode="unknown",
        expect_disposition="auto|escalate",
        reference_root_cause=(
            "A TLS certificate on the acquirer callback path expired. No runbook covers "
            "cert expiry and no sim telemetry corroborates it — the correct outcome is to "
            "escalate on the alert text, not to adopt a loosely-retrieved runbook's cause."
        ),
        judge=False,
        notes="healthy sim: tools show nothing. Tests triage=novel + escalation under no signal.",
    ),
    EvalCase(
        id="novel/feature-flag-fanout",
        alert=(
            "since a config change at 13:10, every charge is doing ~40 synchronous calls "
            "to the pricing service instead of 1. pricing is now overloaded and paymentsvc "
            "p99 is 6s. no code deploy, just a flag flip."
        ),
        scenario="healthy",
        expect_triage=TRIAGE_NOVEL,
        expect_runbook=None,
        expect_failure_mode="unknown",
        expect_disposition="auto|escalate",
        reference_root_cause=(
            "A feature-flag change turned a batched pricing lookup into an N+1 fan-out, "
            "overloading the pricing service. No runbook covers it and the sim does not "
            "model a pricing service — escalate on the alert text rather than forcing a fit."
        ),
        judge=False,
        notes="healthy sim: no corroborating signal. Correct move is escalate, not a rollback.",
    ),
]

CASES: list[EvalCase] = [
    *_ACQUIRER,
    *_MIGRATION,
    *_POOL,
    *_NOISY,
    *_LAG,
    *_REDIS,
    *_NEGATIVE,
    *_NOVEL,
]

_ids = [c.id for c in CASES]
assert len(_ids) == len(set(_ids)), "duplicate eval case id"
