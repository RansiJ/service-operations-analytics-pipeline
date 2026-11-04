import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil

import pytest

from service_analytics.dashboard import build_dashboard, load_evidence, make_figures

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence"


@pytest.fixture
def snapshot(tmp_path):
    destination = tmp_path / "evidence"
    destination.mkdir()
    for name in ("metrics", "daily_metrics", "category_metrics", "agency_metrics", "quality_issues"):
        shutil.copyfile(EVIDENCE / f"{name}.csv", destination / f"{name}.csv")
    shutil.copyfile(EVIDENCE / "run_summary.json", destination / "run_summary.json")
    return destination


def rewrite_csv(directory, name, mutate):
    path = directory / f"{name}.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    update_hash(directory, name)


def update_hash(directory, name):
    summary_path = directory / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["csv_sha256"][f"{name}.csv"] = hashlib.sha256((directory / f"{name}.csv").read_bytes()).hexdigest()
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def test_verified_snapshot_and_metadata():
    evidence = load_evidence(EVIDENCE)
    assert evidence["metrics"]["total_requests"] == 78_466
    assert evidence["metrics"]["median_resolution_hours"] == 3.390833333333333
    assert evidence["observed"].isoformat() == "2026-10-15T00:32:06.211358+00:00"
    assert str(evidence["start"]) == "2026-10-01"
    assert str(evidence["end"]) == "2026-10-08"
    assert sum(r["total_requests"] for r in evidence["tables"]["daily_metrics"]) == 78_466
    assert not any(name in evidence["tables"] for name in ("requests", "etl_demo"))


@pytest.mark.parametrize("missing", ["metrics.csv", "run_summary.json"])
def test_missing_input_fails(snapshot, missing):
    (snapshot / missing).unlink()
    with pytest.raises(ValueError, match="Cannot read complete"):
        load_evidence(snapshot)


def test_unverified_changed_file_fails(snapshot):
    with (snapshot / "metrics.csv").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_evidence(snapshot)


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "not-numeric", "1.5"])
def test_malformed_counts_fail(snapshot, value):
    rewrite_csv(snapshot, "metrics", lambda rows: rows[0].update(total_requests=value))
    with pytest.raises(ValueError):
        load_evidence(snapshot)


def test_missing_columns_fail(snapshot):
    path = snapshot / "quality_issues.csv"
    path.write_text("rule\nunknown_status\n", encoding="utf-8")
    update_hash(snapshot, "quality_issues")
    with pytest.raises(ValueError, match="Missing columns"):
        load_evidence(snapshot)


@pytest.mark.parametrize("name", ["category_metrics", "agency_metrics", "daily_metrics"])
def test_aggregate_inconsistency_fails(snapshot, name):
    def change(rows):
        rows[0]["total_requests"] = str(int(rows[0]["total_requests"]) + 1)
        rows[0]["open_requests"] = str(int(rows[0]["open_requests"]) + 1)
    rewrite_csv(snapshot, name, change)
    with pytest.raises(ValueError, match="totals do not reconcile"):
        load_evidence(snapshot)


def test_summary_mismatch_fails(snapshot):
    path = snapshot / "run_summary.json"
    summary = json.loads(path.read_text())
    summary["metrics"]["median_resolution_hours"] = 999
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="Summary metric mismatch"):
        load_evidence(snapshot)


@pytest.mark.parametrize("field,value", [("status", "failed"), ("observed_at", "2026-10-15T00:32:06"),
                                          ("window_end_exclusive", "2026-10-01")])
def test_invalid_snapshot_metadata(snapshot, field, value):
    path = snapshot / "run_summary.json"
    summary = json.loads(path.read_text())
    summary[field] = value
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        load_evidence(snapshot)


def test_malformed_json(snapshot):
    (snapshot / "run_summary.json").write_text("{oops")
    with pytest.raises(ValueError, match="Cannot read complete"):
        load_evidence(snapshot)


def test_null_group_medians_remain_missing():
    evidence = load_evidence(EVIDENCE)
    by_agency = {row["agency"]: row for row in evidence["tables"]["agency_metrics"]}
    assert by_agency["EDC"]["median_resolution_hours"] is None
    assert by_agency["OTI"]["median_resolution_hours"] is None
    figure = make_figures(evidence)["resolution"]
    assert set(figure.data[0].y) == set(by_agency) - {"EDC", "OTI"}
    assert dict(zip(figure.data[0].y, figure.data[0].x))["HPD"] == by_agency["HPD"]["median_resolution_hours"]


def test_figures_use_real_values_and_local_top_n():
    figures = make_figures(load_evidence(EVIDENCE))
    assert set(figures) == {"volume", "categories", "agencies", "resolution", "quality"}
    assert list(figures["volume"].data[0].y) == [12017, 11771, 10718, 9053, 11623, 11675, 11609]
    assert max(figures["categories"].data[0].x) == 13664
    assert sum(figures["agencies"].data[0].x) == 78466
    assert max(figures["quality"].data[0].x) == 1813
    buttons = figures["categories"].layout.updatemenus[0].buttons
    assert [len(button.args[0]["x"][0]) for button in buttons] == [5, 10, 15]
    assert all(button.method == "restyle" for button in buttons)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs["src"])


def test_html_export_and_shared_offline_runtime(tmp_path):
    page = build_dashboard(EVIDENCE, tmp_path / "site")
    html = page.read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(html)
    assert parser.scripts == ["assets/plotly.min.js"]
    assert len([i for i in parser.ids if i.startswith("chart-")]) == 5
    assert len(parser.ids) == len(set(parser.ids))
    assert html.count("Plotly.newPlot(") == 5
    assert all(text in html for text in ("78,466", "17,360", "61,098", "3.39", "2.38", "Oct 15, 2026 · 00:32 UTC"))
    assert "Oct 01–Oct 07, 2026" in html
    assert "not the citywide backlog" in html
    assert "does not fetch live API updates" in html
    assert "@@" not in html
    assert page.stat().st_size < 150_000
    runtime = page.parent / parser.scripts[0]
    assert "plotly.js" in runtime.read_text(encoding="utf-8")[:1000]
    assert not list(page.parent.rglob("*.csv"))


def test_untrusted_labels_are_escaped(snapshot, tmp_path):
    attack = '</script><script>alert("label")</script>@@agencies@@'
    rewrite_csv(snapshot, "category_metrics", lambda rows: rows[0].update(category=attack))
    html = build_dashboard(snapshot, tmp_path / "site").read_text(encoding="utf-8")
    assert attack not in html
    assert 'alert(\\"label\\")' not in html
    assert "&lt;" in html or "\\u0026lt;" in html
    assert html.count("Plotly.newPlot(") == 5
