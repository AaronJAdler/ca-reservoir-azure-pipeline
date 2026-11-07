# 4. Append-only runs, newest real value wins

Status: accepted (2026-11-07)

## Context

CDEC revises recent data: in 13 months of storage readings for 12 reservoirs (inspected 2026-11-07) there were 19 readings flagged `e` (estimated) and 2 flagged `r` (revised), and the newest day is often still `---` when it is first pulled. A pipeline that only pulls yesterday would keep the estimate forever.

## Decision

* Each run pulls a trailing window (default 30 days) and is stored as its own silver folder. Nothing is overwritten.
* `gold.reservoir_daily` ranks the copies of each station-day by `is_missing ASC, ingested_at DESC, run_id DESC` and keeps the first: the newest run that has a real value.
* A later `---` never erases an earlier value. If CDEC withdraws a value on purpose this keeps the old one; `gold.revisions` lists the station-day so it can be checked.
* Rerunning the same window is safe: the same values appear twice in silver and once in gold.

## Consequences

* Gold views scan every run, so cost grows with history (about 30 copies of each station-day after a month of daily runs). At this size it is still well under the 10 MB per-query minimum. Past that, a periodic compaction job would rewrite silver to one row per station-day.
* `ingested_at` is an ISO-8601 string, so it sorts correctly in both engines without timestamp type differences.
