# Evidence from Azure runs

Empty until the pipeline has been deployed and run. `scripts/deploy.ps1` writes `deployment.json` (resource names, no secrets). Each `scripts/run.ps1` writes a folder named after the Data Factory run id:

* `pipeline-run.json`: status, start and end time, parameters
* `activity-runs.json`: every activity with its status, duration and output
* `checks.json`: the RunChecks rows
* `gold_*.csv`: gold views queried right after a published run

Commit these after a run, and update the verification table in the main README with what they show.
