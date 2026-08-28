---
service: paymentsvc
failure_mode: acquirer-gw-timeouts
severity: SEV1
alert: PaymentsvcErrorRateHigh
---

# paymentsvc — Acquirer gateway timeouts / elevated 5xx

## Summary

`acquirer-gw` is the external card processor. `paymentsvc` calls it synchronously on the
charge path. When `acquirer-gw` slows down or fails, `paymentsvc` returns 5xx to
`checkout-web` and customers cannot pay. This is customer-facing revenue loss — treat as
SEV1 until proven otherwise.

## Alert

`PaymentsvcErrorRateHigh` — 5xx rate on `POST /charges` over 5m exceeds 2%.

## Symptoms

- 5xx rate rises; the errors are `502`/`504` from `paymentsvc`, not `400`s.
- Logs: `acquirer-gw request failed: deadline exceeded` or `upstream connect timeout`.
- `paymentsvc_acquirer_request_duration_seconds` p95 climbs toward the client timeout.
- Charge *attempts* are flat or rising while charge *successes* drop.
- Often no `paymentsvc` deploy correlates — the change is upstream.

## Likely causes

1. `acquirer-gw` degradation or partial outage on their side.
2. Network path degradation between `paymentsvc` and `acquirer-gw`.
3. A `paymentsvc` change that increased per-request work or lowered the client timeout.
4. Retry storm — `paymentsvc` retries aggressively on timeout, adding load to an already
   slow upstream and making it worse.

## Diagnosis

1. `query_metrics` — `paymentsvc_acquirer_request_duration_seconds` p50/p95/p99 and
   `paymentsvc_acquirer_error_total` by error type (`timeout`, `connection_refused`, `5xx`).
2. `query_metrics` — retry rate: `paymentsvc_acquirer_retry_total` / request total. A ratio
   climbing above ~0.3 indicates cause (4) is amplifying the incident.
3. `get_recent_deploys` — rule out cause (3). If nothing shipped, focus upstream.
4. `search_logs` — sample the failure lines; `deadline exceeded` vs `connection refused`
   distinguishes a slow upstream (1) from a hard network break (2).
5. `get_service_dependencies` — confirm `acquirer-gw` is the only upstream on this path and
   check its published status.

## Remediation

- **[read-only] Check the `acquirer-gw` status page / support channel** for a declared
  incident. If confirmed, this is cause (1): mitigate and wait.
- **[state-changing — needs approval] Reduce retry aggressiveness** (lower max retries,
  add jitter/backoff) via config flag if step 2 showed a retry storm.
- **[state-changing — needs approval] Enable the circuit breaker** on the `acquirer-gw`
  client so `paymentsvc` fails fast and sheds load from the upstream.
- **[state-changing — needs approval] Fail over to the secondary acquirer route** if one is
  configured (`ACQUIRER_ROUTE=secondary`).
- **[read-only] Post customer-facing status** — payments degraded — via the incident channel.
- **[state-changing — needs approval] Roll back** the implicated `paymentsvc` deploy for
  cause (3).

## Escalation

Page the `payments` service owner and open a vendor ticket with `acquirer-gw` immediately if
their side is implicated. Loop in the on-call incident commander — this is revenue-impacting.

## Related

- `db-connection-pool-exhaustion.md` — a slow `acquirer-gw` call inside a DB transaction
  drains the pool as a secondary effect.
- `payments-events-consumer-lag.md` — failed synchronous charges still enqueue events;
  watch for downstream lag afterward.
