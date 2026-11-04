# ADR-001 — Integración opcional y aislada de dbt

Estado: aceptada para fases 0 y 1. Fecha: 2026-11-02.
Proyecto: versión 1.0.0, sin release nuevo.

## Contexto y problema

El pipeline ELT funciona y concentra normalización, calidad y métricas en un SQL
con múltiples sentencias y DDL. Necesitamos organizar gradualmente dependencias,
validaciones y documentación analítica sin alterar extracción, carga, transacciones
ni resultados. El entorno usa Python 3.12, uv y DuckDB embebido en Windows/Linux.
La auditoría está en [dbt_baseline.md](../migration/dbt_baseline.md).

## Alternativas investigadas

| Alternativa | Ventajas | Costes / límites para esta iteración |
|---|---|---|
| dbt Core v1 + dbt-duckdb | Paquetes Python resolubles por uv; reutiliza el DuckDB Python ya fijado; ejecución local, tests y docs/linaje clásicos. | Árbol transitivo amplio; adaptador separado; futura revisión de soporte/versiones. |
| dbt v2, soporte local DuckDB integrado | Motor Rust, adaptador incluido y driver integrado; no necesita dbt-duckdb. Disponible instalación pip y opciones Windows/Linux. | Introduce otro motor/driver cuya equivalencia habría que verificar; la documentación declara diferencias respecto al adaptador v1 y límites de análisis SQL/archivos locales. |
| Mantener únicamente SQL/Python | Sin nuevas dependencias. | No incorpora el DAG, catálogo y ejecución dbt solicitados. Se conserva como operación principal durante la POC. |

La consulta a PyPI reportó dbt Core **1.12.6**, dbt-duckdb **1.11.1** y dbt **2.0.9**
como versiones actuales. Los metadatos de los tres requieren Python >=3.10.
La matriz oficial de Core 1.12 incluye Python 3.12. dbt-duckdb declara Windows y
Linux y permite dbt-core >=1.8 y duckdb >=1.0; la resolución concreta se verificó
instalando y ejecutando los paquetes en este entorno.

## Decisión

Usar **dbt-core==1.12.6 y dbt-duckdb==1.11.1**, fijados en el grupo opcional `dbt`
de `pyproject.toml`, con dependencias transitivas en `uv.lock`. Mantener DuckDB
**1.5.6**, sin actualizar versiones de dependencias base. El proyecto dbt exige
Core >=1.12.6,<1.13.0. No instalar el paquete `dbt` v2 en este entorno ni combinar
ambas CLIs. No se eligió v1 por desconocer el soporte integrado de v2.

La razón principal es controlar la equivalencia con la implementación funcional:
ambos caminos ejecutan el mismo SQL con el mismo DuckDB Python. La POC usa un solo
modelo SQL materializado como tabla, sin packages externos, seeds de datasets,
extensiones, servicios ni credenciales.

## Instalación reproducible

Desde la raíz del repositorio, con Python 3.12 y uv:

```shell
uv sync --frozen --group dbt
uv run --frozen --group dbt dbt --version
```

Usar `--group dbt` también en cada `uv run` experimental: uv puede retirar paquetes
opcionales si se omite. `uv sync --frozen` mantiene el entorno original sin dbt.
`uv lock` sólo se utiliza al actualizar intencionalmente dependencias; no forma
parte de la reproducción habitual. El lock cubre plataformas, pero ejecutar en
Windows no demuestra ejecución real en Linux.

## Aislamiento y contrato de ejecución

El preparador genera una base temporal nueva con fixtures y las funciones originales.
Cierra la conexión y copia únicamente esa base de prueba a un destino nuevo
`*_poc.duckdb`, con creación exclusiva. Rechaza archivos existentes. Nunca abre ni
copia `data/service_operations.duckdb`.

El perfil usa una ruta relativa a la raíz y esquema fijo `dbt_staging`. Se puede
seleccionar otra ruta local de prueba mediante `DBT_POC_DATABASE`; el hook exige
el sufijo `_poc.duckdb`, esquema separado y metadatos de snapshot. La nomenclatura
no es un sistema de permisos ni un mecanismo para volver segura cualquier base
arbitraria: seguir usando exclusivamente las bases preparadas por la POC.

No hay run_id predeterminado ni inferencia de latest. Se requieren `run_id` y
`snapshot_id` explícitos, concordancia con auditoría success y huellas de RAW,
pertenencia y auditoría. El modelo une RAW y pertenencia por ID y filtra sólo por
la pertenencia seleccionada; mantiene `last_run_id` como procedencia independiente.
La validez de un run_id histórico no implica historial de versiones.

## Beneficios esperados

Permite practicar sources, modelo, tests, materialización y catálogo con un caso
real del repositorio. El staging conserva la semántica SQL y puede compararse con
un oráculo independiente sin reemplazar las métricas. La instalación base y la
operación existente siguen disponibles sin dbt.

## Desventajas, riesgos y consecuencias

Core incorpora unas 50 dependencias/paquetes de instalación adicionales, incluidos
transitivos que esta POC no utiliza directamente; se aíslan por grupo. El coste
no justifica añadir plataformas ni paquetes opcionales del adaptador.

La POC duplica intencionalmente el SELECT de normalización para comprobar paridad;
si cambia `transform.sql`, las pruebas deben revelar divergencias y requerir revisión.
No se extrae ahora una macro compartida porque modificaría el oráculo original.

Las huellas MD5 de JSON ordenado comprueban alteraciones accidentales, no seguridad,
historial ni portabilidad entre motores/versiones. El entorno fija motor y UTC para
serialización. Se verifican las diez tablas originales de la POC después de dbt.
La documentación generada puede contener metadatos locales: queda ignorada.

`threads: 1` limita concurrencia interna; no soluciona escritores externos. No se
ejecuta dbt dentro de la transacción Python ni se ofrece atomicidad entre procesos.
Diseñar bloqueo, recuperación y publicación sigue siendo requisito para otra fase.

Core y v2 evolucionan. Revisar soporte y repetir la evaluación antes de una
integración estable; v2 no fue instalado ni ejecutado comparativamente. No se
afirma superioridad de rendimiento de ninguna alternativa.

## Fuentes primarias consultadas

- [Versiones y generaciones de dbt](https://docs.getdbt.com/docs/dbt-versions).
- [Compatibilidad Python/Core](https://docs.getdbt.com/faqs/Core/install-python-compatibility).
- [Metadatos de dbt-core 1.12.6](https://pypi.org/pypi/dbt-core/1.12.6/json).
- [Metadatos de dbt-duckdb 1.11.1](https://pypi.org/pypi/dbt-duckdb/1.11.1/json).
- [Configuración del adaptador v1](https://pypi.org/project/dbt-duckdb/1.11.1/).
- [Instalación oficial de v2](https://docs.getdbt.com/docs/local/install-dbt).
- [DuckDB integrado y limitaciones en v2](https://docs.getdbt.com/docs/local/connect-data-platform/duckdb-setup).
- [Anuncio de DuckDB sobre v2](https://duckdb.org/2026/09/22/dbt-fusion).

La documentación describe las rutas relativas del perfil respecto a profiles.yml,
pero la ejecución del adaptador instalado resolvió la ruta desde el directorio
actual. Por ello los comandos exigen la raíz del repositorio y se verificó esa
convención, sin rutas personales ni depender de la afirmación documental.
