# Changelog

## Unreleased

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

No se reemplaza `transform.sql`, no se integra dbt en `pipeline.py`, no se migran
métricas/exportaciones y no se publica la futura versión 1.1.0.
