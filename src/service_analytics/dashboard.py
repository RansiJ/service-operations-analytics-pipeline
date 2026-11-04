"""Build an offline-capable Plotly dashboard from verified aggregate evidence only."""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import escape
from importlib.resources import files
import io
import json
import math
from pathlib import Path
import re
import textwrap

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

REPOSITORY = "https://github.com/RansiJ/service-operations-analytics-pipeline"
COUNTS = ("total_requests", "open_requests", "closed_requests", "unknown_status_requests",
          "resolution_eligible_requests", "flagged_requests")
INPUTS = ("metrics", "daily_metrics", "category_metrics", "agency_metrics", "quality_issues")
BLUE, TEAL, INK = "#2455b5", "#147d82", "#182b45"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, *, integer=False, nullable=False):
    if nullable and value == "":
        return None
    try:
        result = int(value) if integer else float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Malformed numeric value: {value!r}") from exc
    require(math.isfinite(result) and result >= 0, "Counts and durations must be finite and nonnegative")
    return result


def load_evidence(directory):
    """Check provenance, input hashes and existing metric invariants; never call the API.

    Medians are read as published. Group medians are deliberately not combined.
    Only the five allowlisted aggregate CSVs can reach the dashboard builder.
    """
    directory = Path(directory)
    try:
        summary = json.loads((directory / "run_summary.json").read_text(encoding="utf-8"))
        require(isinstance(summary, dict) and summary.get("status") == "success", "Snapshot must be a successful pipeline run")
        start = date.fromisoformat(summary["window_start"])
        end = date.fromisoformat(summary["window_end_exclusive"])
        observed = datetime.fromisoformat(summary["observed_at"].replace("Z", "+00:00"))
        require(start < end and observed.tzinfo is not None, "Invalid snapshot window or missing observation timezone")
        tables = {}
        for name in INPUTS:
            raw = (directory / f"{name}.csv").read_bytes()
            require(hashlib.sha256(raw).hexdigest() == summary["csv_sha256"][f"{name}.csv"],
                    f"Snapshot hash mismatch: {name}.csv")
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            label = {"daily_metrics": "created_day", "category_metrics": "category",
                     "agency_metrics": "agency", "quality_issues": "rule"}.get(name)
            needed = {"rule", "affected_requests"} if name == "quality_issues" else {*COUNTS, "median_resolution_hours"}
            if label:
                needed.add(label)
            if name == "metrics":
                needed.update(("valid_requests", "flagged_pct"))
            require(needed <= set(reader.fieldnames or []), f"Missing columns: {name}.csv")
            rows = list(reader)
            seen = set()
            for row in rows:
                require(None not in row and all(row[k] is not None for k in needed), f"Malformed CSV row: {name}")
                if label:
                    require(row[label].strip() and row[label] not in seen, f"Missing or duplicate {label}")
                    seen.add(row[label])
                if name == "quality_issues":
                    row["affected_requests"] = number(row["affected_requests"], integer=True)
                    continue
                for field in COUNTS:
                    row[field] = number(row[field], integer=True)
                row["median_resolution_hours"] = number(row["median_resolution_hours"], nullable=True)
                require(sum(row[k] for k in ("open_requests", "closed_requests", "unknown_status_requests")) == row["total_requests"], f"Status counts do not reconcile: {name}")
                require(row["resolution_eligible_requests"] <= row["closed_requests"] and row["flagged_requests"] <= row["total_requests"], f"Invalid denominator: {name}")
                require((row["median_resolution_hours"] is None) == (row["resolution_eligible_requests"] == 0), f"Median eligibility mismatch: {name}")
                if name == "metrics":
                    row["valid_requests"] = number(row["valid_requests"], integer=True)
                    row["flagged_pct"] = number(row["flagged_pct"], nullable=True)
            tables[name] = rows
        require(len(tables["metrics"]) == 1, "metrics.csv must contain exactly one row")
        metrics = tables["metrics"][0]
        require(metrics["valid_requests"] + metrics["flagged_requests"] == metrics["total_requests"], "Quality partition does not reconcile")
        require(summary["loaded_count"] == metrics["total_requests"], "Loaded count differs from metrics")
        for key, value in metrics.items():
            if key not in {*COUNTS, "median_resolution_hours", "valid_requests", "flagged_pct"}:
                continue
            recorded = summary["metrics"][key]
            require((value is None and recorded is None) or
                    (value is not None and isinstance(recorded, (int, float)) and
                     math.isclose(value, recorded, rel_tol=1e-12, abs_tol=1e-10)), f"Summary metric mismatch: {key}")
        expected_pct = 100 * metrics["flagged_requests"] / metrics["total_requests"] if metrics["total_requests"] else None
        require((expected_pct is None and metrics["flagged_pct"] is None) or
                (expected_pct is not None and metrics["flagged_pct"] is not None and
                 math.isclose(expected_pct, metrics["flagged_pct"], abs_tol=1e-10)), "Quality percentage does not reconcile")
        for name in ("category_metrics", "agency_metrics"):
            for field in COUNTS:
                require(sum(r[field] for r in tables[name]) == metrics[field], f"{name} totals do not reconcile: {field}")
        days = sorted(date.fromisoformat(r["created_day"]) for r in tables["daily_metrics"])
        require(days == [start + timedelta(days=i) for i in range((end - start).days)], "Daily date spine differs from snapshot window")
        rules = tables["quality_issues"]
        undated = sum(r["affected_requests"] for r in rules if r["rule"] == "missing_or_invalid_created_date")
        require(sum(r["total_requests"] for r in tables["daily_metrics"]) + undated == metrics["total_requests"], "Daily totals do not reconcile, including undated requests")
        for field in COUNTS:
            daily_total = sum(r[field] for r in tables["daily_metrics"])
            require(daily_total <= metrics[field] and (undated > 0 or daily_total == metrics[field]), f"Daily totals do not reconcile: {field}")
        require(all(r["affected_requests"] <= metrics["flagged_requests"] for r in rules)
                and sum(r["affected_requests"] for r in rules) >= metrics["flagged_requests"], "Quality rule counts do not reconcile with flagged requests")
        return {"tables": tables, "metrics": metrics, "summary": summary, "start": start,
                "end": end, "observed": observed.astimezone(timezone.utc)}
    except (OSError, KeyError, TypeError, json.JSONDecodeError, csv.Error) as exc:
        raise ValueError(f"Cannot read complete dashboard evidence: {exc}") from exc


