// ─────────────────────────────────────────────────────────────────────────────
// Market Research Intelligence Pipeline — Azure Infrastructure
// Deploys: ACR · Key Vault · Storage (File Share) · Container Apps environment
//          · User-Assigned Managed Identity · Container App
// ─────────────────────────────────────────────────────────────────────────────

// ── Parameters ───────────────────────────────────────────────────────────────

@minLength(1)
@description('Short environment tag used in all resource names: dev | staging | prod')
param environment string = 'prod'

@description('Azure region for all resources')
param location string = resourceGroup().location

@minLength(1)
@description('Base name used to construct all resource names')
param appName string = 'mri-pipeline'

// Use the sentinel value 'bootstrap' for the very first deploy (before any
// Docker image has been pushed to ACR). CI/CD passes the real git-sha tag.
@description('Container image tag. Use "bootstrap" for the initial provisioning run.')
param imageTag string = 'bootstrap'

@secure()
@description('Anthropic API key — stored in Key Vault; NEVER hardcode here')
param anthropicApiKey string

@description('Anthropic workspace ID (optional)')
param anthropicWorkspaceId string = ''

// ── Variables ─────────────────────────────────────────────────────────────────

var prefix = '${appName}-${environment}'

// ACR names: alphanumeric only, 5–50 chars
var acrName = replace('acr${replace(prefix, '-', '')}', '-', '')

// Key Vault names: 3–24 chars, alphanumeric + hyphens
var kvName = take('kv-${prefix}', 24)

// Storage account names: 3–24 chars, lowercase alphanumeric only
var storageAccountName = take(replace('st${replace(prefix, '-', '')}', '-', ''), 24)

var fileShareName         = 'pipeline-data'
var containerAppEnvName   = 'cae-${prefix}'
var containerAppName      = 'ca-${prefix}'
var managedIdentityName   = 'id-${prefix}'
// 'bootstrap' sentinel → use a public placeholder so the Container App deploys
// successfully before any image is pushed to ACR. Step 5 of azure_infra.sh
// (and every subsequent CI/CD run) updates the image via 'az containerapp update'.
var imageName = imageTag == 'bootstrap'
  ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
  : '${acrName}.azurecr.io/${appName}:${imageTag}'

// ── 1. Azure Container Registry ──────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    // Basic is sufficient: 10 GB storage, managed-identity pull, no geo-replication
    name: 'Basic'
  }
  properties: {
    // Admin user disabled — Container App pulls via managed identity instead
    adminUserEnabled: false
  }
}

// ── 2. Key Vault ─────────────────────────────────────────────────────────────

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    // RBAC model (not legacy access policies) — works with managed identity
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForTemplateDeployment: false
  }
}

resource kvSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'anthropic-api-key'
  properties: {
    value: anthropicApiKey
  }
}

// ── 3. Storage Account + File Share ──────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    // LRS is fine — pipeline data is regenerable from reruns
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: fileShareName
  properties: {
    // 5 GB is massive headroom: JSONL lines ~200 B each, reports ~3 KB each
    shareQuota: 5
    enabledProtocols: 'SMB'
  }
}

// ── 4. User-Assigned Managed Identity ────────────────────────────────────────

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

// AcrPull: lets the Container App pull images without stored credentials
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, managedIdentity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User: lets the Container App read secrets from Key Vault
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, managedIdentity.id, kvSecretsUserRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── 5. Container Apps Environment ────────────────────────────────────────────

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    // No VNet needed — only outbound call is api.anthropic.com (public internet)
  }
}

// Attach the Azure File Share to the environment so Container Apps can mount it
resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: containerAppEnv
  name: 'pipeline-data-storage'
  properties: {
    azureFile: {
      accountName: storageAccount.name
      accountKey: storageAccount.listKeys().keys[0].value
      shareName: fileShareName
      accessMode: 'ReadWrite'
    }
  }
}

// ── 6. Container App ─────────────────────────────────────────────────────────

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      // Single active revision — suits the single-instance constraint
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        // HTTP/1.1 — required for reliable SSE across all browsers.
        // HTTP/2 SSE has spotty browser support.
        transport: 'http'
      }
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: managedIdentity.id
        }
      ]
      // Key Vault secret reference — API key never appears in logs or env inspection
      secrets: [
        {
          name: 'anthropic-api-key'
          keyVaultUrl: kvSecret.properties.secretUri
          identity: managedIdentity.id
        }
      ]
    }
    template: {
      volumes: [
        {
          name: 'pipeline-data'
          storageType: 'AzureFile'
          storageName: 'pipeline-data-storage'
        }
      ]
      containers: [
        {
          name: containerAppName
          image: imageName
          resources: {
            // 1 vCPU: pipeline threads are I/O-bound (Anthropic API), not CPU-bound
            cpu: json('1.0')
            // 2 GiB: headroom for 4 concurrent pipeline runs + Python interpreter
            memory: '2Gi'
          }
          env: [
            {
              name: 'ANTHROPIC_API_KEY'
              secretRef: 'anthropic-api-key'
            }
            {
              name: 'ANTHROPIC_WORKSPACE_ID'
              value: anthropicWorkspaceId
            }
            {
              // All file I/O (JSONL log + report .md files) goes to the mounted share
              name: 'DATA_DIR'
              value: '/data'
            }
            {
              name: 'PIPELINE_LOG_FILE'
              value: '/data/pipeline_runs.jsonl'
            }
          ]
          volumeMounts: [
            {
              volumeName: 'pipeline-data'
              mountPath: '/data'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/v1/runs'
                port: 8000
              }
              initialDelaySeconds: 15
              periodSeconds: 30
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        // CRITICAL: both limits must be 1.
        // minReplicas=1 → never scale to zero (in-memory RunRegistry would be wiped).
        // maxReplicas=1 → never scale out (threading.Event for HITL is per-process;
        //                 approve on instance A cannot unblock instance B).
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [envStorage, acrPullRole, kvSecretsUserRole]
}

// ── Outputs ──────────────────────────────────────────────────────────────────

@description('Fully-qualified domain name of the Container App — use as the app URL')
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn

@description('ACR login server (e.g. acrmripipelineprod.azurecr.io)')
output acrLoginServer string = acr.properties.loginServer

@description('Container App name (for az containerapp update commands)')
output containerAppName string = containerApp.name

@description('Resource group name')
output resourceGroupName string = resourceGroup().name
