# dbt experimental

Sólo fase 1: un staging de solicitudes, sin migrar métricas, calidad ni operación.
El proyecto sigue en 1.0.0. Ejecutar desde la **raíz del repositorio**, con Python 3.12.

```shell
uv sync --frozen --group dbt
uv run --frozen --group dbt python -m service_analytics.dbt_poc prepare
uv run --frozen --group dbt dbt debug --project-dir analytics --profiles-dir analytics
uv run --frozen --group dbt dbt run --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
uv run --frozen --group dbt dbt test --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
uv run --frozen --group dbt python -m service_analytics.dbt_poc verify
uv run --frozen --group dbt dbt docs generate --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
```

El preparador crea `analytics/sandbox/service_requests_poc.duckdb`, con siete
solicitudes seleccionadas y una fila RAW adicional de otra cohorte. Nunca llama
al API ni abre la base operacional. **No sobrescribe archivos**: en ejecuciones
posteriores reutilizar la base preparada y comenzar en `dbt debug`. Para una base
nueva usar `--database` y el mismo `DBT_POC_DATABASE`, siempre terminado en
`_poc.duckdb`. Los detalles PowerShell/Bash están en la guía de integración.

Sólo se materializa `dbt_staging.stg_service_requests`. Las fuentes operativas son
`main.raw_requests`, `main.run_members` y `main.pipeline_runs`; el metadato auxiliar
`main.dbt_poc_snapshot` existe exclusivamente en la POC. run_id e snapshot_id son
obligatorios y las huellas deben concordar. Un run_id no reconstruye payloads
históricos. Mantener todas las conexiones Python cerradas antes de invocar dbt.

Tests completos: `uv run --frozen --group dbt pytest`. Tests originales sin dbt:
`uv run --frozen pytest tests/test_extract.py tests/test_models.py`.
El nuevo test de subprocess dbt se omite explícitamente si no está instalado.

La documentación se genera en `analytics/target/`; `dbt docs serve --project-dir
analytics --profiles-dir analytics --port 8080` permite explorar catálogo y DAG
localmente. No se publica ni se versiona ese directorio.

Ver [baseline](../docs/migration/dbt_baseline.md),
[ADR](../docs/decisions/ADR-001-dbt-integration.md) e
[integración, resultados y límites](../docs/migration/dbt_integration.md).
