---
service: paymentsvc
failure_mode: payments-events-consumer-lag
severity: SEV3
alert: PaymentsEventsConsumerLagHigh
---

# paymentsvc — payments-events consumer lag / delayed webhooks

## Summary

After a charge succeeds, `paymentsvc` publishes to the `payments-events` queue. Downstream
consumers (`ledger`, `notification-svc`) read from it to update the ledger and send merchant
webhooks. When consumers fall behind, the money has moved but the ledger and webhooks lag —
merchants see "pending" for too long. Not customer-facing on the pay path, but a correctness
and trust problem.

## Alert

`PaymentsEventsConsumerLagHigh` — consumer group lag on `payments-events` exceeds 10k
messages, or oldest-unacked-message age exceeds 5m.

## Symptoms

- Queue depth / consumer lag rising monotonically.
- Merchant webhook delivery p95 age climbing; support tickets about "payment not showing up".
- Charge success rate is **normal** — the pay path is healthy.
- Possibly `ledger` or `notification-svc` error logs, or those services scaled down / crash-looping.

## Likely causes

1. A downstream consumer (`ledger` / `notification-svc`) is down, slow, or crash-looping.
2. A poison message — one event the consumer cannot process, blocking the partition if
   ordering is enforced and there is no dead-letter path.
3. Publish-rate spike from a charge-volume surge or a backfill/replay.
4. Consumer under-provisioned after a scale-down or a bad HPA setting.

## Diagnosis

1. `query_metrics` — `payments_events_consumer_lag` per consumer group and per partition.
   Lag on one partition only points to cause (2); even lag across all points to (1), (3), (4).
2. `query_metrics` — publish rate vs historical baseline for cause (3).
3. `get_service_dependencies` — health of `ledger` and `notification-svc`; check their pod
   counts and restart counts.
4. `search_logs` — on the lagging consumer, look for a repeating error on the same
   message/offset (cause 2) vs generic slowness.
5. `get_recent_deploys` — a recent `ledger` / `notification-svc` / schema deploy can cause
   (1) or (2).

## Remediation

- **[read-only] Identify the stuck consumer and partition** from step 1.
- **[state-changing — needs approval] Restart / scale up the lagging consumer** for cause
  (1) or (4).
- **[state-changing — needs approval] Roll back** the implicated downstream deploy.
- **[state-changing — needs approval] Route the poison message to the dead-letter queue**
  (advance the offset past it) for cause (2), and capture it for later analysis.
- **[read-only] Confirm no double-processing risk** before advancing any offset — consumers
  must be idempotent on event id.
- **[read-only] Once lag is draining, estimate catch-up time** (lag ÷ consume rate) and
  communicate it to support.

## Escalation

If the lagging consumer is owned by another team (`ledger`, `notification-svc`), page that
team. If a poison message involves malformed data from `paymentsvc` itself, page the
`payments` owner.

## Related

- `acquirer-gw-timeouts.md` — a burst of retried charges can spike publish rate afterward.
- `redis-eviction-idempotency.md` — duplicate events downstream if idempotency keys were lost.
