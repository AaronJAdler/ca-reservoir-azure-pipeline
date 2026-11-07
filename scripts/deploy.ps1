<#
.SYNOPSIS
  Create the resource group, deploy the Bicep template, and set up the
  Synapse serverless database. Safe to rerun.

.DESCRIPTION
  Needs: Azure CLI (az login done), sqlcmd (go-sqlcmd: winget install sqlcmd),
  and uv. Run from the repo root in PowerShell 7:

    ./scripts/deploy.ps1 -ResourceGroup rg-resflow-demo -Location westus2

  Writes the deployment outputs to evidence/deployment.json for run.ps1.
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'rg-resflow-demo',
    [string]$Location = 'westus2',
    [string]$Prefix = 'resflow',
    [string]$ClientIp = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Invoke-Checked {
    param([scriptblock]$Command, [string]$What)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

foreach ($tool in 'az', 'sqlcmd', 'uv') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH" }
}

Write-Host '== Checking generated Synapse SQL is current'
Invoke-Checked { uv run resflow render --check } 'resflow render --check'

Write-Host '== Signed-in user'
$me = az ad signed-in-user show --query '{id:id, upn:userPrincipalName}' -o json | ConvertFrom-Json
if (-not $me.id) { throw 'az ad signed-in-user show returned nothing; run az login' }
Write-Host "   $($me.upn)"

if (-not $ClientIp) {
    $ClientIp = (Invoke-RestMethod -Uri 'https://api.ipify.org').Trim()
}
Write-Host "   client IP for the Synapse firewall: $ClientIp"

Invoke-Checked { az extension add --name datafactory --upgrade --only-show-errors } 'az extension add datafactory'

Write-Host "== Resource group $ResourceGroup ($Location)"
Invoke-Checked {
    az group create --name $ResourceGroup --location $Location `
        --tags project=ca-reservoir-azure-pipeline purpose=portfolio-demo -o none
} 'az group create'

Write-Host '== Deploying infra/main.bicep (several minutes; Synapse is the slow part)'
$outputs = az deployment group create `
    --resource-group $ResourceGroup `
    --name main `
    --template-file infra/main.bicep `
    --parameters prefix=$Prefix deployerObjectId=$($me.id) deployerUpn=$($me.upn) clientIpAddress=$ClientIp `
    --query properties.outputs -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $outputs) { throw 'az deployment group create failed' }

$sa = $outputs.storageAccountName.value
$adf = $outputs.factoryName.value
$sql = $outputs.serverlessEndpoint.value
$db = $outputs.serverlessDatabase.value

New-Item -ItemType Directory -Force evidence | Out-Null
$outputs | ConvertTo-Json -Depth 5 | Set-Content evidence/deployment.json -Encoding utf8

Write-Host "== Uploading reference/stations.csv to $sa/lake (retries while role assignment propagates)"
$uploaded = $false
for ($i = 1; $i -le 10 -and -not $uploaded; $i++) {
    az storage blob upload --account-name $sa --container-name lake `
        --name reference/stations.csv --file reference/stations.csv `
        --auth-mode login --overwrite --only-show-errors -o none
    if ($LASTEXITCODE -eq 0) { $uploaded = $true } else { Start-Sleep -Seconds 30 }
}
if (-not $uploaded) { throw 'Could not upload reference/stations.csv' }

Write-Host "== Setting up serverless database $db on $sql"
$auth = @('--authentication-method', 'ActiveDirectoryDefault')
Invoke-Checked { sqlcmd -S $sql -d master @auth -b -i infra/synapse/setup_master.sql } 'setup_master.sql'

$bytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$masterKey = 'Mk1!' + [Convert]::ToBase64String($bytes)
Invoke-Checked {
    sqlcmd -S $sql -d $db @auth -b -i infra/synapse/setup_db.sql `
        -v STORAGE_ACCOUNT=$sa ADF_NAME=$adf MASTER_KEY_PASSWORD=$masterKey
} 'setup_db.sql'
Invoke-Checked { sqlcmd -S $sql -d $db @auth -b -i infra/generated/gold_views.sql } 'gold_views.sql'

Write-Host ''
Write-Host "Deployed. Next: ./scripts/run.ps1 -ResourceGroup $ResourceGroup"
Write-Host "Trigger $($outputs.triggerName.value) is deployed stopped; nothing runs on its own."
