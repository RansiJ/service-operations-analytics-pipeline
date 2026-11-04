# Fase 2.5 — estabilización y preparación de publicación

Validación realizada el **4 de noviembre de 2026**. No es fase 3 ni un cambio del
camino operativo. Versión: **1.0.0**.

## Baseline de esta iteración

Git comenzó limpio en `feature/dbt-analytics-layer`, HEAD `45e5070`; main/origin main
seguían en `5dc3143`. Se revisaron ramas, log, remoto, diff con main, workflows,
lock, fixtures, guardias, tests y documentación antes de editar. Se guardaron SHA-256
de archivos seguidos y de la base real en `tmp/stabilization-phase2_5/` (ignorado).
No se sobrescribió trabajo previo ni se reordenaron commits.

Entorno real: Windows 11, Python **3.12.10**, uv **0.12.7**, DuckDB **1.5.6**,
dbt Core **1.12.6**, dbt-duckdb **1.11.1**, pytest **9.1.1**, Plotly **6.9.0**.
El baseline nuevo `uv run --frozen --group dbt pytest` terminó con **72 aprobadas,
0 fallidas, 0 errores, 0 omitidas**, en 90,67 s. No se reutilizó el resultado de fase 2.

## Cambios, razones y verificación

| Archivo | Problema y solución | Cómo se comprobó |
|---|---|---|
| `.github/workflows/ci.yml` | El CI habitual omitía dbt. Añadir job `dbt` independiente con Ubuntu/Windows, instalación frozen y verificación completa. | YAML parseado; job base idéntico al anterior; replay local de todos los comandos nuevos. |
| Mismo workflow | Los skips opcionales podían producir verde sin ejecutar dbt. Rechazar skips o cero tests mediante JUnit, sin nueva librería/plugin. | Reporte real con 72 tests/0 skips aceptado; reporte base con 6 skips rechazado con exit 1. |
| Mismo workflow | Faltaba una ejecución CLI sobre archivo nuevo. Exigir ausencia de POC/base operativa, preparar, build y verificar; comprobar de nuevo ausencia de base operativa. | Copia limpia sin bases previas, siete solicitudes y seis salidas idénticas; diez huellas intactas. |
| Mismo workflow | Faltaba validar la rama antes del merge. Añadir únicamente `feature/dbt-analytics-layer` al push, conservando main, PR y dispatch. | Revisión de triggers y matriz; no se lanzó ningún run remoto. |
| README y docs/dashboard.md | El 404 no tenía diagnóstico completo. Distinguir configuración existente, código no publicado y despliegue no verificado; instrucciones de publicación. | Consultas GitHub de solo lectura y HTTP 404 actual. |
| docs/migration/dbt_integration.md | La descripción de CI de fase 2 quedó histórica. Enlazar la matriz propuesta y sus límites. | Comandos analíticos permanecen iguales. |
| CHANGELOG.md y este reporte | Trazabilidad de lo implementado y lo pendiente. | Diff acotado a seis archivos; sin nuevas dependencias ni código analítico. |

Se mantuvo el job `test` original completo: Ubuntu/Windows y smoke del wheel en Linux.
El nuevo job no tiene `if` ni `continue-on-error`; `fail-fast: false` permite observar
ambas plataformas. Mantiene `contents: read` y los mismos SHA de acciones, verificados
en sus repositorios oficiales. No sube bases, XML, logs, outputs ni site como artifacts CI.

No se añadió un runner/helper Python ni un plugin pytest: el pequeño control JUnit
usa la biblioteca estándar. Un YAML inicial rechazó los dos puntos de `--vars` en
un escalar plano; se corrigió usando `run: >-` y se repitió el parseo/replay completo.
Los comandos nuevos no usan sintaxis exclusiva de Bash. Se dejan los shells nativos
de Actions: Bash en Ubuntu y pwsh en Windows. El replay local usó `powershell.exe`;
esto **no demuestra** ejecución con pwsh en un runner hospedado.

## Ejecuciones locales y conteos

Para reproducir la independencia del runner se copió sólo el contenido seguido por
Git a una carpeta nueva, incluyendo el CI propuesto, sin .venv, bases ni salidas.
Se creó allí otro entorno con uv y se ejecutaron los campos `run` del job nuevo,
en orden, a través de Windows PowerShell. No se simularon las acciones de checkout,
setup-python, setup-uv ni un runner de GitHub.

