<#
.SYNOPSIS
  Delete the resource group and everything in it, then confirm it is gone.
  Copy anything you want to keep out of evidence/ first; that folder is local
  and is not touched.
#>
[CmdletBinding()]
param([string]$ResourceGroup = 'rg-resflow-demo')

$ErrorActionPreference = 'Stop'

$exists = az group exists --name $ResourceGroup
if ($exists -ne 'true') { Write-Host "$ResourceGroup does not exist"; exit 0 }

Write-Host "Deleting $ResourceGroup (takes a few minutes)"
az group delete --name $ResourceGroup --yes
if ($LASTEXITCODE -ne 0) { throw 'az group delete failed' }

# Synapse creates a managed resource group of its own; it is removed with the
# workspace. Check nothing tagged for this project is left.
$left = az resource list --tag project=ca-reservoir-azure-pipeline --query '[].id' -o tsv
if ($left) { Write-Warning "Still present:`n$left" } else { Write-Host 'Nothing tagged project=ca-reservoir-azure-pipeline remains.' }
