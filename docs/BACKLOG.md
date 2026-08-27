# Backlog — deferred items

Things we've deliberately decided to do *later*, so they don't clog the current slice.

- **Keep-warm ping** — a ~3-line GitHub Action on a cron (every ~10 min during the day) that
  hits the deployed `/health` endpoint so the host doesn't idle the service to sleep
  (~1 min cold start otherwise). Add once deploy is live and the cold start is actually
  annoying.
