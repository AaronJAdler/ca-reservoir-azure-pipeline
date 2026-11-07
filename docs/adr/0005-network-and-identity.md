# 5. Managed identities, Entra-only, public endpoints

Status: accepted (2026-11-07)

## Context

The demo should hold no secrets and still be cheap to stand up. Private endpoints and a managed virtual network add cost and setup time, and Synapse's managed VNet can only be chosen when the workspace is created.

## Decision

* Storage: shared-key access disabled, no public blob access, TLS 1.2. Access only through Entra RBAC (Storage Blob Data Contributor for the factory, the Synapse workspace and the deployer).
* Synapse: Entra-only authentication. The deployer is Synapse admin and SQL Entra admin. The factory's identity is a contained database user with `db_ddladmin`, `db_datareader`, bulk-operations and credential use (not `db_owner`).
* Serverless SQL reaches storage through a database scoped credential `WITH IDENTITY = 'Managed Identity'` (the workspace identity).
* Network: storage and Synapse keep public endpoints. The Synapse firewall allows Azure services (needed for Data Factory's Azure integration runtime) and the deployer's IP.

## Why this matters now

Microsoft announced the end of the "trusted Microsoft services" firewall exception for Synapse managed-identity access to storage (first set for 1 August 2026, now moved to 1 June 2027 with an opt-in setting). This design does not depend on that exception because the storage account has no firewall. A production version would instead create the workspace with a managed VNet, add managed private endpoints to storage, and turn the storage firewall on.

## Consequences

* No keys, connection strings or passwords exist in the repo, the pipeline, or Key Vault.
* The endpoints are reachable from the internet, protected by Entra auth only. Acceptable for a short-lived demo; not for real data.
