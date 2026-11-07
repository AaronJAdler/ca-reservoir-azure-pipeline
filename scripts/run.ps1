<#
.SYNOPSIS
  Start one pipeline run, wait for it, and save evidence of what happened.

.EXAMPLE
  ./scripts/run.ps1 -ResourceGroup rg-resflow-demo                     # trailing 30 days
  ./scripts/run.ps1 -ResourceGroup rg-resflow-demo -WindowStart 2025-10-01 -WindowEnd 2026-11-06
  ./scripts/run.ps1 -ResourceGroup rg-resflow-demo -Stations 'SHA,ORO'          # two reservoirs only

.DESCRIPTION
  Writes to evidence/<run id>/:
    pipeline-run.json   az datafactory pipeline-run show
    activity-runs.json  every activity in the run with its status and output
    checks.json         the RunChecks output (one row per rule)
    gold_*.csv          gold views queried after the run (only if it published)
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'rg-resflow-demo',
    [string]$WindowStart = '',
    [string]$WindowEnd = '',
    [int]$LookbackDays = 30,
    [string]$Stations = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$outputs = Get-Content evidence/deployment.json -Raw | ConvertFrom-Json
$adf = $outputs.factoryName.value
$pipeline = $outputs.pipelineName.value
$sql = $outputs.serverlessEndpoint.value
$db = $outputs.serverlessDatabase.value

$params = @{ windowStart = $WindowStart; windowEnd = $WindowEnd; lookbackDays = $LookbackDays }
if ($Stations) { $params.stations = $Stations }
$paramFile = New-TemporaryFile
$params | ConvertTo-Json | Set-Content $paramFile -Encoding utf8

$runId = az datafactory pipeline create-run --resource-group $ResourceGroup --factory-name $adf `
    --name $pipeline --parameters "@$paramFile" --query runId -o tsv
Remove-Item $paramFile
if ($LASTEXITCODE -ne 0 -or -not $runId) { throw 'create-run failed' }
Write-Host "Run $runId started"

$status = 'Queued'
while ($status -in 'Queued', 'InProgress', 'Canceling') {
    Start-Sleep -Seconds 15
    $status = az datafactory pipeline-run show --resource-group $ResourceGroup --factory-name $adf `
        --run-id $runId --query status -o tsv
    Write-Host "  $(Get-Date -Format HH:mm:ss) $status"
}

$dir = Join-Path evidence $runId
New-Item -ItemType Directory -Force $dir | Out-Null
az datafactory pipeline-run show --resource-group $ResourceGroup --factory-name $adf --run-id $runId -o json |
    Set-Content (Join-Path $dir 'pipeline-run.json') -Encoding utf8

$after = (Get-Date).ToUniversalTime().AddDays(-1).ToString('o')
$before = (Get-Date).ToUniversalTime().AddDays(1).ToString('o')
$activities = az datafactory activity-run query-by-pipeline-run --resource-group $ResourceGroup `
    --factory-name $adf --run-id $runId --last-updated-after $after --last-updated-before $before -o json
$activities | Set-Content (Join-Path $dir 'activity-runs.json') -Encoding utf8

$checks = ($activities | ConvertFrom-Json).value | Where-Object activityName -eq 'RunChecks'
if ($checks) {
    $checks.output.value | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $dir 'checks.json') -Encoding utf8
    Write-Host ''
    $checks.output.value | Format-Table rule_id, severity, failed | Out-String | Write-Host
}

if ($status -eq 'Succeeded') {
    foreach ($view in 'reservoir_latest', 'statewide_daily', 'revisions', 'quarantine') {
        $out = Join-Path $dir "gold_$view.csv"
        sqlcmd -S $sql -d $db --authentication-method ActiveDirectoryDefault -b -W -s ',' `
            -Q "SET NOCOUNT ON; SELECT * FROM gold.$view" -o $out
        if ($LASTEXITCODE -ne 0) { Write-Warning "query of gold.$view failed" }
    }
    Write-Host "Published. Evidence in $dir"
} else {
    Write-Host "Run ended $status. Nothing published. Evidence in $dir"
    exit 1
}
