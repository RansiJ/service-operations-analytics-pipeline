# Actual results and verification

## Provenance

These are actual public API results, not fixture or simulated data. The creation window is **October 1, 2026 00:00:00 inclusive to October 8, 2026 00:00:00 exclusive**, in NYC floating local time. The second local run observed the cohort at **2026-10-15 00:32:06 UTC**, equivalent to **October 14, 2026 18:32:06 in Costa Rica**. Source statuses are those observed at extraction, not historical statuses at the window end.

Two complete live API runs were executed with:

```shell
uv run --frozen service-analytics --start 2026-10-01 --end 2026-10-08 --max-records 100000 --page-size 5000
```

The endpoint returned 78,466 requests in 16 pages in each run. Counts before and after each extraction matched. [API verification](evidence/api_verification.json), [run summary](evidence/run_summary.json) and [repeat-run verification](evidence/repeat_run_verification.json) preserve the evidence. No request-level dataset is tracked in Git.

## Cohort indicators

| Indicator | Actual value |
|---|---:|
| Extracted / distinct loaded | 78,466 / 78,466 |
| Open | 17,360 |
| Closed | 61,098 |
| Unknown status | 8 |
| Eligible nonnegative closure durations | 61,053 |
| Median eligible closure duration | 3.3908333333 hours |
| Requests without implemented quality flags | 76,600 |
| Requests with at least one flag | 1,866 |
| Flagged percentage | 2.3781000688% |
| Missing-ID rejections / input duplicates | 0 / 0 |
| ETL comparison subset | 1,000 |
| ETL/ELT field mismatches | 0 |
| Median on that identical ETL/ELT subset | 2.1325 hours |

The subset median is not expected to match the full-cohort median: the subset contains the first 1,000 text-ordered IDs and is not a representative sample.

## Demand and resolution interpretation

The largest category by volume was **ILLEGAL PARKING: 13,664** requests, followed by **NOISE - RESIDENTIAL: 7,999**. The largest agency by volume was **NYPD: 36,351**, followed by **HPD: 15,752**. Observed median eligible durations were about **1.42 hours for NYPD** and **63.04 hours for HPD**. These differences do not establish relative effectiveness: request mix, reporting practices, cohort age and unresolved cases differ.

Daily volume ranged from **9,053 on October 4** to **12,017 on October 1**. This seven-day cohort is too short to evaluate the seven-prior-day volume review heuristic, and it cannot establish a seasonal pattern. The implemented SQL test verifies that the marker activates on a deterministic eight-day fixture; that fixture is not an actual operational finding.

## Data quality findings

| Rule | Affected requests |
|---|---:|
| `open_with_closed_date` | 1,813 |
| `negative_resolution_interval` | 44 |
| `unknown_status` | 8 |
| `closed_without_date` | 1 |

In this run these counts total 1,866; the general rules can overlap. Open requests with a closure date warrant checking source definitions and lifecycle history before interpreting them. The pipeline retains them, classifies lifecycle by source status, flags the inconsistency and excludes them from resolution durations. The 44 negative intervals and one closed request without a valid date explain why eligible durations are fewer than closed requests. No cause is inferred.

## Repeatability and tests

After two real runs, RAW contained **78,466 rows and 78,466 distinct IDs**, rather than double that number. The two runs had identical metrics and identical hashes for seven CSVs (all except `requests.csv`). Request business columns also had identical canonical hashes after excluding only `observed_at`; that observation timestamp intentionally changes on each refresh. Both local audit rows reported `success`.

**38 offline pytest cases** pass locally on Python 3.12. They include mocked extraction, SQL quality/metric checks, ETL parity, duplicate prevention, changed-status UPSERT, failed API audit, failed transformation rollback, failed export rollback, anomaly baseline gating and end-to-end export repeatability. Package build and an isolated wheel SQL-resource check also pass. GitHub Actions independently executes the suite on Linux and Windows after publication.

## Artifacts and practical limits

The [static preview](evidence/dashboard_preview.png) was visually inspected. Small real [aggregate CSV snapshots](evidence/) are included for review. Full Power BI request exports remain in the ignored local `outputs` directory or downloadable successful Actions artifacts.

The source is mutable and paginated reads are not atomic. Repeating this historical window later may yield different states and metrics. The open count is a cohort statistic, not a citywide backlog. Resolution times use source local wall-clock dates and exclude unresolved requests; they should not be treated as unbiased estimates of eventual resolution time. No official SLA, causal finding, speedup, native Power BI report or measured production availability is claimed.