| Comando/comprobación nueva | Aprobadas | Fallidas/errores | Omitidas | Resultado |
|---|---:|---:|---:|---|
| Baseline pytest con grupo dbt | 72 | 0 | 0 | 90,67 s |
| Replay: `uv sync --frozen --group dbt` + pytest con JUnit | 72 | 0 | 0 | 102,46 s |
| `uv sync --frozen`; dbt ausente; pytest base | 66 | 0 | 6 | 6,46 s |
| `uv run --frozen pytest tests/test_dashboard.py` | 22 | 0 | 0 | 1,05 s |
| `dbt build` CLI en POC nueva | 33 data tests | 0 | 0 | 7 tablas + 1 hook; PASS total 41 |
| CLI `dbt_poc verify` | — | 0 diferencias | — | 6 salidas y 10 huellas originales intactas |

Los seis skips base son los mismos tests opcionales de dbt: uno de fase 1, cuatro
escenarios y una guardia de destino. Se ejecutaron todos en el job dbt. El control
JUnit rechazó el reporte base con `Collected: 72 Skipped: 6`, exit 1, como se esperaba;
ese rechazo deliberado no es un fallo de pytest. El XML exitoso se restauró después.

Secuencia exacta principal del job propuesto, desde la raíz:

```shell
uv sync --frozen --group dbt
uv run --frozen --group dbt pytest --junitxml=tmp/dbt-pytest.xml
# El workflow comprueba que JUnit contiene tests y cero skips.
# Después comprueba que no existen la POC ni data/service_operations.duckdb.
uv run --frozen --group dbt python -m service_analytics.dbt_poc prepare
uv run --frozen --group dbt dbt build --project-dir analytics --profiles-dir analytics --vars '{run_id: poc-selected, snapshot_id: poc-fixture-v1}'
uv run --frozen --group dbt python -m service_analytics.dbt_poc verify
```

Se usan los IDs explícitos `poc-selected` / `poc-fixture-v1`, ruta relativa
`analytics/sandbox/service_requests_poc.duckdb` y esquema `dbt_staging`. El preparador
rechaza sobrescritura; en CI el checkout es nuevo. El job vuelve a comprobar que
`data/service_operations.duckdb` no se creó. No se ejecutó NYC 311.

## Plataformas y GitHub Actions

- **Windows local:** baseline, replay limpio y comandos anteriores ejecutados.
- **Ubuntu/Linux local:** no ejecutado. `wsl --status` informa que WSL no está
  instalado (exit 50); Docker no está disponible y no se instaló infraestructura.
- **Al cerrar la fase 2.5, GitHub-hosted Ubuntu/Windows:** **pending remote validation**.
  En aquella etapa no se hizo push ni dispatch. YAML válido/replay Windows no equivalen
  a un run remoto. La comprobación previa al PR se registra al final de este documento;
  los resultados hospedados se registran en los checks y en la descripción del PR.
