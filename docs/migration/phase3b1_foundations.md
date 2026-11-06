# Fase 3B, entrega 1: fundamentos inactivos de publicación

Esta entrega añade `service_analytics.publication`, pruebas sintéticas y
[ADR-003](../decisions/ADR-003-publication-state-and-lock.md). No lo importa el CLI,
no modifica `pipeline.py`, SQL, modelos dbt ni workflows. El productor operativo
sigue siendo el SQL original; versión 1.0.0, cambios en Unreleased.

Referencia histórica: paquete externo `service-operations-phase3-design-review.zip`,
en particular proposed_design, architecture_current, implementation_roadmap,
failure_recovery_matrix, test_strategy y open_decisions. No se edita ese diseño.
Esta entrega autoriza solo los fundamentos del primer PR; no presupone aprobadas
las decisiones de cutover de 3A. El usuario confirmó el QA visual de fase 2.6;
esta entrega no lo repite ni lo declara pendiente nuevamente.

## Fases, intentos y resultados

`RunState` es un valor inmutable, separado de `pipeline_runs`:

`created → raw_committed → candidate_validated → artifacts_ready → tables_committed → published`

- `advance` admite únicamente el siguiente paso de un intento activo. Una fase
  desconocida, salto o retroceso falla; no se ejecuta la operación nombrada.
- `run_id`/`snapshot_id`: 1–128 caracteres ASCII alfanuméricos, `_` o `-`, empezando
  por alfanumérico. No son identificadores SQL. En created snapshot_id es NULL;
  después se exige uno explícito e invariable. Validar la cadena **no comprueba
  existencia de un snapshot**: su implementación queda para otra entrega.
- El primer error de un intento activo conserva la fase alcanzada. Antes de
  tables_committed, outcome=failed; en tables_committed, requires_reconciliation,
  nunca rollback declarado. Ambos resultados son terminales e inmutables: repetir
  exactamente el mismo error/estado es no-op; cambiar su texto, identidad, fase u
  outcome se rechaza también por record_run, incluso con un objeto construible.
- `retry` es una decisión explícita de metadatos, solo antes de T2 y después de
  failed: incrementa intento y conserva fase/identidad. La fila previa no se borra.
  No reintenta procesos ni recupera datos. published/succeeded es estrictamente
  terminal: failed() y record_run no permiten convertirlo en reconciliación.
  Registrar una inconsistencia posterior requerirá un protocolo futuro explícito;
  esta entrega no lo implementa ni modifica una publicación pasada.
- `record_run` conserva duplicados exactamente coherentes como no-op, valida la
  progresión y rechaza duplicados incompatibles. UPDATE compara todos los valores
  anteriores para detectar una actualización concurrente. El llamador debe
  coordinar escritores y controlar su transacción; no hay COMMIT escondido.

Las fases persistidas son afirmaciones del llamador. Ni siquiera un registro
published demuestra publicación de tablas/archivos. Esa evidencia y su integración
transaccional no existen todavía en este módulo.

## Esquema opt-in

`initialize_publication(con)` crea únicamente dos tablas en main. Es idempotente
para su esquema compatible, valida nombres/orden/tipos y PK, y confirma ambas
creaciones en su propia transacción. Ante incompatibilidad revierte su DDL y exige
migración manual; no hace DROP ni altera tablas analíticas. Debe invocarse sin
transacción previa. Si ya hay una, BEGIN falla sin confirmar el trabajo del llamador.
La comprobación estructural no es un migrador general ni certifica constraints
editadas manualmente o archivos de una publicación antigua.

| Tabla | Campos / claves | Motivo |
|---|---|---|
| run_publications | PK(run_id, attempt); phase, snapshot_id nullable, outcome, error nullable | Una fila por intento; separa progreso y fallo, conserva intentos previos. CHECK de intento positivo, vocabularios y snapshot según fase. Las reglas combinadas se validan además con RunState. |
| publication_state | PK(slot), CHECK slot='analytics'; run_id, attempt positivo, snapshot_id y artifact_manifest_sha256 NOT NULL | Reservada para la única generación de tablas declarada; empieza vacía. **No tiene helper de escritura en esta entrega**. No valida manifiestos ni promueve nada. |

No se duplican ventana, conteos o timestamps del pipeline original ni se escribe
su auditoría. El error por intento sí se almacena aquí: debe poder probarse en una
DB vacía sin crear pipeline_runs, y no es el resultado general del pipeline legado.
No hay FK a pipeline_runs porque el módulo no depende de su inicialización. Una
eventual asociación de publication_state al intento efectivo se resolverá con T2,
no con un insert simulado ahora. Las consultas usan nombres SQL constantes y valores
parametrizados; ningún helper acepta schema/nombre de tabla del usuario.

`get_run` consulta un intento; `get_publication_state` devuelve None si está vacío.
`assess_existing_state` **nunca devuelve verificado/publicado**: devuelve empty
sin evidencia previa, o requires_reconciliation ante tablas RAW/analíticas,
relaciones ajenas/desconocidas o metadatos de ejecución/publicación. Es conservador incluso
si las tablas están vacías. No lee latest/exports ni convierte el último success
en publicación: la coherencia completa requiere una migración futura validada.

No añadir el DDL a schema.sql/initialize: la POC llama ese inicializador y debe
conservar sus diez tablas originales. Importar publication no crea archivos ni tablas.

