from datetime import date, datetime, timezone
import json

import duckdb
import pytest

from service_analytics.etl import load_demo, transform
from service_analytics.pipeline import (check_quality, compare_etl, get_metrics, initialize,
                                      load_raw, run_pipeline, transform_sql)


def test_raw_preservation_and_rejections(model, rows):
    con, counts = model
    assert counts == {"loaded_count": 7, "rejected_count": 1, "duplicate_count": 0}
    payload = json.loads(con.execute("SELECT source_payload FROM raw_requests WHERE unique_key = '101'").fetchone()[0])
    assert payload == rows[0]
    assert con.execute("SELECT reason FROM raw_rejections").fetchone()[0] == "missing_identifier"
    assert con.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 7


def test_sql_normalization_and_nulls(model):
    con, _ = model
    assert con.execute("SELECT agency, category, resolution_hours FROM requests WHERE request_id = '101'").fetchone() == ("DOT", "STREET CONDITION", 2)
    assert con.execute("SELECT created_at, closed_at, agency, category, resolution_hours FROM requests WHERE request_id = '104'").fetchone() == (None, None, "UNKNOWN", "UNKNOWN", None)


def test_bad_records_are_flagged_and_retained(model):
    con, _ = model
    flags = {r[0]: r[1] for r in con.execute("SELECT request_id, quality_flags FROM requests").fetchall()}
    assert "negative_resolution_interval" in flags["103"]
    assert {"invalid_closed_date", "closed_without_date", "missing_agency", "missing_category"} <= set(flags["104"])
    assert flags["106"] == ["open_with_closed_date"]
    assert flags["107"] == ["unknown_status"]
    assert con.execute("SELECT resolution_hours FROM requests WHERE request_id = '105'").fetchone()[0] == 0
    assert con.execute("SELECT resolution_hours FROM requests WHERE request_id = '103'").fetchone()[0] is None


def test_metric_denominators_and_zero_day(model):
    con, counts = model
    m = check_quality(con, counts["loaded_count"])
    assert (m["total_requests"], m["open_requests"], m["closed_requests"], m["unknown_status_requests"]) == (7, 2, 4, 1)
    assert m["resolution_eligible_requests"] == 2
    assert m["median_resolution_hours"] == 1
    assert m["flagged_requests"] == 4
    assert m["flagged_pct"] == pytest.approx(400 / 7)
    assert con.execute("SELECT total_requests FROM daily_metrics WHERE created_day = '2026-10-03'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM daily_metrics WHERE review_volume_spike").fetchone()[0] == 0


def test_processing_anomaly_detected(model):
    con, _ = model
    con.execute("UPDATE category_metrics SET total_requests = 0")
    with pytest.raises(ValueError, match="category_metrics mismatch"):
        check_quality(con, 7)


def test_etl_elt_parity_on_identical_subset(model, rows):
    con, _ = model
    assert load_demo(con, rows) == (7, 1)
    comparison = compare_etl(con)
    assert comparison == {"sample_rows": 7, "mismatched_rows": 0, "median_resolution_hours": 1}
    elt = get_metrics(con)
    etl = con.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE lifecycle = 'open'), median(resolution_hours) FROM etl_demo").fetchone()
    assert etl == (elt["total_requests"], elt["open_requests"], elt["median_resolution_hours"])


def test_idempotence_upsert_and_cohort_membership(model, rows):
    con, _ = model
    original = con.execute("SELECT * EXCLUDE (observed_at) FROM requests ORDER BY request_id").fetchall()
    con.execute("INSERT INTO pipeline_runs (run_id, window_start, window_end) VALUES ('second', '2026-10-01', '2026-10-04')")
    load_raw(con, rows + [rows[0]], "second", datetime.now(timezone.utc))
    transform_sql(con, "second")
    assert con.execute("SELECT COUNT(*) FROM raw_requests").fetchone()[0] == 7
    assert con.execute("SELECT * EXCLUDE (observed_at) FROM requests ORDER BY request_id").fetchall() == original
    con.execute("INSERT INTO pipeline_runs (run_id, window_start, window_end) VALUES ('third', '2026-10-01', '2026-10-04')")
    changed = {**rows[1], "status": "Closed", "closed_date": "2026-10-01T04:00:00"}
    load_raw(con, [changed], "third", datetime.now(timezone.utc))
    transform_sql(con, "third")
    assert con.execute("SELECT COUNT(*) FROM raw_requests").fetchone()[0] == 7
    assert con.execute("SELECT request_id, lifecycle, resolution_hours FROM requests").fetchone() == ("102", "closed", 3)


def test_duplicate_last_payload_wins(model, rows):
    con, _ = model
    updated = {**rows[0], "status": "Open", "closed_date": None}
    counts = load_raw(con, [rows[0], updated], "duplicates", datetime.now(timezone.utc))
    assert counts["duplicate_count"] == 1
    assert con.execute("SELECT status, closed_date FROM raw_requests WHERE unique_key = '101'").fetchone() == ("Open", None)


