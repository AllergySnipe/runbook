---
service: paymentsvc
failure_mode: redis-eviction-idempotency
severity: SEV1
alert: PaymentsvcIdempotencyMissRateHigh
---

# paymentsvc — Redis eviction / idempotency failures / double-charge risk

## Summary

`paymentsvc` stores idempotency keys in Redis so a retried `POST /charges` with the same
`Idempotency-Key` returns the original result instead of charging twice. It also uses Redis
for rate limiting. If Redis evicts keys early (memory pressure) or is unavailable, retried
requests miss the idempotency check and can double-charge a customer. Treat as SEV1 — this
is a money-correctness bug.

## Alert

`PaymentsvcIdempotencyMissRateHigh` — rate of idempotency-key lookups returning MISS for a
key seen in the last 24h exceeds 1%.

## Symptoms

- `paymentsvc_idempotency_lookup_total{result="miss"}` rising for keys that should be hits.
- Redis `used_memory` at or near `maxmemory`; `evicted_keys` counter climbing.
- Redis latency spikes or connection errors in logs: `redis: connection refused` /
  `READONLY You can't write against a read only replica`.
- Duplicate charge rows in Postgres for the same `(merchant_id, idempotency_key)` — the
  smoking gun. Query for it.

## Likely causes

1. Redis memory pressure → `maxmemory-policy` evicting idempotency keys before their TTL.
2. Redis failover / restart losing the keyspace (no persistence or AOF disabled).
3. TTL on idempotency keys set too short relative to client retry windows.
4. A `paymentsvc` change to how keys are written (wrong key name, missing write).
5. Redis unreachable — network or auth — so `paymentsvc` fails open (processes without the
   check) instead of failing closed.

## Diagnosis

1. `query_metrics` — Redis `used_memory` / `maxmemory`, `evicted_keys` rate, `keyspace_hits`
   vs `keyspace_misses`. Eviction climbing = cause (1).
2. `query_metrics` — Redis availability / connection error rate for cause (2) or (5).
3. `search_logs` — grep for `redis` errors and for the idempotency code path's
   `fail-open` / `fail-closed` log line to learn which behavior is active.
4. `get_recent_deploys` — a `paymentsvc` deploy touching idempotency or Redis config = (4);
   an infra change to Redis = (1) or (2).
5. **[read-only]** Run the duplicate-charge query in Postgres to quantify customer impact.

## Remediation

- **[state-changing — needs approval] Make the idempotency check fail *closed*** — reject
  charges when Redis is unavailable rather than processing them — if step 3 showed fail-open.
  Prefer a brief payment outage over double charges.
- **[state-changing — needs approval] Raise Redis `maxmemory` / scale the instance** for
  cause (1), or switch `maxmemory-policy` to `noeviction` for the idempotency keyspace.
- **[state-changing — needs approval] Increase the idempotency-key TTL** for cause (3).
- **[state-changing — needs approval] Roll back** the implicated `paymentsvc` deploy.
- **[read-only] Enumerate affected customers** from the duplicate-charge query and hand off
  to the refunds/finance process. Do **not** issue refunds from here.

## Escalation

Page the `payments` service owner and the incident commander immediately — customer money is
affected. Engage finance/ops for the refund workflow. If Redis infra is managed by another
team, page them for causes (1)/(2).

## Related

- `payments-events-consumer-lag.md` — duplicate charges produce duplicate downstream events.
- `noisy-neighbour-cpu-throttling.md` — CPU throttling on the Redis host can look like (2)/(5).
