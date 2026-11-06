# Changelog

## Unreleased

### Phase 3B, delivery 1 — inactive publication foundations

- Add opt-in execution phases, per-attempt metadata and conservative legacy
  assessment, without changing the original initializer or ten-table dbt POC.
- Add a cooperative local descriptor lock with canonical DB identity and a
  persistent output-root binding, using the Python standard library.
- Add synthetic state/schema and real multiprocess tests, plus ADR-003 and a
  technical guide. Separate local Windows evidence from hosted Ubuntu/Windows
  validation in the PR and review package; preserve the existing CI workflow.
- Preserve terminal attempt history: identical failures are idempotent, changed
  errors/identity/outcomes are rejected, and pre-T2 retries retain the prior row.
- Make published/succeeded strictly terminal; post-publication reconciliation
  remains outside the metadata API. Cover direct persistence edits and stale writes.
- Correct external review packaging to redact parsed XML values, reparse the
  serialized JUnit and validate final counts/hashes. Record hosted CI by PR/head.
- Preserve the operational SQL producer, pipeline, dbt models and workflows.
  No snapshots, operational dbt, promotion, latest writes or recovery are enabled.

### Phase 2.6 — publication and repository presentation

- Merge reviewed PR #1 after confirming its original head and all four hosted
  Ubuntu/Windows checks; preserve the separate commits and parallel dbt scope.
- Publish the existing aggregate dashboard through the unchanged Pages workflow;
  verify HTTP 200 for HTML/JS and exact hashes against its deployment artifact.
- Promote the verified dashboard link and repository website metadata; replace
  obsolete publication warnings while retaining the fixed observation period and
  explicit pending desktop/mobile browser QA. Keep version 1.0.0.

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
