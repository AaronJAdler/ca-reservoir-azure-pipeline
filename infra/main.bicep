// California reservoir storage pipeline: ADLS Gen2 + Data Factory + Synapse serverless.
// Deployed by scripts/deploy.ps1 into its own resource group and removed by
// scripts/teardown.ps1. Nothing here runs on a schedule until the trigger is
// started by hand.

targetScope = 'resourceGroup'

@description('Azure region for every resource.')
param location string = resourceGroup().location

@description('Short lowercase prefix for resource names (3-10 letters or digits).')
@minLength(3)
@maxLength(10)
param prefix string = 'resflow'

@description('Object id of the person deploying. Becomes Synapse admin and gets data access to the lake.')
param deployerObjectId string

@description('User principal name of the person deploying, for the Synapse SQL Entra admin.')
param deployerUpn string

@description('Public IP allowed through the Synapse firewall, so the deploy script can run sqlcmd.')
param clientIpAddress string

@description('CDEC station ids the pipeline pulls. Must all be in reference/stations.csv.')
param stations string = 'SHA,CLE,ORO,BUL,FOL,CMN,NML,DNP,EXC,MIL,SNL,PNF'

@description('Never used: Entra-only auth is enforced. ARM still expects a SQL admin password on create.')
@secure()
param sqlAdminPassword string = newGuid()

var suffix = uniqueString(resourceGroup().id)
var storageName = take('${prefix}lake${suffix}', 24)
var factoryName = '${prefix}-adf-${suffix}'
var workspaceName = take('${prefix}-syn-${suffix}', 50)
var serverlessEndpoint = '${workspaceName}-ondemand.sql.azuresynapse.net'
var serverlessDatabase = 'reservoir'
var tags = {
  project: 'ca-reservoir-azure-pipeline'
  purpose: 'portfolio-demo'
}

// Storage Blob Data Contributor
var blobDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

// ---------------------------------------------------------------- Storage

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    // Public endpoint with Entra-only auth; see docs/adr/0005-network-and-identity.md.
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource lakeContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'lake'
}

resource synapseContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'synapse'
}

// ---------------------------------------------------------------- Synapse (serverless SQL only)

resource workspace 'Microsoft.Synapse/workspaces@2021-06-01' = {
  name: workspaceName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    defaultDataLakeStorage: {
      accountUrl: storage.properties.primaryEndpoints.dfs
      filesystem: synapseContainer.name
      resourceId: storage.id
      createManagedPrivateEndpoint: false
    }
    azureADOnlyAuthentication: true
    sqlAdministratorLogin: 'sqladminuser'
    sqlAdministratorLoginPassword: sqlAdminPassword
    publicNetworkAccess: 'Enabled'
    cspWorkspaceAdminProperties: {
      initialWorkspaceAdminObjectId: deployerObjectId
    }
  }
}

resource allowAzure 'Microsoft.Synapse/workspaces/firewallRules@2021-06-01' = {
  parent: workspace
  // Lets Data Factory's Azure integration runtime reach the serverless endpoint.
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource allowClient 'Microsoft.Synapse/workspaces/firewallRules@2021-06-01' = {
  parent: workspace
  name: 'DeployerClientIp'
  properties: {
    startIpAddress: clientIpAddress
    endIpAddress: clientIpAddress
  }
}

resource sqlEntraAdmin 'Microsoft.Synapse/workspaces/administrators@2021-06-01' = {
  parent: workspace
  name: 'activeDirectory'
  properties: {
    administratorType: 'ActiveDirectory'
    login: deployerUpn
    sid: deployerObjectId
    tenantId: subscription().tenantId
  }
}

// ---------------------------------------------------------------- Data Factory

resource factory 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: factoryName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// ---------------------------------------------------------------- Role assignments

resource factoryLakeAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, factory.id, blobDataContributor)
  properties: {
    roleDefinitionId: blobDataContributor
    principalId: factory.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workspaceLakeAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, workspace.id, blobDataContributor)
  properties: {
    roleDefinitionId: blobDataContributor
    principalId: workspace.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerLakeAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, deployerObjectId, blobDataContributor)
  properties: {
    roleDefinitionId: blobDataContributor
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// ---------------------------------------------------------------- Pipeline

module pipeline 'adf.bicep' = {
  name: 'adf-pipeline'
  params: {
    factoryName: factory.name
    lakeDfsUrl: storage.properties.primaryEndpoints.dfs
    serverlessEndpoint: serverlessEndpoint
    serverlessDatabase: serverlessDatabase
    stations: stations
  }
}

output resourceGroupName string = resourceGroup().name
output storageAccountName string = storage.name
output factoryName string = factory.name
output workspaceName string = workspace.name
output serverlessEndpoint string = serverlessEndpoint
output serverlessDatabase string = serverlessDatabase
output pipelineName string = pipeline.outputs.pipelineName
output triggerName string = pipeline.outputs.triggerName