def label(value, width=28):
    return "<br>".join(escape(part) for part in textwrap.wrap(value, width=width))


def style(figure, *, left=55, top=25, height=360):
    figure.update_layout(template="plotly_white", height=height, autosize=True,
                         font=dict(family="Arial, sans-serif", color=INK, size=12),
                         margin=dict(l=left, r=50, t=top, b=58), paper_bgcolor="rgba(0,0,0,0)",
                         plot_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(bgcolor="#ffffff"),
                         dragmode="zoom", showlegend=False)
    figure.update_xaxes(gridcolor="#edf0f5", zeroline=False, automargin=True)
    figure.update_yaxes(gridcolor="#edf0f5", zeroline=False, automargin=True)
    return figure


def make_figures(evidence):
    tables = evidence["tables"]
    daily = sorted(tables["daily_metrics"], key=lambda row: row["created_day"])
    volume = go.Figure(go.Scatter(
        x=[r["created_day"] for r in daily], y=[r["total_requests"] for r in daily],
        mode="lines+markers", line=dict(color=BLUE, width=3), marker=dict(size=8),
        fill="tozeroy", fillcolor="rgba(36,85,181,0.06)",
        customdata=[[r["open_requests"], r["closed_requests"], r["unknown_status_requests"]] for r in daily],
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>%{y:,} requests<br>Open at observation: %{customdata[0]:,}<br>Closed: %{customdata[1]:,}<br>Unknown status: %{customdata[2]:,}<extra></extra>",
    ))
    style(volume, height=330)
    volume.update_xaxes(title="Creation date · NYC local time", type="date", tickformat="%b %d", nticks=7)
    volume.update_yaxes(title="Requests", rangemode="tozero", tickformat=",")

    categories = sorted(tables["category_metrics"], key=lambda r: (-r["total_requests"], r["category"]))

    def category_data(n):
        rows = categories[:n][::-1]
        return {"x": [[r["total_requests"] for r in rows]], "y": [[label(r["category"]) for r in rows]],
                "customdata": [[[escape(r["category"]), r["open_requests"]] for r in rows]]}

    initial = category_data(10)
    category = go.Figure(go.Bar(x=initial["x"][0], y=initial["y"][0], customdata=initial["customdata"][0],
                                orientation="h", marker_color=TEAL,
                                hovertemplate="<b>%{customdata[0]}</b><br>%{x:,} requests<br>Open at observation: %{customdata[1]:,}<extra></extra>"))
    style(category, left=165, top=55, height=470)
    category.update_layout(updatemenus=[dict(buttons=[dict(label=f"Top {n}", method="restyle", args=[category_data(n)]) for n in (5, 10, 15)],
                                            active=1, x=1, y=1.12, xanchor="right", yanchor="top", bgcolor="white")])
    category.update_xaxes(title="Requests", rangemode="tozero", tickformat=",")
    category.update_yaxes(type="category", categoryorder="trace", showgrid=False)

    agencies = sorted(tables["agency_metrics"], key=lambda r: (-r["total_requests"], r["agency"]))
    agency = go.Figure(go.Bar(x=[r["total_requests"] for r in agencies[::-1]],
                             y=[escape(r["agency"]) for r in agencies[::-1]], orientation="h", marker_color=BLUE,
                             customdata=[[r["open_requests"], r["closed_requests"], r["unknown_status_requests"]] for r in agencies[::-1]],
                             hovertemplate="<b>%{y}</b><br>%{x:,} requests<br>Open: %{customdata[0]:,}<br>Closed: %{customdata[1]:,}<br>Unknown: %{customdata[2]:,}<extra></extra>"))
    style(agency, left=60, height=470)
    agency.update_xaxes(title="Requests", rangemode="tozero", tickformat=",")
    agency.update_yaxes(type="category", categoryorder="trace", showgrid=False)

    eligible = [r for r in agencies if r["resolution_eligible_requests"] > 0][::-1]
    resolution = go.Figure(go.Scatter(
        x=[r["median_resolution_hours"] for r in eligible], y=[escape(r["agency"]) for r in eligible],
        mode="markers", marker=dict(size=11, color=TEAL, line=dict(color="white", width=2)),
        customdata=[[r["resolution_eligible_requests"], r["total_requests"]] for r in eligible],
        hovertemplate="<b>%{y}</b><br>Median: %{x:.2f} hours<br>Eligible closed requests: %{customdata[0]:,}<br>Total cohort requests: %{customdata[1]:,}<extra></extra>",
    ))
    style(resolution, left=60, height=380)
    resolution.update_xaxes(title="Median eligible resolution · hours", rangemode="tozero")
    resolution.update_yaxes(type="category", categoryorder="trace", showgrid=True)

    rules = sorted(tables["quality_issues"], key=lambda r: (-r["affected_requests"], r["rule"]))[::-1]
    quality = go.Figure(go.Bar(
        x=[r["affected_requests"] for r in rules], y=[label(r["rule"].replace("_", " "), 23) for r in rules],
        orientation="h", marker_color="#9b6d27", text=[f"{r['affected_requests']:,}" for r in rules],
        textposition="outside", cliponaxis=False, customdata=[escape(r["rule"]) for r in rules],
        hovertemplate="<b>%{customdata}</b><br>%{x:,} affected requests<extra></extra>",
    ))
    style(quality, left=155, height=310)
    quality.update_xaxes(title="Affected requests per rule", rangemode="tozero", tickformat=",")
    quality.update_yaxes(type="category", categoryorder="trace", showgrid=False)
    return {"volume": volume, "categories": category, "agencies": agency,
            "resolution": resolution, "quality": quality}


