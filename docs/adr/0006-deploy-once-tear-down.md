# 6. Deploy once, keep evidence, tear down

Status: accepted (2026-11-07)

## Context

Synapse, Data Factory and storage cost little when idle, but a forgotten demo still accrues charges and keeps public endpoints open. Projects 2 and 3 in this portfolio are proven by CI only; this one should also have a record of a real cloud run.

## Decision

* `scripts/deploy.ps1` creates one tagged resource group, deploys Bicep, and sets up the serverless database.
* The schedule trigger is deployed **stopped**. Runs happen only through `scripts/run.ps1`.
* `run.ps1` saves the pipeline run, every activity run, the checks output and the gold views to `evidence/<run id>/`.
* `scripts/teardown.ps1` deletes the resource group and checks nothing tagged for the project remains.

## Expected cost (estimate, not measured)

For a deploy, a backfill run and a few daily runs: Data Factory copy activities bill per DIU-minute (two small copies per run), orchestration about $1 per 1,000 activity runs, serverless SQL at the 10 MB per-query minimum, and storage in cents. The whole exercise should cost well under $5. The real figure will be in Cost Management after teardown.
