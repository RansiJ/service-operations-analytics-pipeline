# Experimental dbt integration - phases 0 to 2

The original pipeline still owns extraction, RAW loading, transactions, ETL/ELT
comparison, exports and the dashboard. dbt runs independently on deterministic
synthetic DuckDB snapshots. Version remains 1.0.0; this branch is not deployed.

## Model map and scope

| Original | dbt model |
|---|---|
| normalized CTE | `stg_service_requests` |
| classified CTE | `int_service_requests_classified` (ephemeral) |
| requests / flagged CTE | `fct_service_requests` |
| metrics | `mart_overall_metrics` |
| daily_metrics | `mart_daily_metrics` |
| category_metrics | `mart_category_metrics` |
| agency_metrics | `mart_agency_metrics` |
| quality_issues | `mart_quality_issues` |

Staging preserves run/snapshot/last-observation provenance. The fact matches the
original 16-column schema, including overlapping flags and eligible durations.
Five marts preserve the original grains and denominators. Seven tables are stored
in `dbt_staging`; the classification CTE does not add a stored table. See
[ADR-002](../decisions/ADR-002-dbt-model-migration.md) for rules and tradeoffs.

## Reproduce from the repository root

Use Python 3.12 and uv. Core **1.12.6**, adapter **1.11.1** and DuckDB **1.5.6**
remain fixed by the existing optional group/lock; no new dependencies were added.
The default environment remains usable without dbt.

```shell
uv sync --frozen --group dbt
uv run --frozen --group dbt python -m service_analytics.dbt_poc prepare
uv run --frozen --group dbt dbt debug --project-dir analytics --profiles-dir analytics
uv run --frozen --group dbt dbt build --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
uv run --frozen --group dbt python -m service_analytics.dbt_poc verify
uv run --frozen --group dbt pytest
uv run --frozen --group dbt dbt docs generate --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
```

The preparer creates a temporary database, closes it, then copies exclusively to
`analytics/sandbox/service_requests_poc.duckdb`. It never opens/copies an operational
DB or overwrites a destination. Reuse the known snapshot and omit `prepare` on
later runs. Both dbt variables are mandatory. Keep `--group dbt` on experimental
uv invocations; a normal uv sync can remove optional packages.

`dbt run` followed by `dbt test` is equivalent to the model/test steps in build.
`dbt docs serve --project-dir analytics --profiles-dir analytics --port 8080`
can display the generated catalog/lineage locally; stop with Ctrl+C. `analytics/`
is checkout-based and not included in the Python wheel. target/logs are ignored.

## Extended deterministic scenarios

Preparation supports `small` (phase-1 fixture), `edge` (12 days, bands and weekly
threshold), `empty` (three empty days), and `zero-baseline` (seven zero days before
one arrival). Every scenario uses `poc-selected`; non-small snapshot IDs are
`poc-edge-v2`, `poc-empty-v2`, and `poc-zero-baseline-v2`. The returned IDs, not a
latest-run heuristic, define the explicit dbt invocation.

For example, in PowerShell with a fresh filename:

```powershell
$env:DBT_POC_DATABASE = 'analytics/sandbox/phase2_edge_poc.duckdb'
uv run --frozen --group dbt python -m service_analytics.dbt_poc prepare --scenario edge --database $env:DBT_POC_DATABASE
uv run --frozen --group dbt dbt build --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-edge-v2}'
uv run --frozen --group dbt python -m service_analytics.dbt_poc verify --database $env:DBT_POC_DATABASE --snapshot-id poc-edge-v2
Remove-Item Env:DBT_POC_DATABASE
```

For Bash, use `export DBT_POC_DATABASE=analytics/sandbox/phase2_edge_poc.duckdb`,
pass `--database "$DBT_POC_DATABASE"`, and `unset DBT_POC_DATABASE` afterwards.
Paths are relative to the repository root in the installed adapter. Do not point
this profile at a real database. The parsing guard rejects other filename suffixes
before a build creates schemas; the run hook validates identity, successful audit,
loaded membership and complete RAW/membership/audit fingerprints.

## Parity and correction of phase-1 gaps

The `verify` CLI now compares **all six** historical outputs: ordered column names
and types, then unordered row multisets in both directions with EXCEPT ALL. NULLs,
timestamps and ordered flag lists participate. Exact float equality is intentional:
the same pinned DuckDB evaluates the same expressions. No tolerance hides differences.
It also checks staging provenance and fingerprints of all ten original POC tables.
The phase-1 `verify_database()` Python staging API remains compatible; the new
`verify_full_parity()` is used by the CLI and full tests.

The original phase-1 fixture remains available. Additional scenarios cover all five
open labels, unknown status, malformed dates, rejected IDs, duplicate last-payload
UPSERT, whitespace, eligible-but-flagged requests, zero hours, exact duration bands,
empty groups, null percentage/median, zero days and seven-day baseline boundaries.
Deliberately corrupted final tables must fail parity despite equal row counts.

[Executed results](../validation/dbt_full_parity.md) distinguish current synthetic
validation from the historical 78,466-row live run. No NYC API extraction occurred.
[ADR-001](../decisions/ADR-001-dbt-integration.md) and the
[baseline audit](dbt_baseline.md) preserve the initial rationale. Phase 1 was
recorded independently in local commit `18f229a` before phase-2 edits.

## Phase 3 remains pending

Design writer coordination, snapshot/version policy, transaction and filesystem
recovery, export compatibility and operational cutover before calling dbt from the
pipeline. Validate Linux alongside Windows before changing CI; WSL is unavailable
and Docker is absent in this environment. No existing workflow was modified.
The original SQL remains an independent reference until a reviewed cutover.
