# ADR-002 — Parallel migration of analytical SQL to dbt

Accepted for phase 2, 2026-11-04. Project version remains 1.0.0.

## Context and decision

The original pipeline owns extraction, RAW UPSERT, cohort membership, transaction,
ETL comparison and publication. Phase 1 introduced one staging model on a synthetic
DuckDB snapshot. Phase 2 migrates the remaining analytical SELECTs in parallel;
`pipeline.py`, `transform.sql`, ingestion and dashboard code remain the reference.

The mapping below was established before implementing the models.

| Original block/table | dbt model | Grain / rules to preserve |
|---|---|---|
| `normalized` CTE | `stg_service_requests` (existing) | One accepted ID in explicit membership; original TRY_CAST and cleaning order; provenance retained. |
| `classified` CTE | `int_service_requests_classified` | Same ID; floating NYC `created_day`; CLOSED → closed; OPEN, IN PROGRESS, ASSIGNED, STARTED, PENDING → open; otherwise unknown. |
| `flagged` CTE + final `requests` SELECT | `fct_service_requests` | Same ID; ordered list of eight overlapping rules; eligible hours only for closed with valid nonnegative interval; validity and bands. |
| `metrics` | `mart_overall_metrics` | One row, including empty cohorts; counts, eligible median and flagged percentage over all accepted IDs. |
| `daily_metrics` | `mart_daily_metrics` | One row per requested calendar day, end exclusive; zero days; previous seven rows including zeros; ratio only with seven days and positive mean; inclusive 1.5 threshold. |
| `category_metrics` | `mart_category_metrics` | One normalized category; original counts, eligible median and flagged count. |
| `agency_metrics` | `mart_agency_metrics` | One normalized agency; same measures as category. |
| `quality_issues` | `mart_quality_issues` | One triggered rule; unnest lists without treating overlapping flags as disjoint. |

The single intermediate model is ephemeral: it names the classification boundary
without adding another stored table. Staging, fact and five marts are tables in
`dbt_staging`. No star schema, dimension models or separate flagged/valid tables
are needed. `ref()` links analytical layers; `source()` is limited to RAW/audit
and POC metadata. The fact excludes staging-only run/snapshot columns so its column
names, types and values match historical `requests`; staging retains traceability.

## Semantic contracts

- Malformed/missing dates remain null. Unknown statuses and anomalous requests
  remain in the fact, with all applicable flags. No timezone reinterpretation.
- Duration eligibility is independent of other quality flags. Zero hours is valid;
  null is never zero. Bands remain [0,24), [24,72), [72,168), >=168 and Unavailable.
- Global quality uses accepted requests as denominator. Medians use eligible
  durations and are never reconstructed by averaging group medians.
- Daily totals exclude null creation dates; aggregation only covers the selected
  audit window. Prior RAW observations outside membership do not enter the models.
- Preserve the original order trim → whitespace collapse → uppercase, including
  unusual whitespace edge cases. Do not alter rules to make parity pass.

## Alternatives and consequences

Keeping a single dbt model with all original DDL would hide dependencies and defeat
the migration. Splitting every CTE into a stored table would add redundant storage
and interfaces. The chosen eight-model DAG names meaningful boundaries with one
ephemeral intermediate and six final outputs; there are seven stored dbt tables.

Deliberate duplication of original SQL temporarily provides an independent oracle.
Full verification compares schemas and unordered row multisets for all six outputs,
including nulls, timestamps, lists and every aggregate column. Equality is exact:
the same pinned DuckDB engine evaluates the same expressions on the same snapshot,
so no floating-point tolerance is introduced. A mismatch requires investigation.

Phase 1's staging verifier remains callable for compatibility; the `verify` CLI
must now check full parity. Add fixtures for short/empty cohorts, seven zero days,
the exact spike threshold, overlapping flags and band boundaries. Keep existing
tests and add deliberate model corruption checks so equal counts cannot hide errors.

The snapshot guard must also run during parsing, before dbt creates schemas, to
reject an operational filename before opening it for a build. It is an experiment
guard, not a permission system. Preserve the existing source fingerprints and
validate all ten original test tables after each successful parity check.

No production transaction is transferred to dbt. Single-threaded dbt does not solve
multi-process DuckDB writes. Coordinating writers, committing/publishing atomically,
failure recovery and the final operational cutover remain phase 3 decisions.

## Scope and validation record

Use the existing optional Core 1.12.6 / dbt-duckdb 1.11.1 group and DuckDB 1.5.6;
no new dependencies or workflow changes. Linux dbt CI will be proposed only if
local cross-platform execution cannot be verified. Tests follow the supported
[dbt data_tests contract](https://docs.getdbt.com/reference/resource-properties/data-tests).

Results, initial Git state and remaining limitations belong in
[dbt_full_parity.md](../validation/dbt_full_parity.md). See
[ADR-001](ADR-001-dbt-integration.md) for the engine choice and
[integration guide](../migration/dbt_integration.md) for reproduction.
