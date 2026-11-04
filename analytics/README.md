# Isolated dbt analytics

Experimental phase 2: eight models (one ephemeral), seven stored tables and
six outputs equivalent to the original SQL on deterministic synthetic snapshots.
The original pipeline remains the operational entry point. Version is 1.0.0.

Run from the repository root with Python 3.12:

```shell
uv sync --frozen --group dbt
uv run --frozen --group dbt python -m service_analytics.dbt_poc prepare
uv run --frozen --group dbt dbt build --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
uv run --frozen --group dbt python -m service_analytics.dbt_poc verify
uv run --frozen --group dbt pytest
```

Preparation refuses existing files. On subsequent runs reuse the known database
and omit prepare. Sources/metadata stay in main and all dbt tables stay in
`dbt_staging`. The database is `analytics/sandbox/service_requests_poc.duckdb`;
never use an operational database. RAW is latest-observed state, not a history of
versions. run_id and snapshot_id must both be explicit in every dbt build.

The CLI verifies all six outputs, not only staging. Generated databases, target,
logs and packages remain ignored. Full commands, model mapping, other local paths,
edge scenarios and documentation/lineage instructions are in the
[integration guide](../docs/migration/dbt_integration.md).

See [ADR-002](../docs/decisions/ADR-002-dbt-model-migration.md) and
[actual validation results](../docs/validation/dbt_full_parity.md).
