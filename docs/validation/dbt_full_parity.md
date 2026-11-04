# Fase 2 — validación de paridad integral

Ejecutada el **4 de noviembre de 2026**. Entorno: Windows 11, Python 3.12.10,
uv 0.12.7, DuckDB 1.5.6, dbt Core 1.12.6 y dbt-duckdb 1.11.1.
Resultados sintéticos de esta iteración; no son una nueva extracción NYC 311.

## Git al inicio y separación del trabajo

La rama `feature/dbt-analytics-layer` apuntaba a
`5dc3143e476739d341ddb24d329ce6bfd9cef112`. Las fases 0–1 y el dashboard todavía
estaban sin confirmar: cuatro archivos seguidos modificados y archivos nuevos
bajo analytics, docs, src, tests y el workflow Pages. Se revisaron status, diff,
los cinco últimos commits disponibles y las ramas antes de editar.

Se conservaron copias y SHA-256 de 51 archivos fuente, el diff inicial y la huella
de la base operacional bajo `tmp/phase2-baseline/` (ignorado). Se usó el diff
guardado en fase 0 para separar los cambios compartidos de README/lock/configuración.

| Commit local de preservación | Contenido previo, sin cambios de fase 2 |
|---|---|
| `79e02dc` | Dashboard, plantilla, pruebas, documentación, Plotly y workflow Pages; nueve archivos. |
| `18f229a` | POC dbt, dependencias opcionales, pruebas, baseline y documentación de fases 0–1; veinte archivos. |

Después se organizaron commits de modelos/ADR, verificación/pruebas y presentación.
No se reescribió historia, hizo push, merge, tag o release. La versión sigue en 1.0.0.
No se modificó ni consultó el repositorio de perfil personal.

Archivos nuevos: `analytics/models/intermediate/` (clasificación y YAML),
`analytics/models/marts/` (fact, cinco marts y YAML), cinco contratos SQL bajo
`analytics/tests/`, `tests/test_dbt_full_parity.py`, ADR-002, este reporte y
`docs/pipeline.md`. Modificados: macro de guardia, comentario/schema del staging,
`dbt_poc.py`, README raíz/analytics, guía dbt, changelog y estado de la demo en
docs/dashboard.md. No se añadieron dependencias ni módulos Python nuevos.

## Qué se comparó

La matriz de [ADR-002](../decisions/ADR-002-dbt-model-migration.md) precedió a la
implementación. Hay ocho modelos, uno ephemeral y siete tablas en `dbt_staging`.
La clasificación es el único intermediate; las reglas de flags se integran en la
fact sin materializar capas redundantes.

| Referencia original | Modelo dbt | Columnas comparadas |
|---|---|---:|
| requests | fct_service_requests | 16 |
| metrics | mart_overall_metrics | 9 |
| daily_metrics | mart_daily_metrics | 12 |
| category_metrics | mart_category_metrics | 8 |
| agency_metrics | mart_agency_metrics | 8 |
| quality_issues | mart_quality_issues | 2 |

Se comprueban nombres/tipos/orden de columnas y el multiconjunto de filas en ambas
direcciones con EXCEPT ALL, sin depender del orden físico. Incluye NULL, listas
ordenadas de flags, microsegundos, TIMESTAMP/TIMESTAMPTZ y todas las métricas.
Se exige igualdad exacta de flotantes porque ambos caminos usan las mismas
expresiones y el mismo DuckDB fijado. No se aplicaron tolerancias ni redondeos.

El staging conserva su verificación anterior: diez columnas compartidas y la
procedencia adicional. Antes de aceptarlo se comparan las huellas completas de
las diez tablas originales de la POC. El preparador no abre ni copia la base real.

## Resultados ejecutados

