# Power BI import and report specification

## Delivery status

The pipeline generates authentic CSV exports and a verified Matplotlib preview. No `.pbix` file was generated or validated. The native report below remains to be assembled in Power BI Desktop; the CSV schema and measure logic are implemented/documented, but DAX has not been executed in a Power BI session.

## Import one successful run

1. Run the pipeline or download a successful **Bounded public-data refresh** Actions artifact. Read `outputs/latest.json` and open the directory it identifies. Do not combine files from multiple run UUIDs.
2. In Power BI Desktop select **Get data → Text/CSV**, choose `requests.csv`, set UTF-8 and comma delimiter, then **Transform data**.
3. Set `request_id`, agency, category, borough, lifecycle, source status and resolution band to **Text**. Keep the identifier as Text even though it contains digits. Set `created_day` to **Date**, `created_at` and `closed_at` to **Date/Time**, `resolution_hours` to **Decimal Number**, and `is_valid` to **True/False**. Empty resolution values must remain null, never zero. Parse UTC provenance fields as **Date/Time/Timezone** in Power Query; they are not used to compute elapsed business durations.
4. Select **Close & Apply** and call this table `Requests`. Create the measures below. Use `Requests` for interactive KPIs: static preaggregates cannot recalculate their median when filtered by category.
5. Optionally import `request_quality_flags.csv` as `RequestQualityFlags`, `quality_issues.csv` for a fixed audit page, and `daily_metrics.csv` for an unfiltered audit/timeline cross-check. Whole-number type applies to counts; decimal to medians/ratios; Boolean to `review_volume_spike`.
6. Add a Date table, mark it as a date table, and relate `Date[Date]` (one) to `Requests[created_day]` (many), single direction. The table formula below spans the requested bounds of the recorded example, including zero-volume days. Change bounds with the run. Never use closure date as the active creation-date relationship.
7. Use `Requests[agency]`, `Requests[category]` and `Date[Date]` in slicers. Separate agency/category dimensions are unnecessary at this scale. Optionally relate `Requests[request_id]` (one) to `RequestQualityFlags[request_id]` (many), single direction from Requests. Do not turn on bidirectional filters simply to make a rule slicer affect request KPIs.
8. Keep `metrics.csv`, category/agency aggregates and `etl_demo.csv` disconnected or outside the interactive model. Use them for SQL validation/export inspection. Do not join an aggregate to requests in a way that duplicates measures.

```dax
Date = CALENDAR ( DATE(2026, 10, 1), DATE(2026, 10, 7) )

Total Requests = COUNTROWS ( Requests )

Open Requests =
CALCULATE ( [Total Requests], Requests[lifecycle] = "open" )

Closed Requests =
CALCULATE ( [Total Requests], Requests[lifecycle] = "closed" )

Unknown Status Requests =
CALCULATE ( [Total Requests], Requests[lifecycle] = "unknown" )

Resolution Eligible Requests = COUNT ( Requests[resolution_hours] )

Median Resolution Hours = MEDIAN ( Requests[resolution_hours] )

Flagged Requests =
CALCULATE ( [Total Requests], Requests[is_valid] = FALSE() )

Flagged Rate = DIVIDE ( [Flagged Requests], [Total Requests] )

Daily Requests = COALESCE ( [Total Requests], 0 )
```

Format `Flagged Rate` as a percentage; it is a fraction in DAX, whereas exported `flagged_pct` is already multiplied by 100. In a model with no rows, check how blank counts appear before choosing a display fallback. The first local live run provides expected unfiltered values in [results](results.md).

## Report layout

Use a 16:9 canvas, a light background, dark blue headings, blue demand marks and teal comparisons. Show the creation window and UTC observation time in a subtitle. Include a visible note: **Creation cohort; open count is not citywide backlog.**

| Position | Visual | Fields / behavior |
|---|---|---|
| Top row | KPI cards | Total, open, closed, unknown status, median resolution hours, eligible duration count |
| Left / top | Slicers | Date range, category and optionally agency; apply to all main visuals |
| Middle left | Line chart | Date[Date] and Daily Requests; include zero days; tooltip shows open/closed counts by creation day |
| Middle right | Horizontal category bar | Category and Total Requests, descending, top 10; show applied filters |
| Bottom left | Horizontal agency bar | Agency and Total Requests; tooltip includes median, eligible count and flagged rate |
| Bottom right | Resolution distribution | `resolution_band` and count, excluding Unavailable; sort 0–24, 24–72, 72–168, 168+; title says eligible closed requests |
| Second page | Quality audit | Flagged card/rate, rules table, request details and date/status inconsistencies; more than one rule may affect a request |

For a numeric histogram instead of bands, create numeric bins from `resolution_hours`, exclude nulls, and disclose the full range or any visual-only cap. Keep zero-hour observations. Never replace missing durations with zero. The supplied static preview shows the full eligible-duration distribution.

The optional daily review marker requires `baseline_days = 7`. Do not show early days as "no anomalies"; label them **Insufficient baseline**. Never frame the 1.5 ratio threshold as an official service target.

## Validate before sharing

With all slicers cleared, compare the cards with the same run's `metrics.csv`: status counts must sum to total, eligible count must match nonblank durations, and the median should agree within display rounding. Filter one category and compare its cards against `category_metrics.csv`; do the same for an agency. Compare the sum of dated counts against total after accounting for any invalid creation dates. Test Date and Category slicers together and inspect null/zero durations separately.

To refresh later, point every query to the **same new run directory** and update the Date bounds and subtitle. Do not append current snapshots of the same request IDs: that would duplicate counts. Desktop import/report assembly, visual interactions and these in-app checks are pending until a native Power BI session is available.
