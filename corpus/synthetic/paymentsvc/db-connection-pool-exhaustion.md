---
service: paymentsvc
failure_mode: db-connection-pool-exhaustion
severity: SEV2
alert: PaymentsvcP99LatencyHigh
---

# paymentsvc — Database connection-pool exhaustion

## Summary

`paymentsvc` holds a bounded pool of Postgres connections (default 20 per pod). When
all connections are checked out, new requests block waiting for one, then time out.
The signature is a sharp p99 latency rise with normal CPU and normal database load —
the database is fine, the app just cannot reach it.

## Alert

`PaymentsvcP99LatencyHigh` — p99 of `POST /charges` over 5m exceeds 2s.

## Symptoms

- p99 latency climbs to seconds; p50 stays near baseline until the pool is fully drained.
- Error logs contain `pool timeout: no connection available after 5000ms`.
- `pg_stat_activity` shows far fewer active `paymentsvc` connections than the pool size —
  connections are checked out in the app but idle-in-transaction or stuck on a slow query.
- Postgres CPU, replication lag, and lock counts are normal.

## Likely causes

1. A slow or missing query plan (a dropped index, a bad migration) making every query hold
   its connection longer, so throughput no longer covers arrival rate.
2. A code path that opens a transaction and does slow non-DB work (an external HTTP call to
   `acquirer-gw`) while holding the connection.
3. Traffic spike beyond provisioned pool capacity.
4. Connection leak — a path that checks out a connection and never returns it.

## Diagnosis

1. `query_metrics` — `paymentsvc_db_pool_checked_out` vs `paymentsvc_db_pool_size`. If
   checked-out sits pinned at pool size, the pool is the bottleneck.
2. `query_metrics` — `paymentsvc_db_query_duration_seconds` p99. A step change points to
   cause (1); flat points to (2) or (3).
3. `get_recent_deploys` — a `paymentsvc` deploy or a migration in the hour before onset
   implicates (1) or (2).
4. `search_logs` — grep for `pool timeout` to confirm, and for `idle in transaction` to
   distinguish a leak (2/4) from pure saturation (3).
5. `get_service_dependencies` — check `acquirer-gw` latency; if elevated and the charge path
   holds a transaction across that call, that is cause (2).

## Remediation

- **[read-only] Confirm scope** — is it one pod or all? One pod suggests a leak; restart it.
- **[state-changing — needs approval] Roll back the implicated deploy** if step 3 found one.
- **[state-changing — needs approval] Scale out `paymentsvc`** (add pods) to add pool
  capacity as a stopgap for cause (3).
- **[state-changing — needs approval] Raise the per-pod pool size** only if Postgres has
  headroom (`max_connections` minus current usage); otherwise you move the exhaustion into
  the database.
- **[read-only] File a follow-up** to move the `acquirer-gw` call outside the DB transaction
  if step 5 confirmed cause (2).

## Escalation

If no deploy correlates and Postgres is healthy, page the `payments` service owner. If
`pg_stat_activity` shows long-running queries you cannot attribute, page the DBA on-call.

## Related

- `acquirer-gw-timeouts.md` — when the upstream call is the reason connections are held.
- `bad-migration-table-lock.md` — a migration is a common trigger for cause (1).