## Exclusión cooperativa y destinos

`PublicationTarget(database, output_root, allowed_root)` exige rutas absolutas
locales dentro de una raíz explícita existente. Resuelve enlaces y `..`, normaliza
case en Windows, exige sufijo .duckdb/padre existente y rechaza red/dispositivo,
archivo de salida, directorio DB y alias hardlink de DB existente. No crea DB ni
directorio de salida. La raíz la autoriza el llamador: no es una política de permisos
del sistema ni impide cambios de rutas/enlaces por un tercero.

La identidad es la ruta canónica (no un UUID de contenido DB). El lock adyacente
`.publication-<SHA256 de la ruta>.lock` es estable; mover/copiar DB+directorio de
locks exige revisión, no se presenta como la misma identidad automáticamente.

`PublicationLock` mantiene un descriptor abierto; Windows usa msvcrt.LK_NBLCK
sobre el byte 0 y POSIX usa flock EX|NB. Si hay propietario, LockBusyError inmediato:
no hay polling, sleep ni timeout implícito del CRT. No es reentrante. Al salir,
incluidas excepciones/errores de vinculación, cierra el descriptor y libera el lock.
No elimina/recrea el archivo ni inspecciona/mata PIDs.

Después del byte reservado, un JSON versionado vincula DB canónica y output_root,
escrito/sincronizado bajo lock en la primera adquisición y comparado en siguientes
sesiones/procesos. Otra raíz o JSON truncado/incompatible producen
ReconciliationRequired, sin sobrescritura. No es latest ni un manifiesto publicado.
No borrar el lock estable para «corregir» una raíz: se perdería esa vinculación.
El archivo puede permanecer aunque nadie posea el bloqueo; su existencia no impide
adquirirlo. Los locks de tests se limpian solo al eliminar su sandbox privado cerrado.

Esto excluye únicamente cooperadores que usan la misma identidad/ruta estable.
No protege frente a DuckDB directo, renombres/borrados externos, reinicios del
coordinador con hijo dbt activo, ni almacenamiento compartido/sincronizado.
No se certifica OneDrive, NAS o carpetas de red. El lock nunca abre DuckDB.

## Ejemplo exclusivamente sintético

Usar un TEMP local verificado. No sustituir estas rutas por la DB real:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import duckdb
from service_analytics.publication import (
    PublicationTarget, PublicationLock, RunState,
    initialize_publication, record_run, get_publication_state,
)

with TemporaryDirectory(prefix="publication-demo-") as directory:
    root = Path(directory).resolve()
    target = PublicationTarget(root / "demo.duckdb", root / "outputs", root)
    with PublicationLock(target):
        with duckdb.connect(str(target.database)) as con:
            initialize_publication(con)
            record_run(con, RunState("demo-run"))  # Solo created, sin snapshot ficticio.
            assert get_publication_state(con) is None
```

## Pruebas y próximos límites

`tests/test_publication.py` usa temp DB y procesos spawn con Pipe y barreras, no
sleeps de sincronización. Verifica estados/identidad/reintentos, DDL opt-in y rollback,
legacy success sin importar, pointer vacío/singleton, pipeline/POC sin nuevas tablas,
exclusión real en ambas direcciones, liberación ante excepción, binding, alias y
rechazo de rutas. HTTP está bloqueado explícitamente en estas pruebas.

Ejecutar desde la raíz con TEMP local:

```shell
uv run --frozen --group dbt pytest tests/test_publication.py
uv sync --frozen
uv run --frozen pytest
uv sync --frozen --group dbt
uv run --frozen --group dbt pytest
```

El baseline nuevo de Windows antes de la corrección fue 116 passed con dbt y
110 passed/6 skipped en base. La suite centrada corregida tiene 56 casos: también
cubre inmutabilidad después de retry y un escritor que lee un estado activo antes
de que otro lo convierta en terminal. Las seis omisiones base son los tests dbt
opcionales originales, que sí deben ejecutarse en el job especializado.

Tras la corrección, las suites locales completas de Windows terminaron con
**128 passed/0 skipped con dbt** y **122 passed/6 skipped sin dbt**. No hubo errores
ni cambios de dependencias. Los XML nuevos conservan esos conteos tras anonimizar.

Los resultados finales, comandos, SHA y enlaces alojados se documentan en el PR y
en el paquete externo `service-operations-phase3b1-final-review.zip`. El workflow
existente descubre todos los tests en sus cuatro jobs Ubuntu/Windows, sin cambios.
La rama nueva no activa CI por push bajo el filtro actual; el PR sí lo activa. No
se deduce éxito de la configuración: hay que revisar las ejecuciones del head real.

Los JUnit del paquete final se anonimizan sobre atributos/texto de un árbol XML y
se serializan con ElementTree; luego se parsean y cotejan conteos con el log. Esto
corrige el reemplazo textual del empaquetador externo anterior, que introducía
`<repo>` sin escapar en atributos. No se reescriben resultados para aparentar una
ejecución nueva ni se añaden scripts de empaquetado permanentes al repositorio.

Fuera de alcance: congelar entradas, invocar dbt operativo, publicar siete tablas,
escribir latest, validar manifiestos, migrar una DB real, recuperar hijos/caídas,
cutover o despliegues. Ninguna prueba de esta entrega acredita esas capacidades.
