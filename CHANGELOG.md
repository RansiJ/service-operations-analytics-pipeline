# Changelog

## Unreleased

### Phase 2.5 — CI stabilization and publication preparation

- Add a separate dbt job on Ubuntu/Windows, preserving the base matrix
  and Linux wheel check. Run the locked environment, full offline pytest, a fresh
  synthetic dbt build and exact six-output/ten-fingerprint verification.
- Fail the dbt job on skipped or uncollected tests; check that the operational
  database is absent. Keep generated reports/databases local to the runner.
- Enable CI pushes only on main and the named feature branch, alongside PR/manual
  triggers, so validation can run before an authorized merge.
- Document the observed Pages configuration, unpublished workflow and deployment
  checklist. Keep the existing Pages/refresh workflows and all analytical code.
- Record local evidence separately from hosted validation and publication status.

### Phase 2 — parallel analytical migration

- Preserve the previously uncommitted dashboard and phases 0–1 in separate local commits.
- Migrate classification, overlapping quality flags, eligible durations and all five
  analytical marts into an eight-model dbt DAG, with one ephemeral intermediate.
- Extend the isolated verifier to compare schemas and exact row multisets for all
  six original outputs, preserving the phase-1 staging API.
- Add deterministic empty/weekly/band-boundary scenarios and corruption checks;
  move the target guard into parsing so invalid build targets fail before schema creation.
- Add model contracts, ADR-002 and a full parity/regression report. Preserve
  ingestion, original SQL, transactions, ETL comparison, exports and workflows.
- Restructure the repository README around purpose, real evidence, architecture
  and offline reproduction. Correct the intended dashboard URL's observed 404 status.
- Keep project version 1.0.0; no operational dbt integration or remote publication.

### Phases 0–1 (previous work)

- Auditoría del sistema original y baseline offline, con identificación y
  preservación de cambios locales previos del dashboard.
- Grupo opcional uv para dbt Core 1.12.6 y dbt-duckdb 1.11.1, sin cambiar la
  versión 1.0.0 ni actualizar las dependencias originales.
- POC aislada con fuentes documentadas, staging de solicitudes y 11 tests dbt.
- Preparación determinista sin API, selección explícita de cohorte/instantánea,
  huellas de fuentes y verificación de equivalencia con el SQL original.
- Tres pruebas pytest adicionales, incluyendo ejecución real opcional de dbt,
  protección ante selecciones incorrectas y conservación de anomalías.
- ADR-001, guía de reproducción, límites y fases pendientes.

En las fases 0–1 no se migraron métricas. La fase 2 las reproduce en paralelo;
`transform.sql`, `pipeline.py` y las exportaciones originales permanecen como antes.
No se publica la futura versión 1.1.0.
