# Original pipeline: operation and outputs

This is the existing operational path; dbt runs separately on a synthetic POC.
Run commands from the repository root. See the [README](../README.md) for the
short offline path and the [dictionary](data_dictionary.md) for metric definitions.

## Extraction and controlled refresh

```shell
uv sync --frozen
uv run --frozen service-analytics --start 2026-10-01 --end 2026-10-03 --max-records 25000 --page-size 5000 --etl-sample-size 500
```

Live execution queries the public Socrata `erm2-nwe9` endpoint. It selects only
the fields required by this project, excluding addresses, coordinates and narratives.
Dates define a bounded creation cohort: inclusive start, exclusive end, 1–31 days.
The configurable download cap cannot exceed 100,000 rows; page size is 1–10,000.
The source is counted before download and after text-ID keyset pagination. Missing,
duplicate, nonascending IDs, schema drift or inconsistent counts fail the run.
Transient HTTP/network errors have three attempts with bounded backoff and timeouts.
The public API offers no cross-request snapshot isolation.

Without dates, the CLI selects the NYC calendar day before yesterday to allow
publication lag. This does not guarantee source completeness. `--database` defaults
to `data/service_operations.duckdb`, and `--output` to `outputs`.

Each refresh rereads the bounded window. RAW UPSERT retains the latest observed
payload per ID; `run_members` preserves exact run membership. Old RAW rows do not
leak into current analytics, but historical payload versions cannot be reconstructed.
Refresh old windows explicitly to capture later closures. Audit/output retention
is manual; no automatic cleanup is implemented.

## Transactions, audits and publication

One writer is supported. RAW, membership, SQL models, QA, the ETL comparison and
staged exports run in a DuckDB transaction. Failures roll back those data changes;
the failed run audit survives outside that transaction. Missing IDs are quarantined,
while identifiable anomalous records remain with their quality flags.

After COMMIT, the staging directory is renamed to an immutable run-UUID directory,
`outputs/latest.json` is replaced and the audit becomes success. Filesystem and DB
publication are separate operations: after an error, inspect `pipeline_runs.status`,
the reported error and output directories before consuming them. A post-COMMIT
filesystem failure can leave committed data with a failed/incomplete publication.

The ETL demonstration uses the first 1,000 extracted IDs by default (configurable
1–5,000). Python parses dates/classifies lifecycle before loading `etl_demo`; the
orchestrator compares dates, lifecycle and hours with ELT for the same IDs. This
is a teaching subset, not a representative sample or a second analytical source.

## Per-run outputs

| File | Grain / purpose |
|---|---|
| `requests.csv` | Current-cohort requests; quality list exported separately |
| `metrics.csv` | Cohort-wide counts, eligible median and quality percentage |
| `daily_metrics.csv` | Every requested day, including zeros and baseline fields |
| `category_metrics.csv`, `agency_metrics.csv` | Normalized group counts and eligible medians |
| `quality_issues.csv` | Frequency per rule; flags can overlap |
| `request_quality_flags.csv` | One request/rule pair |
| `etl_demo.csv` | Limited Python-before-load comparison target |
| `run_summary.json` | Run/window provenance, counts, warnings, ETL comparison and SHA-256 for eight CSVs |
| `dashboard_preview.png` | Existing Matplotlib preview |

Identical input yields identical aggregate business CSVs. Run IDs and observation
timestamps intentionally change. Row-level exports, databases, logs and generated
outputs are ignored by Git; only small recorded aggregate evidence is committed.

## Existing automation

CI runs offline tests on Windows/Linux and checks packaged SQL on Linux. The
bounded refresh workflow supports manual windows or Monday 10:23 UTC / 04:23 Costa
Rica with a 25,000-row scheduled cap; artifacts are retained for 14 days. Runners
are ephemeral and do not reuse the local RAW database.

The separate Pages workflow builds the dashboard from committed aggregates. It
does not query NYC 311, adopt refresh artifacts or depend on dbt. Source outages,
rate limits, schema changes and caps can fail a live refresh; CI does not prove
source availability. See [dashboard status and build](dashboard.md) and the
[historical hosted-run evidence](results.md).