def build_dashboard(evidence_dir=Path("docs/evidence"), output_dir=Path("site")):
    evidence = load_evidence(evidence_dir)
    figures = make_figures(evidence)
    config = {"responsive": True, "displaylogo": False, "scrollZoom": False,
              "modeBarButtonsToRemove": ["lasso2d", "select2d", "toImage"],
              "showTips": False}
    charts = {name: pio.to_html(fig, full_html=False, include_plotlyjs=False, config=config,
                                div_id=f"chart-{name}", default_width="100%")
              for name, fig in figures.items()}
    metrics = evidence["metrics"]
    median = metrics["median_resolution_hours"]
    percentage = metrics["flagged_pct"]
    cards = [
        ("Total requests", f"{metrics['total_requests']:,}", "Identifiable requests in the creation cohort"),
        ("Open requests", f"{metrics['open_requests']:,}", "Cohort requests still open at observation"),
        ("Closed requests", f"{metrics['closed_requests']:,}", f"{metrics['unknown_status_requests']:,} additional requests have unknown status"),
        ("Median resolution", f"{median:.2f}<small>h</small>" if median is not None else "N/A", f"{metrics['resolution_eligible_requests']:,} eligible closed requests"),
        ("Quality-flagged", f"{percentage:.2f}<small>%</small>" if percentage is not None else "N/A", f"{metrics['flagged_requests']:,} requests · retained for review"),
    ]
    kpis = "".join(f'<article class="kpi"><h2>{title}</h2><p class="kpi-value">{value}</p><p>{note}</p></article>' for title, value, note in cards)
    observed = evidence["observed"].strftime("%b %d, %Y · %H:%M UTC")
    period = f"{evidence['start']:%b %d}–{evidence['end'] - timedelta(days=1):%b %d, %Y}"
    template = files("service_analytics").joinpath("dashboard.html").read_text(encoding="utf-8")
    replacements = {"kpis": kpis, "period": period, "observed": observed,
                    "flagged": f"{metrics['flagged_requests']:,}", "repository": REPOSITORY,
                    "run_id": escape(str(evidence["summary"]["run_id"])), **charts}
    template = re.sub(r"@@([a-z_]+)@@", lambda match: replacements[match[1]], template)
    output = Path(output_dir)
    (output / "assets").mkdir(parents=True, exist_ok=True)
    # One shared, version-locked runtime. No CDN, data fetch, font service or backend.
    (output / "assets" / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    (output / "index.html").write_text(template, encoding="utf-8")
    return output / "index.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/evidence"))
    parser.add_argument("--output", type=Path, default=Path("site"))
    args = parser.parse_args()
    print(build_dashboard(args.evidence_dir, args.output).resolve())


if __name__ == "__main__":
    main()
