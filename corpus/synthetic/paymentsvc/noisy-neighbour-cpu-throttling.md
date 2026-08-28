---
service: paymentsvc
failure_mode: noisy-neighbour-cpu-throttling
severity: SEV2
alert: PaymentsvcCpuThrottlingHigh
---

# paymentsvc — Noisy-neighbour CPU throttling

## Summary

`paymentsvc` pods share nodes with other workloads. When a co-located pod (or `paymentsvc`
itself) hits its CPU limit, the kernel CFS quota throttles it — the container is runnable but
not scheduled. Latency rises in bursts with no change in traffic, no errors from
dependencies, and no deploy. The give-away is high `container_cpu_cfs_throttled_periods`
with only moderate CPU *usage*.

## Alert

`PaymentsvcCpuThrottlingHigh` — `rate(container_cpu_cfs_throttled_periods_total)` /
`rate(container_cpu_cfs_periods_total)` for `paymentsvc` exceeds 25% over 10m.

## Symptoms

- Latency p95/p99 rises and is **bursty** (sawtooth), tracking the 100ms CFS period.
- CPU *usage* looks only moderate (e.g. 60–70% of limit) yet throttling is high — because
  the limit is consumed in bursts.
- No dependency errors, no `acquirer-gw` slowdown, no `paymentsvc` deploy.
- May correlate with a spike in *another* pod on the same node(s), or a node-level CPU
  pressure metric.

## Likely causes

1. CPU limits set too close to (or below) real burst demand — throttling under normal load.
2. A genuine noisy neighbour: another pod on the same node saturating node CPU.
3. A traffic pattern shift (bigger payloads, more crypto work per request) pushing
   `paymentsvc` into its own limit.
4. Node under-provisioned / autoscaler not adding capacity.

## Diagnosis

1. `query_metrics` — throttled-periods ratio and `container_cpu_usage_seconds` vs the CPU
   limit for `paymentsvc`. High ratio + usage below limit = throttling is the cause.
2. `query_metrics` — node-level CPU for the nodes running `paymentsvc` pods; and top
   CPU consumers on those nodes for cause (2).
3. `get_recent_deploys` — confirm nothing shipped for `paymentsvc`; check whether a
   *neighbour* workload deployed or scaled up.
4. `query_metrics` — request rate and payload-size metrics to rule cause (3) in or out.
5. `search_logs` — expect **no** relevant application errors; their absence supports
   throttling over a code fault.

## Remediation

- **[state-changing — needs approval] Raise the `paymentsvc` CPU limit** (or remove it and
  rely on requests + node headroom) for cause (1) or (3).
- **[state-changing — needs approval] Scale out `paymentsvc`** so load spreads across more
  pods/nodes, reducing per-pod burst.
- **[state-changing — needs approval] Cordon/drain or reschedule** to move `paymentsvc` off
  the contended node, or evict the noisy neighbour, for cause (2). Coordinate with the
  neighbour's owner.
- **[read-only] File a follow-up** to set anti-affinity so `paymentsvc` does not co-locate
  with known CPU-heavy batch workloads.

## Escalation

If the noisy neighbour is another team's workload, page that team. If node capacity is the
issue and the cluster autoscaler is not responding, page the platform/infra on-call.

## Related

- `redis-eviction-idempotency.md` — CPU throttling on the Redis host presents as Redis
  timeouts; check which host is actually throttled.
- `db-connection-pool-exhaustion.md` — throttled request handlers hold DB connections
  longer, so pool metrics may also look stressed.
