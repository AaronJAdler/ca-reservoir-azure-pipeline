# 2. One SQL source, two engines

Status: accepted (2026-11-07)

## Context

Cloud-only logic is slow to test and easy to break. I want every rule (parsing, checks, dedup, gold) tested on every commit without an Azure subscription, and I don't want a Python copy of the logic that can drift from the SQL that really runs.

## Decision

Write the SQL once as Jinja templates (`src/resflow/sql/*.sql.j2`) in the subset of SQL that both DuckDB and T-SQL accept: CTEs, `CASE`, `TRY_CAST`, `CONCAT`, `SUBSTRING`, `ROW_NUMBER() OVER`, `COALESCE`. Where they differ, a macro renders the engine's form:

| Macro | DuckDB | Synapse serverless |
|---|---|---|
| `bronze()`, `staging()`, `silver()`, `reference()` | `read_csv` / `read_parquet` on local paths | `OPENROWSET(BULK …, DATA_SOURCE = 'lake')` |
| `days_between(a, b)` | `date_diff('day', a, b)` | `DATEDIFF(day, a, b)` |
| `add_days(x, n)` | `CAST(x + INTERVAL (n) DAY AS DATE)` | `DATEADD(day, n, x)` |
| `clean(col)` | `chr(13)` | `CHAR(13)` |
| run values | literals | Data Factory expressions such as `@{pipeline().RunId}` |

The Synapse rendering is committed under `infra/generated/` and embedded into the pipeline by Bicep `loadTextContent()`. CI fails if it is stale.

## Consequences

* 40 tests run the real SQL on real CDEC responses in about two seconds.
* CI also parses the Synapse rendering with sqlglot's T-SQL dialect. That catches syntax mistakes but **does not prove Synapse accepts the SQL**; only a run in Azure does. `OPENROWSET(BULK …)` is not understood by sqlglot, so it is swapped for a table name before parsing and its text is checked separately.
* Some differences can't be hidden. Example: with a 10-column row, DuckDB errors (the run fails as `F0_unreadable`) while Synapse with a 9-column `WITH` clause ignores the extra column, so the run fails a later rule instead. Both refuse to publish, through different rules.