| Comando / comprobación | Resultado real |
|---|---|
| Baseline: `uv run --frozen --group dbt pytest` | **63 passed**, 83,25 s |
| Baseline: `uv sync --frozen` y suite base | dbt ausente; **62 passed, 1 skipped**, 8,00 s |
| `uv run --frozen --group dbt pytest tests/test_dbt_full_parity.py` | **9 passed**, 43,44 s |
| Suite final: `uv run --frozen --group dbt pytest` | **72 passed**, 116,58 s |
| Suite final tras `uv sync --frozen` | dbt ausente; **66 passed, 6 skipped**, 9,89 s |
| `dbt build` sobre POC pequeña | 7 tablas, **33 data tests passed**, 1 hook; cero errores/advertencias/omitidos |
| Preparación/build/verificador CLI con escenario edge | 32 solicitudes, 12 días, 33 tests dbt; seis salidas con cero diferencias y diez huellas intactas |
| CLI `python -m service_analytics.dbt_poc verify` | Paridad integral verdadera, seis salidas con cero diferencias; diez tablas originales intactas |
| Build/verificación en los cuatro escenarios de pytest | Paridad exacta en todos los modelos; mismas huellas originales |
| `dbt docs generate` | Catálogo/manifiesto generados: 8 modelos, 7 tablas; 55 columnas finales documentadas |
| `uv run --frozen python -m service_analytics.dashboard` | Genera `site/index.html` con los agregados existentes, sin API ni dbt |

Los seis skips de la suite sin dbt son explícitos: un test subprocess de fase 1,
cuatro builds de escenarios y una prueba de destino no permitido. Los 60 casos
previos de pipeline/dashboard, los dos tests de preparación de fase 1 y cuatro
tests nuevos de escenarios se ejecutaron. No se eliminaron ni cambiaron tests previos.
La suite completa con dbt no tuvo fallos ni skips. El resumen PASS de dbt build
es 41 porque incluye 7 tablas + 33 tests + 1 hook, no 41 tests.

## Escenarios y casos límite

| Escenario | IDs seleccionados | Días | Comportamiento comprobado |
|---|---:|---:|---|
| small / poc-fixture-v1 | 7 | 3 | Cohorte corta, día vacío, anomalías y baseline insuficiente. |
| edge / poc-edge-v2 | 32 | 12 | Cinco estados abiertos, CLOSED, desconocidos; bandas exactas; flags solapadas; semana completa. |
| empty / poc-empty-v2 | 0 | 3 | Agregado global de una fila; medianas/porcentaje NULL; grupos vacíos y tres días cero. |
| zero-baseline / poc-zero-baseline-v2 | 1 | 8 | Siete días cero antes de una llegada; ratio NULL y review=false pese a tener siete días. |

El escenario edge comprueba 32 solicitudes: 16 open, 14 closed, 2 unknown,
12 duraciones elegibles y 6 solicitudes con flags. El día 8 tiene media previa 2,
volumen 3, ratio **1,5** y review=true; el día 9 queda en cero y se conserva la
fecha final exclusiva. Una solicitud presenta cinco flags y la suma por regla
es diez, mayor que las seis solicitudes afectadas. Una solicitud con agencia
ausente conserva su duración elegible de una hora.

También se comprueban cero horas, límites 24/72/168, microsegundos, actualización
UTC con offset, whitespace extremo, fechas malformadas, intervalo negativo,
abierta con cierre y cerrada sin fecha. La carga edge rechaza tres IDs inutilizables
y cuenta un duplicado cuyo último payload gana. Se reutilizan sin cambios las
fixtures y guardias de fase 1, incluidas pertenencia histórica y RAW mutable.

Se alteró deliberadamente **cada una** de las seis salidas, manteniendo su número
de filas: orden de listas, mediana, baseline y frecuencias/conteos. Todas las
alteraciones fallaron en el verificador. Un cambio BIGINT→DOUBLE, con mismos
valores, falló por esquema. Esto evita aceptar igualdad de conteos como paridad.

El test de destino protege un archivo sintético `protected.duckdb`: dbt build
debe fallar durante parsing, conservar su SHA-256 y no crear `dbt_staging`.
Los tests previos siguen rechazando variables omitidas, otra cohorte, snapshot
incorrecto, fuente alterada y sobrescritura de archivos.

## Preservación de la implementación original

Se verificó igualdad de SHA-256 con el inicio para 19 archivos/base: pipeline,
transform.sql, esquema, extracción, ETL, preview, dashboard/plantilla, cinco
archivos de tests existentes, los tres workflows, pyproject, lock y base real.
Ninguna dependencia, métrica, exportación ni flujo transaccional original cambió.

