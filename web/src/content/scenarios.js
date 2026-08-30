// Editorial copy for each sim scenario — merged by name onto GET /api/scenarios
// (which supplies the canonical summary, severity, alert, expected_runbook).
// `impact` is the business framing; `watch` is what a good investigation finds.

export const SCENARIO_COPY = {
  "db-connection-pool-exhaustion": {
    oneLiner: "p99 latency blows past the timeout because every DB connection is checked out.",
    impact:
      "Charge requests time out for a growing share of traffic. Not an outage — a brownout that widens until the pool frees up or the service restarts.",
    watch:
      "Pool in-use pegged at the max for minutes, a matching rise in p99, and a recent traffic step or a slow-query change — not a deploy that broke a query outright.",
    difficulty: "Looks like the bad-migration case at a glance; the tell is that Postgres is busy, not waiting.",
  },
  "acquirer-gw-timeouts": {
    oneLiner: "5xx on /charges climbs because the external card processor slowed down.",
    impact:
      "Real revenue is failing — customers see declined payments. But the fault is upstream and outside our control; the fix is shielding, not repair.",
    watch:
      "502/504s rather than 400s, latency concentrated on the acquirer call, the acquirer's own dependency marked degraded, and nothing in our recent deploys.",
    difficulty: "The right answer is often to escalate / apply a circuit-breaker, not to 'fix' anything in paymentsvc.",
  },
  "payments-events-consumer-lag": {
    oneLiner: "The events consumer falls behind, so webhooks and ledger updates are delayed.",
    impact:
      "No charge fails, but downstream systems (ledger, notifications) drift out of sync. Lower severity, real reconciliation cost if it runs long.",
    watch:
      "Consumer group lag rising steadily, consumer throughput flat or dropped, and either a partition-count change or a slow downstream write.",
    difficulty: "Tempting to page hard; it's a SEV3. The judgement call is scale the consumer vs wait it out.",
  },
  "redis-eviction-idempotency": {
    oneLiner: "Redis starts evicting keys, so idempotency lookups miss — double-charge risk.",
    impact:
      "The dangerous one. A retried payment whose idempotency key was evicted can charge the customer twice. Financial and trust damage, not just latency.",
    watch:
      "Redis used-memory at maxmemory with evicted_keys climbing, idempotency miss-rate tracking it, and a key-size or TTL change upstream.",
    difficulty: "High stakes, and the safe remediation (raise maxmemory / stop the bleeding) is state-changing — it goes through approval.",
  },
  "bad-migration-table-lock": {
    oneLiner: "A migration takes AccessExclusiveLock on charges and every request queues behind it.",
    impact:
      "Near-total availability loss on /charges within two minutes of a deploy. The clearest SEV1 — and the clearest 'roll back now'.",
    watch:
      "Success rate collapse right after a deploy, 'lock timeout' / 'AccessExclusiveLock' in the logs, dozens of backends queued on Lock, and Postgres CPU low because everything is waiting.",
    difficulty: "Superficially like pool exhaustion. The deploy correlation and the low CPU are the discriminators.",
  },
  "noisy-neighbour-cpu-throttling": {
    oneLiner: "Another tenant on the node saturates CPU; paymentsvc gets throttled.",
    impact:
      "Latency and error rate rise for no reason visible inside the service. A platform problem wearing an application costume.",
    watch:
      "cfs_throttled_periods climbing, container CPU near its limit while node CPU is saturated by something else, and no deploy or traffic change of our own.",
    difficulty: "Everything internal looks fine. The evidence is all at the node / cgroup level.",
  },
  healthy: {
    oneLiner: "Steady state — the alert is flapping, there's no incident.",
    impact: "Nothing. This is the negative case: the copilot should recognise noise and stop.",
    watch: "Metrics inside normal bands, no error signature in the logs, no recent deploy. Triage should short-circuit to noise-or-flapping.",
    difficulty: "Tests that the system doesn't hallucinate an incident to match an alert.",
  },
};