- [CI histórico observado](https://github.com/RansiJ/service-operations-analytics-pipeline/actions/runs/38661240583)
  muestra test Ubuntu/Windows exitosos en `5dc3143`. Valida únicamente el main
  anterior; ese workflow no contiene el nuevo job dbt.

Después de autorizar el push, abrir PR o usar **Actions → CI → Run workflow** con
la rama feature. El push de esa rama también ejecutará CI automáticamente. Antes
del merge deben revisarse los estados `test (ubuntu-latest)`, `test (windows-latest)`,
`dbt (ubuntu-latest)` y `dbt (windows-latest)`. Si se desea impedir merges sin esos
estados, marcarlos como required checks en las reglas de main tras su primer run;
no se cambió branch protection ni otro ajuste remoto aquí.

## Dashboard y Pages

`uv run --frozen python -m service_analytics.dashboard` generó correctamente el
dashboard existente desde los agregados verificados. site/ contiene exclusivamente
`index.html` (59.082 bytes) y `assets/plotly.min.js` (4.855.045 bytes). Los 22 tests
verifican datos reales agregados en cinco figuras, valores, integridad de inputs,
exportación y ausencia de CSV a nivel de solicitud. Se comprobó la referencia
relativa `assets/plotly.min.js` y su archivo local: funciona bajo el prefijo del
proyecto en Pages. No se creó otra demo ni imagen.

Diagnóstico de solo lectura del repositorio objetivo:

- Pages: `has_pages=true`, público, `build_type=workflow` y URL prevista correcta.
- Main público: `5dc3143`; workflows remotos: CI y Bounded public-data refresh.
- La rama feature aún no existe en origin (404), Pages no tiene workflow publicado
  en main y la consulta de deployments `environment=github-pages` devolvió vacío.
- La URL prevista sigue devolviendo **HTTP 404**. No hay evidencia de un despliegue
  fallido; la preparación local aún no está publicada. No se atribuye a Pages deshabilitado.

Estado: **ready for manual publication / not verified**. `pages.yml` queda sin cambios:
dependencias frozen, build offline, upload de site/, dispatch y filtros de main
coherentes, environment github-pages y permisos Pages/OIDC sólo en deploy. Los
seis SHA de acciones existentes resuelven a commits válidos. El refresco y su cron
tampoco se modificaron.

Pasos para publicar, únicamente tras autorización: revisar/confirmar cambios,
push de feature, CI verde en ambas plataformas, merge autorizado, comprobar
**Settings → Pages → Build and deployment → Source: GitHub Actions** (ya configurado),
y ejecutar **Deploy analytics dashboard** en main si el push no lo activó. Después
verificar run build/deploy, HTML/JS HTTP 200 y escritorio/móvil. El detalle está en
[dashboard.md](../dashboard.md#publication-status-and-manual-steps).

No se revisó visualmente el dashboard en navegador ni se verificaron HTML/assets
remotos publicados. No se usaron capturas simuladas. README conserva la demo local,
preview auténtica y resultados históricos, separados de la paridad sintética dbt.
About/Topics/Social preview siguen como propuestas de la fase anterior, sin aplicar.

La revisión final comprobó 34 enlaces/rutas/anchors locales y el render GFM del
README mediante la API Markdown de GitHub; el bloque Mermaid se conserva, sin
afirmar revisión visual de su SVG. `git diff --check` pasó. Todos los archivos
previos fuera de las cinco ediciones previstas conservan su SHA-256 inicial,
incluidas las definiciones dbt, tests, workflows Pages/refresco y la base real.
Los archivos generados siguen ignorados; sólo el reporte nuevo se añade al diff.

## Estado al cerrar la revisión local de fase 2.5

Al cerrar la fase 2.5 quedaron seis archivos en el diff, sin commits nuevos, para
revisión. En esa etapa no se hizo push, merge, release, cambio de Pages, workflow
dispatch ni modificación de `RansiJ/RansiJ`.
Logs, XML, copia limpia y bases permanecen ignorados bajo tmp/; no son entregables
públicos ni artifacts del workflow.

La fase 3 sigue bloqueada por decisiones operativas de snapshots, escritor único,
transacciones/publicación y recuperación. Antes de atribuir soporte multiplataforma
a esta capa falta ejecutar la matriz hospedada. Las definiciones/modelos analíticos,
pipeline original, comparación ETL/ELT, dashboard y dependencias permanecen intactos.

## Nueva comprobación previa al PR

El usuario autorizó confirmar los cambios revisados, publicar la rama feature y
crear un PR hacia main; no autorizó merge, Pages ni release. Estas ejecuciones
locales son nuevas, posteriores al baseline anterior, en el mismo Windows/Python:

| Comando ejecutado | Resultado nuevo |
|---|---|
| `uv run --frozen pytest tests/test_extract.py tests/test_models.py` | 38 aprobadas, 0 fallos, 0 omitidas; 4,61 s |
| `uv run --frozen --group dbt pytest` | 72 aprobadas, 0 fallos, 0 omitidas; 89,40 s |
| Prepare/build/verify con `DBT_POC_DATABASE=analytics/sandbox/pr_validation_poc.duckdb` | Archivo nuevo, 33 tests dbt aprobados, seis salidas sin diferencias y diez huellas intactas |
| YAML de CI y comparación de archivos protegidos | Matrices/permisos válidos, job base conservado y hashes sin cambios |

Se generaron nuevos reportes JUnit bajo `tmp/remote-pr-validation/`, ignorados.
Se mantuvieron run_id `poc-selected` y snapshot_id `poc-fixture-v1`. No se consultó
NYC 311 ni se abrió la base operativa mediante DuckDB. Las cifras anteriores
permanecen como evidencia histórica, sin atribuirlas a esta nueva ejecución.

La evidencia remota debe referirse al commit/run que realmente haya terminado:
consultar los cuatro jobs del PR y su descripción actualizada. El README enlaza
los runs de la rama y no utiliza el badge de main como prueba de esta actualización.