def test_python_dates_and_missing_identifier():
    accepted, rejected = transform([{"unique_key": " ", "status": "Open"}, {"unique_key": "1", "created_date": "2026-02-30", "status": None}])
    assert len(rejected) == 1
    assert accepted[0][1] is None
    assert "unknown_status" in accepted[0][-1]


def test_offline_end_to_end_reproducibility_and_failure_audit(tmp_path, rows):
    kwargs = {"database": tmp_path / "data.duckdb", "output": tmp_path / "outputs"}
    source = lambda *args, **kw: (rows, len(rows))
    first, first_dir = run_pipeline(date(2026, 10, 1), date(2026, 10, 4), extractor=source, **kwargs)
    second, second_dir = run_pipeline(date(2026, 10, 1), date(2026, 10, 4), extractor=source, **kwargs)
    assert first["metrics"] == second["metrics"]
    for file in ("metrics.csv", "daily_metrics.csv", "agency_metrics.csv", "category_metrics.csv", "etl_demo.csv"):
        assert (first_dir / file).read_bytes() == (second_dir / file).read_bytes()
    assert json.loads((kwargs["output"] / "latest.json").read_text())["run_id"] == second["run_id"]

    def fail(*args, **kw):
        raise RuntimeError("simulated network outage")

    with pytest.raises(RuntimeError, match="simulated network"):
        run_pipeline(date(2026, 10, 1), date(2026, 10, 4), extractor=fail, **kwargs)
    with duckdb.connect(str(kwargs["database"])) as con:
        assert con.execute("SELECT COUNT(*) FROM raw_requests").fetchone()[0] == 7
        assert con.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status = 'success'").fetchone()[0] == 2
        assert con.execute("SELECT error FROM pipeline_runs WHERE status = 'failed'").fetchone()[0] == "simulated network outage"
    assert json.loads((kwargs["output"] / "latest.json").read_text())["run_id"] == second["run_id"]


def test_transaction_rolls_back_transformation_failure(tmp_path, rows, monkeypatch):
    import service_analytics.pipeline as pipeline
    def broken(*args):
        raise ValueError("simulated SQL failure")
    monkeypatch.setattr(pipeline, "transform_sql", broken)
    db = tmp_path / "db.duckdb"
    with pytest.raises(ValueError, match="SQL failure"):
        run_pipeline(date(2026, 10, 1), date(2026, 10, 4), database=db,
                     output=tmp_path / "outputs", extractor=lambda *a, **k: (rows, len(rows)))
    with duckdb.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM raw_requests").fetchone()[0] == 0
        assert con.execute("SELECT status, extracted_count FROM pipeline_runs").fetchone() == ("failed", len(rows))


def test_empty_run(tmp_path):
    report, _ = run_pipeline(date(2026, 10, 1), date(2026, 10, 2), database=tmp_path / "empty.duckdb",
                             output=tmp_path / "outputs", extractor=lambda *a, **kw: ([], 0))
    assert report["metrics"]["total_requests"] == 0
    assert report["metrics"]["median_resolution_hours"] is None
    assert "Empty cohort" in report["warnings"][0]


def test_volume_review_requires_full_baseline():
    con = duckdb.connect()
    initialize(con)
    con.execute("INSERT INTO pipeline_runs (run_id, window_start, window_end) VALUES ('spike', '2026-10-01', '2026-10-09')")
    rows = [{"unique_key": str(day), "created_date": f"2026-10-{day:02d}T00:00:00", "status": "Open",
             "agency": "DOT", "complaint_type": "Street Condition"} for day in range(1, 9)]
    rows.append({**rows[-1], "unique_key": "extra"})
    load_raw(con, rows, "spike", datetime.now(timezone.utc))
    transform_sql(con, "spike")
    assert con.execute("SELECT baseline_days, volume_ratio, review_volume_spike FROM daily_metrics WHERE created_day = '2026-10-08'").fetchone() == (7, 2, True)
    assert con.execute("SELECT COUNT(*) FROM daily_metrics WHERE baseline_days < 7 AND review_volume_spike").fetchone()[0] == 0
    con.close()


def test_etl_mismatch_blocks_run(model, rows):
    con, _ = model
    load_demo(con, rows)
    con.execute("UPDATE etl_demo SET resolution_hours = 999 WHERE request_id = '101'")
    with pytest.raises(ValueError, match="ETL/ELT comparison failed"):
        compare_etl(con)


def test_export_failure_rolls_back_and_removes_staging(tmp_path, rows, monkeypatch):
    import service_analytics.pipeline as pipeline
    def broken_export(con, directory, report):
        directory.mkdir()
        (directory / "partial.csv").write_text("partial")
        raise OSError("simulated disk failure")
    monkeypatch.setattr(pipeline, "export_outputs", broken_export)
    db, output = tmp_path / "db.duckdb", tmp_path / "outputs"
    with pytest.raises(OSError, match="disk failure"):
        run_pipeline(date(2026, 10, 1), date(2026, 10, 4), database=db, output=output,
                     extractor=lambda *a, **k: (rows, len(rows)))
    with duckdb.connect(str(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM raw_requests").fetchone()[0] == 0
        assert con.execute("SELECT status FROM pipeline_runs").fetchone()[0] == "failed"
    assert list(output.iterdir()) == []
