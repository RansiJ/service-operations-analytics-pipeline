# ADR-003: estados de publicación y lock cooperativo opt-in

Decisión para fase 3B, entrega 1. Estado: implementado localmente, inactivo en el
camino operativo; pendiente de revisión/publicación. Versión 1.0.0 sin cambios.

## Contexto

La fase 3A propuso B simplificada: una base, cohorte congelada, dbt candidato y
promoción controlada. Esta entrega solo construye sus fundamentos. La transacción
original agrupa RAW/SQL/ETL/export; el nuevo módulo no altera esa garantía ni
confunde una fase declarada con una publicación real. Los snapshots y T2 aún no existen.

## Decisión

- Un módulo publication.py, enums/RunState inmutable y helpers explícitos, sin
  import ni llamada desde pipeline. Transiciones adyacentes; fase, intento y
  outcome/error separados. Error posterior a tables_committed exige reconciliación.
- DDL opt-in propio: run_publications por (run_id, attempt), publication_state
  singleton vacío. No hay escritor del pointer ni importación de legacy success.
  Inicialización transaccional idempotente, columnas/PK verificadas y error explícito
  para esquema incompatible; no migración automática ni DROP.
- Un archivo estable adyacente a la DB canónica y descriptor bloqueado de forma
  no bloqueante. Byte de lock reservado, binding JSON de DB/output escrito después
  de adquirir exclusión. No se borra el archivo al liberar: conserva identidad y
  evita crear otro inode mientras haya un propietario.
- Solo biblioteca estándar msvcrt/fcntl; no reintento interno ni daemon. Pipes
  sincronizan tests de procesos reales con timeouts de seguridad.

Se justifican el error por intento y PK compuesta frente al diseño inicial por run:
permiten conservar fallos previos sin modificar pipeline_runs ni duplicar sus
conteos/ventana. El historial de intentos es pequeño; no se añade un event log.
El binding persistente usa el mismo archivo del lock; evita una tercera tabla o
sidecar de configuración y funciona sin abrir DuckDB. No es una migración de datos.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Añadir tablas al initialize/schema original | Cambiaría las diez tablas de referencia POC y activaría metadatos incidentalmente |
| Un único status success/failed | Pierde la fase alcanzada y no expresa incertidumbre posterior a T2 |
| Lock por exists/PID/edad con unlink | No representa propiedad OS; permite carreras y pérdida del binding |
| Espera/retry de duración interna | No es necesaria para esta entrega; fail-fast ofrece comportamiento comprobable y evita esperas ocultas |
| Librería de locks nueva o servidor | Las primitivas estándar bastan para exclusión local; más dependencias/mantenimiento sin necesidad demostrada |
| Certificar legacy mediante último success | Auditoría sola no verifica coherencia con tablas, latest y archivos |

## Consecuencias y límites

El llamador futuro deberá usar el lock y sus transacciones de manera correcta;
record_run no bloquea DuckDB por su cuenta. Los nombres SQL son constantes; solo
se parametrizan valores. El schema valida estructura/PK, no es un verificador
general de toda alteración manual de constraints. La inspección de legacy es
deliberadamente conservadora, sin afirmar que un registro published acredite archivos.

La ruta autorizada la declara el llamador. Paths resueltos/binding no son una
barrera contra un tercero que cambie enlaces, borre el lock o escriba DuckDB.
No se certifica almacenamiento sincronizado/red, alias hardlink ni traslado de una
DB conservando identidad. La terminación de hijos y la recuperación completa se
posponen; un descriptor liberado no prueba que no quede un futuro dbt huérfano.

Coste: mantener un módulo y su schema fijo, dos variantes OS pequeñas y pruebas
de IPC. No hay cambios de CLI, workflow, métricas ni dependencias. Futuras columnas
exigirán migración revisada; la incompatibilidad se rechaza en lugar de improvisarla.

Windows se probó localmente. Ubuntu queda pendiente de ejecución real: tener una
rama fcntl y tests portables no constituye evidencia de compatibilidad aprobada.
Detalles de API, tests, ejemplo sintético y exclusiones en
[phase3b1_foundations.md](../migration/phase3b1_foundations.md).

Referencias primarias: [msvcrt.locking Python 3.12](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking)
para región por descriptor/modo inmediato y [fcntl.flock Python 3.12](https://docs.python.org/3.12/library/fcntl.html#fcntl.flock)
para exclusión no bloqueante Unix. Las pruebas locales, no esas páginas, acreditan
el resultado Windows de esta entrega.
