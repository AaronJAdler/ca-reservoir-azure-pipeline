# 3. Write-audit-publish with CETAS staging

Status: accepted (2026-11-07)

## Context

A bad response must never reach gold. CDEC can return a short file, a changed header, or an error page with status 200; the Copy activity succeeds in all those cases. Serverless SQL has no transactions over files, and CETAS cannot write into a folder that already has files.

## Decision

1. Copy the raw response to `bronze/…/run_id=<run>/cdec.csv`.
2. CETAS writes every parsed row, header and rejects included, to `staging/…/run_id=<run>/`. Each row has a `reject_reason` (NULL when good).
3. A Lookup runs the checks query over staging. A Filter keeps fatal rules that failed.
4. If any did, a Fail activity ends the run: nothing reaches silver, and staging stays for inspection. Otherwise a Copy moves staging to `silver/…/run_id=<run>/` and a Delete removes staging.

Gold views read only `silver/`.

## Consequences

* Publishing is a folder copy, not atomic. If PublishSilver fails partway, silver can hold a partial run folder. The Copy is retried from the same staging files, so a successful retry completes it; if every retry fails, gold would read the partial folder. A stricter version would write a `_SUCCESS` marker last and have gold views read only marked folders. That is not built here and is a known gap.
* Row-level problems (a non-number, a value above 120% of capacity) do not stop the run; those rows stay in silver with a `reject_reason` and appear in `gold.quarantine` only.
* The Script and Lookup activities are not retried, because a retried CETAS would find its own files and fail.
