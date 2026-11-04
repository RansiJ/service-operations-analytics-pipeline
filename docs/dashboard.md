# Interactive aggregate dashboard

**Intended public URL:** [NYC 311 | Service Operations Analytics](https://ransij.github.io/service-operations-analytics-pipeline/).
An HTTP check on November 4, 2026 returned **404**. Status:
**ready for manual publication / not verified**. Pages is already configured for
GitHub Actions, but the dashboard workflow has not been pushed to public main
and no github-pages deployment was found. Use the local build below. Earlier
publication statements are historical context, not evidence of a deployed dashboard.

The pipeline remains the source of analytical definitions. This small presentation layer reads its verified aggregates, checks their integrity and exports five Plotly figures into a static HTML/CSS page. It introduces no database, API extraction, web framework or Python server.

## Reproduce locally

From the repository root:

```shell
uv sync --frozen
uv run --frozen python -m service_analytics.dashboard
```

Open `site/index.html` directly in a browser. The builder accepts `--evidence-dir` and `--output` if another **complete, verified aggregate snapshot** is needed. Use the module command on Windows as well; it uses the existing Python interpreter and does not require a generated console-launcher executable.

The generated site contains only `index.html` and `assets/plotly.min.js`. Plotly's HTML export is used with one shared runtime copied from the locked Python package. Runtime JavaScript is about 4.85 MB uncompressed and is loaded once for all five figures; the HTML stays below 150 KB. No external fonts, CDN, data fetch or backend are required. Generated files are ignored by Git and built inside the Pages workflow.

## Data and scope

Inputs are exactly:

- `docs/evidence/metrics.csv`
- `docs/evidence/daily_metrics.csv`
- `docs/evidence/category_metrics.csv`
- `docs/evidence/agency_metrics.csv`
- `docs/evidence/quality_issues.csv`
- `docs/evidence/run_summary.json` for provenance, metric verification and CSV hashes

The current snapshot covers requests created **October 1–7, 2026**, observed **October 15, 2026 at 00:32 UTC** (October 14 at 18:32 in Costa Rica). The end boundary is October 8 exclusive. It is a creation cohort, not the citywide backlog. No individual request records are read or published by this builder. Additional request-level outputs and ETL demo rows are outside the input allowlist.

Validation checks the five CSV hashes, required columns, unique group keys, nonnegative finite counts/durations, lifecycle partitions, eligible counts, median nullability, cohort-wide quality percentage, summary agreement and agency/category totals. Daily totals account for the `missing_or_invalid_created_date` rule if present. The date spine must match the exact window. Quality rules may overlap; their counts are checked against flagged-request bounds rather than assumed additive. Missing or inconsistent inputs fail the build; they are not silently replaced with zeros.

All medians are read directly from their published aggregate. Group medians are never averaged to reconstruct the global median. See the [data dictionary](data_dictionary.md) and [recorded results](results.md) for authoritative definitions.

## Interactions and interpretation

| Component | Implemented behavior |
|---|---|
| KPI cards | Full-cohort totals, open, closed, eligible resolution median and flagged rate; denominators and unknown-status count remain visible |
| Daily volume | Hover with status counts; drag zoom, pan and reset axes through Plotly controls |
| Categories | Ranked horizontal bars; Top 5 / 10 / 15 selector applies to this chart only |
| Agencies | All agency request volumes with status-count tooltips; volume is not an effectiveness score |
| Resolution | Eligible agency medians ordered by demand, with eligible denominators on hover; agencies without eligible intervals are omitted |
| Quality | Flagged cohort count and requests affected per rule; flags may overlap and flagged rows remain in the cohort |

Controls do not cross-filter the page. Zooming or changing Top N does not recalculate KPI cards. Shared date/category filters are intentionally absent because these aggregates cannot support all recalculations, particularly a filtered median. There are no live data updates.

Unresolved requests are excluded from resolution statistics, and request mix, cohort age and source practices differ between agencies. These comparisons are not an official performance ranking or SLA assessment. The original static Matplotlib preview is retained in the README.

## Deployment and snapshot updates

`.github/workflows/pages.yml` installs locked dependencies, runs the full offline tests, builds `site`, uploads the official Pages artifact and deploys it with `actions/deploy-pages`. Only the deploy job has `pages: write` and `id-token: write`; build uses read-only repository access. Repository Pages configuration uses the **GitHub Actions** publishing source.

Pushes affecting the builder, its template, evidence, dependency files, dashboard tests or Pages workflow deploy the committed snapshot. Manual `workflow_dispatch` is also supported. Existing CI and data-refresh workflows are preserved. A successful data-refresh artifact does **not** automatically replace dashboard evidence: review and publish a coherent set of aggregates plus its matching summary to update the snapshot. No NYC API call occurs during dashboard generation or deployment.

## Publication status and manual steps

Read-only checks in phase 2.5 found `has_pages=true`, `build_type=workflow`, public
main at `5dc3143`, only CI/data-refresh workflows remotely and no github-pages
deployments. The feature branch is not on origin. This explains the current
publication blocker without assuming that Pages is disabled or configured incorrectly.
The existing pages.yml needs no code change: pinned actions resolve, site/ is the
upload path, build permissions are read-only, and Pages/OIDC writes belong to deploy.

After authorization to publish:

1. Review/commit the local changes and push `feature/dbt-analytics-layer`. Open a PR
   and wait for the four base/dbt Ubuntu/Windows CI checks. No remote dbt run is
   verified yet; the proposed workflow can also be dispatched on the feature ref.
2. Once those checks pass and merge is authorized, merge the reviewed changes to main.
3. In **Settings → Pages → Build and deployment**, verify **Source: GitHub Actions**.
   That value is already set according to the API; no change was made here.
4. In **Actions → Deploy analytics dashboard → Run workflow**, select main and
   run it if the matching main push did not trigger it. Confirm both build and
   deploy succeed and record the run URL.
5. Check the public HTML and `assets/plotly.min.js` return 200; inspect populated
   charts and relative asset loading on desktop and mobile. Only then label the
   dashboard verified deployed and promote its public link in the README.

Do not run the ingestion workflow to publish this fixed dashboard. No push, merge,
workflow dispatch, Settings change or deployment occurred during stabilization.

## Verification and limits

The original dashboard delivery recorded **60 passing pytest cases**, including
22 dashboard cases for evidence reading, missing/malformed inputs, numeric integrity,
aggregate reconciliation, metadata interpretation, null medians, actual figure data,
local Top N controls, HTML generation and safe label escaping. Tests verify five
populated figures, one local runtime reference, expected KPI values, unique chart
IDs and absence of exported row-level CSVs. Current counts and platform limits are
reported separately in [phase 2.5 validation](validation/stabilization_phase2_5.md).

Browser automation was attempted through the available browser tools; no browser was connected, and both the integrated browser and Chrome reported unavailable. Browser rendering, hover/zoom interactions and mobile visual layout have therefore **not been visually verified** in this session. The responsive layout, Plotly controls and static export are implemented, with structural tests; these do not substitute for in-browser QA. No browser screenshot is claimed.

The site can be HTTP-checked independently of visual QA. The deployment workflow's result, public URL response and referenced JavaScript asset are checked after publication. Static snapshot age and unresolved-case bias remain analytical limitations even when the site deploys successfully.
