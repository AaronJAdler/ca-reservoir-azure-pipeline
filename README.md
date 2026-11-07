# ca-reservoir-azure-pipeline

A batch pipeline on Azure for California reservoir storage. Azure Data Factory pulls daily storage for 12 major reservoirs from CDEC (the state's California Data Exchange Center), lands the raw response in ADLS Gen2, and Synapse serverless SQL parses it, checks it and serves it as gold views. A run that fails a fatal check publishes nothing.

The same SQL also runs locally on DuckDB, so every rule is tested on real CDEC responses on each commit without an Azure subscription.

* Architecture and diagrams: [docs/architecture.md](docs/architecture.md)
* Decisions: [docs/adr/](docs/adr/)

## What it shows

* **Data Factory orchestration with managed identities only.** HTTP to ADLS copy, a Synapse Script activity (CETAS), a Lookup for checks, Filter and IfCondition to gate publishing, Copy and Delete to publish. No keys: storage has shared-key access disabled, Synapse is Entra-only.
* **Write-audit-publish on a lake with no transactions.** Parse into `staging/`, check, and only then copy to `silver/`. A failed run leaves staging for inspection and gold unchanged ([ADR 0003](docs/adr/0003-write-audit-publish.md)).
* **Checks that catch what a successful copy hides.** An HTML error page with status 200, a changed header, a truncated response (fewer station-days than requested), duplicate keys, wrong units or an unknown station are fatal. Non-numeric and implausible values (over 120% of capacity) are quarantined row by row.
* **History that handles revisions.** Each run re-pulls a trailing 30-day window into its own append-only silver folder. Gold keeps the newest real value per station-day; a later `---` never erases an earlier reading; `gold.revisions` lists every disagreement ([ADR 0004](docs/adr/0004-append-only-history.md)).
* **Gaps stay visible.** Missing readings stay NULL. The statewide total is NULL on days a station didn't report, with the partial sum beside it ([ADR 0007](docs/adr/0007-reading-date-and-gaps.md)).
* **One SQL source for two engines.** Jinja templates in the SQL both DuckDB and T-SQL accept, with macros for the few differences. The Synapse rendering is committed and embedded in the pipeline by Bicep ([ADR 0002](docs/adr/0002-one-sql-source-two-engines.md)).
* **Infrastructure as code** in Bicep, plus PowerShell scripts to deploy, run with evidence capture, and tear down.

## The data

Source: CDEC CSV servlet, sensor 15 (reservoir storage, acre-feet), daily (`dur_code=D`), for Shasta, Trinity, Oroville, Bullards Bar, Folsom, Camanche, New Melones, Don Pedro, McClure, Millerton, San Luis and Pine Flat. Capacities in `reference/stations.csv` come from CDEC's Reservoir Conditions report, read on 2026-11-07.

What the real data looks like (13 months, 1 Oct 2025 to 6 Nov 2026, 12 stations, 4,824 rows, inspected in the browser on 2026-11-07 while designing the checks):

* 10 readings are `---` (no value), including the newest day for stations that report late.
* 19 readings are flagged `e` (estimated) and 2 are flagged `r` (revised).
* Lines end in CRLF.
* `OBS DATE` is usually the day after `DATE TIME`, but not always (Oroville, 21 July 2026), so the reading date is taken from `DATE TIME`.
* Asking for a station CDEC doesn't have returns status 200 with that station silently left out. Only the completeness check notices.
* Large real day-over-day jumps exist (Oroville gained 116,000 AF on 22 December 2025 during a storm), so there is no "big change" rejection rule.

Test fixtures are three real CDEC responses saved byte for byte. Their SHA-256 hashes were computed in the browser before saving, and a test checks them. Tests that need bad input change the real bytes inside the test, so each alteration is visible where it is used, and each is labeled "Generated".

## Verification

| Check | Where | Result |
|---|---|---|
| pytest: 40 tests (local lake on real fixtures, T-SQL parse, CDEC client) | locally, Linux, Python 3.13 | 40 passed |
| ruff check, ruff format --check, mypy --strict | locally | clean |
| `resflow render --check` (committed Synapse SQL is current) | locally | up to date |
| `bicep build` and `bicep lint` (v0.49.2) | locally | 0 errors, 0 warnings |
| Fixture SHA-256 matches the browser capture | locally (test) | match |
| Gold latest value for Oroville on 6 Nov 2026 equals CDEC's Reservoir Conditions report (1,452,167 AF) | locally (test) | match |
| GitHub Actions: quality, test, infra, powershell (PSScriptAnalyzer on Windows) | GitHub Actions | see the CI badge / Actions tab |
| **Deployment to Azure and a pipeline run** | **not yet run** | **pending: see below** |

What has **not** been verified: nothing in this repo has run in Azure yet. In particular, whether Synapse serverless accepts every statement (the parse check uses sqlglot, not Synapse), whether the factory's least-privilege database roles are enough for CETAS, and the exact cost. Those are confirmed only by `deploy.ps1` and `run.ps1`, and the evidence goes in `evidence/`.

## Run it locally (Windows, PowerShell)

```powershell
winget install astral-sh.uv
git clone https://github.com/AaronJAdler/ca-reservoir-azure-pipeline
cd ca-reservoir-azure-pipeline
uv sync
uv run pytest
# Real data from CDEC into a local lake (./lake), trailing 30 days:
uv run resflow run
uv run resflow gold reservoir_latest
uv run resflow gold statewide_daily
```

## Deploy, run, tear down (Azure)

Needs the Azure CLI, go-sqlcmd and uv.

```powershell
winget install Microsoft.AzureCLI
winget install sqlcmd
az login

./scripts/deploy.ps1 -ResourceGroup rg-resflow-demo -Location westus2

# One run of the trailing 30 days, then a 13-month backfill:
./scripts/run.ps1 -ResourceGroup rg-resflow-demo
./scripts/run.ps1 -ResourceGroup rg-resflow-demo -WindowStart 2025-10-01 -WindowEnd 2026-11-06

# Try a failure on purpose. ZZZ is not a CDEC station; CDEC answers 200 and leaves it out
# (tested against the real response), so F4_completeness fails and nothing is published.
./scripts/run.ps1 -ResourceGroup rg-resflow-demo -Stations 'SHA,ZZZ'
# Check evidence/<run id>/ for the pipeline run, activity runs, checks and gold CSVs.

./scripts/teardown.ps1 -ResourceGroup rg-resflow-demo
```

The schedule trigger (`tr_daily_1530_utc`) is deployed stopped. Nothing runs unless you start a run.

If `StageParse` fails with a permission error, the factory's database roles are not enough for CETAS on your workspace. Run `ALTER ROLE db_owner ADD MEMBER [<factory name>];` in the `reservoir` database and record it in [ADR 0005](docs/adr/0005-network-and-identity.md).

## Layout

```
src/resflow/sql/       shared SQL templates (stg_parsed, checks, gold_*)
src/resflow/sqlgen.py  macros for DuckDB and Synapse
src/resflow/lake.py    local lake: same steps as the pipeline, on DuckDB
src/resflow/synapse.py writes infra/generated/*.sql
infra/main.bicep       storage, Synapse workspace, Data Factory, role assignments
infra/adf.bicep        linked services, datasets, pipeline, trigger
infra/synapse/         one-time database setup (sqlcmd)
infra/generated/       Synapse SQL rendered from the templates (committed)
scripts/               deploy.ps1, run.ps1, teardown.ps1
reference/             station ids, names, capacities
tests/fixtures/        real CDEC responses and the RES report values
evidence/              outputs of real Azure runs
```
