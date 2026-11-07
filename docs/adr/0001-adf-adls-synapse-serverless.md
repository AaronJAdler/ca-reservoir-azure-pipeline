# 1. Data Factory, ADLS Gen2 and Synapse serverless

Status: accepted (2026-11-07)

## Context

The portfolio already has an Azure Databricks lakehouse (card-payments-lakehouse). This project should show the other common Azure data stack: Data Factory for orchestration and movement, ADLS Gen2 as the lake, and SQL over files. The data is small (12 reservoirs × 31 days ≈ 372 rows a run), so a Spark cluster or a dedicated SQL pool would be paying for capacity that sits idle.

## Decision

* **Data Factory** orchestrates and copies (HTTP to ADLS, staging to silver).
* **ADLS Gen2** (hierarchical namespace) holds bronze, staging, silver and reference data.
* **Synapse serverless SQL** does the transformation (CETAS) and serves gold as views. It bills per data scanned (about $5 per TB, 10 MB minimum per query), with nothing to keep running.
* Mapping Data Flows were not used: they start a Spark cluster per run, and their logic lives in JSON that can't be tested locally.

## Consequences

* Transform logic is SQL, testable locally (ADR 0002).
* Serverless SQL cannot update files in place, which shapes the publish and history design (ADRs 0003, 0004).
* Microsoft now steers new work toward Fabric. ADF and Synapse are still what many Azure shops run, and the patterns (managed identities, WAP, append-only history) carry over to Fabric Data Factory and a Fabric lakehouse.
