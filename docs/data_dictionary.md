# Data dictionary and metric definitions

## Model scope and grains

`raw_requests` has one row per source `unique_key`, with the latest payload observed locally. Its original selected fields are VARCHAR, including dates; `source_payload` is JSON, `fetched_at` is TIMESTAMPTZ and `last_run_id` identifies the last observation. RAW does not claim to preserve every historical version.

`run_members` has one `(run_id, unique_key)` pair per accepted input ID. `raw_rejections` stores the run, one-based source row number, original JSON and `missing_identifier` reason for unidentifiable rows. They cannot enter request-level metrics. Numeric or blank IDs are rejected by the loader; the public endpoint uses text IDs.

`requests` has one row per identifiable request in the current run. Flagged requests remain here. `is_valid = true` means that none of the implemented rules triggered; it does not certify factual correctness of the source. There is no separate duplicate "valid requests" table: filter `is_valid` when needed.

## Request fields

| Column | DuckDB type / Power BI type | Definition |
|---|---|---|
| `request_id` | VARCHAR / Text | Stable public `unique_key`; never treat as a sum or sequential time index |
| `created_at` | TIMESTAMP / Date/Time | Parsed source creation time; NYC local, no timezone; null if missing/invalid |
| `closed_at` | TIMESTAMP / Date/Time | Parsed source closure time; null if missing/invalid |
| `created_day` | DATE / Date | Calendar date derived from `created_at` |
| `agency` | VARCHAR / Text | Uppercase agency code with collapsed whitespace; `UNKNOWN` fallback |
| `agency_name` | VARCHAR / Text | Trimmed display name; `Unknown` fallback; agency code is the grouping key |
| `category` | VARCHAR / Text | Normalized `complaint_type`; no semantic category merging |
| `borough` | VARCHAR / Text | Trimmed uppercase source borough; `UNKNOWN` fallback; source `Unspecified` remains `UNSPECIFIED` |
| `source_status` | VARCHAR / Text | Normalized original status; `UNKNOWN` for missing/blank |
| `lifecycle` | VARCHAR / Text | `closed`: CLOSED; `open`: OPEN, IN PROGRESS, ASSIGNED, STARTED, PENDING; other values: `unknown` |
| `resolution_hours` | DOUBLE / Decimal Number | `(closed_at - created_at)` wall-clock hours for `closed` requests with both valid timestamps and `closed_at >= created_at`; otherwise null; zero is valid |
| `source_updated_at` | TIMESTAMPTZ / Date/Time/Timezone | Socrata `:updated_at`; ingestion/update provenance, not a guaranteed status-transition timestamp |
| `observed_at` | TIMESTAMPTZ / Date/Time/Timezone | UTC time after the complete API extraction |
| `quality_flags` | VARCHAR[] / Not in request CSV | List of triggered rule names; exported separately as request/rule pairs |
| `is_valid` | BOOLEAN / True/False | True exactly when quality flag list is empty |
| `resolution_band` | VARCHAR / Text | `[0,24)`, `[24,72)`, `[72,168)`, `[168,infinity)` hours, or `Unavailable` |

`descriptor` and `resolution_action_updated_date` remain in RAW as original selected source fields. They are not needed for this compact dashboard. Timestamps with timezone suffixes are not part of the source business-date contract; ETL expects NYC floating ISO dates.

## Quality rules

| Rule | Trigger |
|---|---|
| `missing_or_invalid_created_date` | Creation timestamp cannot be parsed or is absent |
| `invalid_closed_date` | Nonblank closure value cannot be parsed |
| `negative_resolution_interval` | Parsed closure precedes parsed creation |
| `closed_without_date` | Normalized closed lifecycle has no valid closure timestamp |
| `open_with_closed_date` | Normalized open lifecycle has a parsed closure timestamp |
| `unknown_status` | Status is missing or outside the explicit open/closed mapping |
| `missing_agency` | Normalized agency is UNKNOWN |
| `missing_category` | Normalized category is UNKNOWN |

Multiple rules can apply to one request. `quality_issues.affected_requests` counts rows per rule; summing it can exceed `flagged_requests`. The quality rate denominator is all identifiable requests, not the number of extracted source rows. Negative intervals are flagged regardless of status. A missing agency/category does not automatically invalidate an otherwise eligible resolution interval: duration eligibility and all-rule validity are separate concepts.

## Metrics and denominators

| Metric | Definition / denominator |
|---|---|
| `total_requests` | Count of identifiable current-cohort requests, including flagged rows |
| `open_requests` | Count with lifecycle `open`; a cohort open count at observation, not a citywide backlog |
| `closed_requests` | Count with lifecycle `closed`, including closure-date inconsistencies |
| `unknown_status_requests` | Count with lifecycle `unknown`; open + closed + unknown = total |
| `resolution_eligible_requests` | Count of nonnull `resolution_hours` |
| `median_resolution_hours` | Continuous median of nonnull `resolution_hours`; null if no eligible rows; for an even count, average of middle values |
| `valid_requests` | Count with zero implemented quality flags |
| `flagged_requests` | Count with at least one flag |
| `flagged_pct` | 100 × flagged / total; null for an empty cohort |
| Category / agency volume | Count of requests in each normalized grouping; totals reconcile to cohort total |
| Daily volume | Count by creation day, including all requested days through a date spine; invalid creation dates cannot appear on the daily timeline |

`metrics` is one cohort-wide row. `daily_metrics` groups by creation day, `category_metrics` by category and `agency_metrics` by agency. All include total, open, closed, unknown, eligible resolution count, median and flagged count (except `valid_requests` and percentage, which are cohort-wide only).

Daily closed/open counts refer to the **current status of requests created on that day**. They are not the number of closures performed on that day. A category-level median is not additive; do not average medians to reconstruct the global median.

Daily review fields:

- `previous_7day_mean`: mean volume over up to seven prior calendar days, excluding the current day.
- `baseline_days`: number of available prior days, from zero to seven.
- `volume_ratio`: current volume / prior mean only when all seven baseline days exist and the mean is positive; otherwise null.
- `review_volume_spike`: true only with a complete baseline and a ratio >= 1.5. This heuristic is configurable only by editing SQL and is not an official target or statistical test. False with insufficient history means **not evaluated**, not evidence of normality; consult `baseline_days`.

## Run audit and output provenance

`pipeline_runs`: UUID `run_id`; UTC start/finish timestamps; inclusive `window_start`; exclusive `window_end`; `running`, `success` or `failed` status; source count; extracted, loaded (distinct accepted), rejected (missing identifier), duplicate (extra accepted-ID occurrences), flagged counts; bounded error text. On a completed load, extracted = loaded + rejected + duplicate. If a transaction fails, loaded/flagged counters remain zero after rollback. If extraction fails before returning a complete cohort, extracted count stays zero even if HTTP pages were received; progress logs record those pages. No partial extraction is loaded.

`run_summary.json` records API URL, bounds, observation time, counters, metrics, warnings, ETL comparison and SHA-256 for every CSV. Each immutable output directory has its run UUID. `outputs/latest.json` locates the most recently published directory. Request CSV hashes change when observation timestamps change; aggregate business outputs are repeatable for identical input.

`etl_demo` has `request_id`, `created_at`, `closed_at`, `lifecycle`, `resolution_hours` and `date_status_issues` (list, omitted from its CSV). It is a comparison target, not a second source for the main report. Its Python transform returns missing-ID rejects; the orchestrator also preserves those source rows in the main RAW rejection table.
