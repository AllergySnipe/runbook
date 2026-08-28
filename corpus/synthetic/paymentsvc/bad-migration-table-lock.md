---
service: paymentsvc
failure_mode: bad-migration-table-lock
severity: SEV1
alert: PaymentsvcAvailabilityLow
---

# paymentsvc — Bad migration locking a table after a deploy

## Summary

A schema migration shipped with a `paymentsvc` deploy takes a strong lock on a hot table
(`charges`) — an `ALTER TABLE` that rewrites it, an index build without `CONCURRENTLY`, or a
migration that blocks behind a long-running transaction. Every query touching that table
queues behind the lock. `paymentsvc` availability collapses within minutes of the deploy.

## Alert

`PaymentsvcAvailabilityLow` — success rate on `POST /charges` over 5m drops below 95%,
**within ~15 minutes of a deploy**.

## Symptoms

- Sharp onset closely following a deploy (check the timestamps).
- Nearly all requests slow or failing, not a subset.
- Logs: `canceling statement due to lock timeout` or `deadlock detected`, or requests just
  hanging until the app-level timeout.
- Postgres: a blocking session holding `AccessExclusiveLock` (or `ShareLock`) on `charges`;
  a long `pg_blocking_pids()` chain; `wait_event_type = Lock` on many backends.
- Database CPU may be low — everything is *waiting*, not working.

## Likely causes

1. `ALTER TABLE charges ...` that rewrites the table or adds a `NOT NULL` column with a
   default on an old Postgres, holding `AccessExclusiveLock` for the rewrite.
2. `CREATE INDEX` without `CONCURRENTLY`, holding a write lock for the whole build.
3. The migration itself is blocked behind a pre-existing long transaction, and in turn
   blocks every newcomer (lock queue pile-up).
4. A migration that runs a long backfill `UPDATE` in one transaction.

## Diagnosis

1. `get_recent_deploys` — identify the deploy and whether it included a migration. This is
   the first and highest-signal step given the alert's timing clause.
2. `search_logs` — grep for `lock timeout`, `deadlock`, `AccessExclusiveLock`,
   and the migration runner's output.
3. `query_metrics` — `paymentsvc_db_query_duration_seconds` (spiking), Postgres
   `pg_locks` waiters, DB CPU (often flat/low).
4. **[read-only]** In Postgres, inspect `pg_stat_activity` + `pg_blocking_pids()` to find
   the head-of-line blocker and what statement it is running.

## Remediation

- **[state-changing — needs approval] Terminate the blocking migration session**
  (`pg_terminate_backend(<pid>)`) — this is the fastest path to recovery. The migration is
  half-applied; note that for cleanup.
- **[state-changing — needs approval] Roll back the deploy** to the previous `paymentsvc`
  version once the lock is released.
- **[read-only] Verify schema state** — is the migration partially applied? Reconcile
  `schema_migrations` with the actual schema before re-attempting.
- **[state-changing — needs approval] Re-issue the migration safely** off the incident:
  `CREATE INDEX CONCURRENTLY`, split `ALTER`s, batch backfills, set a short `lock_timeout`
  so it fails fast instead of queuing traffic behind it.

## Escalation

Page the DBA on-call and the `payments` service owner. If terminating the backend does not
release the pile-up within a couple of minutes, escalate to the incident commander — this is
a full outage.

## Related

- `db-connection-pool-exhaustion.md` — the lock pile-up drains the connection pool as a
  secondary symptom; fix the lock, not the pool.