| Archivo | SHA-256 sin cambios |
|---|---|
| pipeline.py | `ec31e0d6d2e2b7e48efbe3c1f2ffa45a622a54b81d294514e428893370d2e5e4` |
| transform.sql | `4bb8cd5e70a359e620d81872997a4e544b48b675a9f2dd9e1aa2b620a2a7160d` |
| data/service_operations.duckdb | `275a2b297b4b6a8438c6ade3dca0e885333c326c9bf38d5b29b55e46b183085a` |

## Problemas corregidos y límites

- La fase 1 sólo comparaba staging. La CLI ahora verifica las seis salidas; su API
  Python anterior se conserva para no romper consumidores/tests.
- La guardia de destino sólo estaba en on-run-start. Se añadió al parsing para
  rechazar un destino no permitido antes de crear esquemas.
- La fixture de tres días no cubría baseline semanal ni todos los límites; los
  escenarios nuevos lo verifican sin cambiar reglas originales.
- No aparecieron discrepancias analíticas en las comparaciones ejecutadas.
  No fue necesario modificar el SQL original ni introducir tolerancias.
- Linux **no ejecutado**: Docker no está disponible y `wsl --list --quiet` informa
  que WSL no está instalado. No se cambió CI ni se afirmó paridad de plataformas.
- No se ejecutó el API NYC 311 ni dbt sobre las 78.466 filas reales; los resultados
  históricos siguen siendo los de la evidencia existente.
- No hubo revisión visual del dashboard/linaje en navegador. Se inspeccionó la
  imagen real existente, se generó el dashboard y se revisaron fuentes del diagrama.

## README, enlaces y acciones manuales

La portada ahora muestra propósito, stack, resultados delimitados, preview real,
capacidades demostradas y tres rutas claras: offline, dbt aislado e ingesta opcional.
Mermaid distingue el pipeline original y la validación paralela. Detalles de
operación/exportaciones se trasladaron a [pipeline.md](../pipeline.md), sin crear
otra demo. La documentación dbt se condensó y enlaza esta evidencia.

HTTP público: repositorio y badge CI devuelven 200. `main` público sigue en
`5dc3143`: no contiene los cambios locales del dashboard/dbt. La URL prevista
de Pages devuelve **404**; README y docs/dashboard.md lo indican y ofrecen la
ejecución local. No se anuncia una demo pública disponible ni tests remotos de fase 2.
Se comprobaron **41 enlaces/rutas/anchors locales** en siete documentos y la
renderización GFM del README mediante la API Markdown de GitHub. Mermaid queda
como bloque para enriquecimiento del navegador; no se afirma revisión visual
del SVG o de una pantalla móvil. `git diff --check` terminó sin errores.

Propuestas para aplicar manualmente **después de revisar/publicar estos cambios**:

- **About:** NYC 311 analytics with Python, SQL and DuckDB, plus a parallel dbt layer verified against original metrics and quality rules.
- **Topics:** `python`, `sql`, `duckdb`, `dbt`, `analytics-engineering`, `data-engineering`, `elt`, `data-quality`.
- **Social preview:** usar la imagen real `docs/evidence/dashboard_preview.png`,
  con un recorte legible que conserve título, ventana y procedencia. No se creó otra imagen.
- **Pages:** revisar la configuración GitHub Actions y el workflow existente
  cuando se autorice publicar. No se cambiaron ajustes remotos.

## Pendiente para fase 3

Definir snapshots/versionado RAW y selección de cohortes en operación; coordinar
un escritor DuckDB y cierre de conexiones; diseñar transacción, recuperación y
publicación entre procesos; validar exportaciones/dashboard con el futuro camino
dbt; ejecutar Linux/Windows antes de incorporar CI dbt. La comparación ETL/ELT
debe seguir bloqueando diferencias. Mantener el original hasta un cutover revisado.

Comandos reproducibles completos: [guía dbt](../migration/dbt_integration.md).
Logs, JSON de verificación y artefactos generados permanecen en tmp/target/sandbox
ignorados; este reporte sólo incluye resultados y checksums, no datasets individuales.
