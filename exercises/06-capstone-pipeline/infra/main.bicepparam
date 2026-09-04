using './main.bicep'

// ── Non-secret parameters ─────────────────────────────────────────────────────
// DO NOT put anthropicApiKey here — pass it at deploy time via CLI:
//   az deployment group create ... --parameters anthropicApiKey="sk-ant-..."

param environment = 'prod'
param location    = 'eastus2'
param appName     = 'mri-pipeline'

// imageTag is overridden by CI/CD per commit (CI_COMMIT_SHORT_SHA).
// Set to 'latest' here as a safe fallback for manual deploys.
param imageTag = 'latest'

// Optional — leave empty string if not using Anthropic workspace scoping
param anthropicWorkspaceId = ''
