"""One CLI for extraction, transactional ELT, checks, reporting and CSV export."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
from importlib.resources import files
import json
import logging
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
from zoneinfo import ZoneInfo

import duckdb

from .etl import load_demo
from .extract import FIELDS, URL, extract, validate_window

LOG = logging.getLogger(__name__)
EXPORTS = {
    "requests": "SELECT * EXCLUDE (quality_flags) FROM requests ORDER BY request_id",
    "metrics": "SELECT * FROM metrics",
    "daily_metrics": "SELECT * FROM daily_metrics ORDER BY created_day",
    "category_metrics": "SELECT * FROM category_metrics ORDER BY total_requests DESC, category",
    "agency_metrics": "SELECT * FROM agency_metrics ORDER BY total_requests DESC, agency",
    "quality_issues": "SELECT * FROM quality_issues ORDER BY affected_requests DESC, rule",
    "request_quality_flags": "SELECT request_id, unnest(quality_flags) AS rule FROM requests ORDER BY request_id, rule",
    "etl_demo": "SELECT * EXCLUDE (date_status_issues) FROM etl_demo ORDER BY request_id",
}


def initialize(con):
    con.execute(files("service_analytics").joinpath("schema.sql").read_text(encoding="utf-8"))


def load_raw(con, rows, run_id, observed_at):
    """Bulk-load original selected fields, quarantine missing IDs and UPSERT by source ID.

    A temporary NDJSON file avoids slow row-by-row inserts without adding pandas.
    Duplicate payloads within a batch use the last occurrence and remain counted.
    """
    with tempfile.TemporaryDirectory(prefix="service-analytics-") as directory:
        path = Path(directory) / "incoming.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if rows:
            con.execute("""CREATE OR REPLACE TEMP TABLE incoming AS
                SELECT row_number() OVER () AS row_number, json AS source_payload,
                    CASE WHEN json_type(json, '$.unique_key') = 'VARCHAR'
                         THEN json ->> 'unique_key' END AS unique_key
                FROM read_json_objects(?)""", [str(path)])
        else:
            con.execute("""CREATE OR REPLACE TEMP TABLE incoming (
                row_number BIGINT, source_payload JSON, unique_key VARCHAR)""")
    con.execute("""INSERT INTO raw_rejections
        SELECT ?, row_number, source_payload, 'missing_identifier'
        FROM incoming WHERE unique_key IS NULL OR trim(unique_key) = ''""", [run_id])
    rejected = con.execute("SELECT COUNT(*) FROM incoming WHERE unique_key IS NULL OR trim(unique_key) = ''").fetchone()[0]
    con.execute("""CREATE OR REPLACE TEMP TABLE accepted AS
        SELECT * FROM incoming WHERE unique_key IS NOT NULL AND trim(unique_key) <> ''
        QUALIFY row_number() OVER (PARTITION BY unique_key ORDER BY row_number DESC) = 1""")
    loaded = con.execute("SELECT COUNT(*) FROM accepted").fetchone()[0]
    columns = (*FIELDS, "source_updated_at")
    projection = ", ".join(f"source_payload ->> '{field}'" for field in columns)
    updates = ", ".join(f"{field} = excluded.{field}" for field in columns if field != "unique_key")
    con.execute(f"""INSERT INTO raw_requests
        SELECT {projection}, source_payload, ?, ? FROM accepted
        ON CONFLICT (unique_key) DO UPDATE SET {updates},
            source_payload = excluded.source_payload, fetched_at = excluded.fetched_at,
            last_run_id = excluded.last_run_id""", [observed_at, run_id])
    con.execute("INSERT INTO run_members SELECT ?, unique_key FROM accepted", [run_id])
    return {"loaded_count": loaded, "rejected_count": rejected,
            "duplicate_count": len(rows) - loaded - rejected}


def transform_sql(con, run_id):
    sql = files("service_analytics").joinpath("transform.sql").read_text(encoding="utf-8")
    for statement in con.extract_statements(sql):
        con.execute(statement.query, {"run_id": run_id} if statement.named_parameters else None)


def get_metrics(con):
    cursor = con.execute("SELECT * FROM metrics")
    return dict(zip([c[0] for c in cursor.description], cursor.fetchone()))


def check_quality(con, loaded_count):
    metrics = get_metrics(con)
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(metrics["total_requests"] == loaded_count, "Loaded/model count mismatch")
    require(con.execute("SELECT COUNT(DISTINCT request_id) FROM requests").fetchone()[0] == loaded_count, "Duplicate model IDs")
    require(sum(metrics[k] for k in ("open_requests", "closed_requests", "unknown_status_requests")) == loaded_count, "Status partition mismatch")
    require(metrics["flagged_requests"] + metrics["valid_requests"] == loaded_count, "Quality partition mismatch")
    require(con.execute("SELECT COUNT(*) FROM requests WHERE resolution_hours < 0").fetchone()[0] == 0, "Negative resolution escaped validation")
    for table in ("category_metrics", "agency_metrics"):
        require(con.execute(f"SELECT COALESCE(SUM(total_requests), 0) FROM {table}").fetchone()[0] == loaded_count, f"{table} mismatch")
    dated = con.execute("SELECT COUNT(*) FROM requests WHERE created_at IS NOT NULL").fetchone()[0]
    require(con.execute("SELECT COALESCE(SUM(total_requests), 0) FROM daily_metrics").fetchone()[0] == dated, "Daily totals mismatch")
    return metrics


def compare_etl(con):
    mismatches = con.execute("""SELECT COUNT(*) FROM etl_demo e
        FULL JOIN (SELECT * FROM requests WHERE request_id IN (SELECT request_id FROM etl_demo)) r
        USING (request_id)
        WHERE e.created_at IS DISTINCT FROM r.created_at
           OR e.closed_at IS DISTINCT FROM r.closed_at
           OR e.lifecycle IS DISTINCT FROM r.lifecycle
           OR e.resolution_hours IS DISTINCT FROM r.resolution_hours""").fetchone()[0]
    if mismatches:
        raise ValueError(f"ETL/ELT comparison failed for {mismatches} records")
    return {"sample_rows": con.execute("SELECT COUNT(*) FROM etl_demo").fetchone()[0],
            "mismatched_rows": mismatches,
            "median_resolution_hours": con.execute("SELECT median(resolution_hours) FROM etl_demo").fetchone()[0]}


def export_outputs(con, directory, report):
    directory.mkdir(parents=True, exist_ok=False)
    for name, query in EXPORTS.items():
        con.execute(f"COPY ({query}) TO ? (FORMAT CSV, HEADER)", [str(directory / f"{name}.csv")])
    from .preview import create_preview
    create_preview(con, directory / "dashboard_preview.png", report)
    report["csv_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.csv"))
    }
    (directory / "run_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_pipeline(start, end, *, database=Path("data/service_operations.duckdb"),
                 output=Path("outputs"), max_records=100_000, page_size=5_000,
                 etl_sample_size=1_000, extractor=extract):
    validate_window(start, end, max_records, page_size)
    if not 1 <= etl_sample_size <= 5_000:
        raise ValueError("ETL sample size must be 1..5000")
    database, output = Path(database), Path(output)
    database.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    run_id, started = str(uuid4()), datetime.now(timezone.utc)
    stage = output / f".staging-{run_id}"
    published = output / run_id
    report = {"run_id": run_id, "started_at": started.isoformat(),
              "window_start": start.isoformat(), "window_end_exclusive": end.isoformat(),
              "source": URL, "status": "running"}
    with duckdb.connect(str(database)) as con:
        initialize(con)
        con.execute("""INSERT INTO pipeline_runs (run_id, started_at, window_start, window_end, status)
            VALUES (?, ?, ?, ?, 'running')""", [run_id, started, start, end])
        try:
            rows, source_count = extractor(start, end, max_records=max_records, page_size=page_size)
            con.execute("UPDATE pipeline_runs SET extracted_count = ?, source_count = ? WHERE run_id = ?",
                        [len(rows), source_count, run_id])
            observed = datetime.now(timezone.utc)
            con.execute("BEGIN")
            try:
                counts = load_raw(con, rows, run_id, observed)
                transform_sql(con, run_id)
                metrics = check_quality(con, counts["loaded_count"])
                load_demo(con, rows[:etl_sample_size])
                comparison = compare_etl(con)
                report.update(counts, extracted_count=len(rows), source_count=source_count,
                              observed_at=observed.isoformat(), metrics=metrics, etl_comparison=comparison)
                report["warnings"] = []
                if not rows:
                    report["warnings"].append("Empty cohort: investigate source freshness or the selected window")
                if counts["rejected_count"] or counts["duplicate_count"]:
                    report["warnings"].append("Rejected or duplicate input rows: inspect the run audit")
                if metrics["flagged_requests"]:
                    report["warnings"].append("Quality flags present: inspect quality_issues.csv")
                report["status"] = "success"
                export_outputs(con, stage, report)
                con.execute("""UPDATE pipeline_runs SET loaded_count = ?, rejected_count = ?,
                    duplicate_count = ?, flagged_count = ? WHERE run_id = ?""",
                            [counts["loaded_count"], counts["rejected_count"], counts["duplicate_count"],
                             metrics["flagged_requests"], run_id])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            stage.rename(published)
            latest_tmp = output / f".latest-{run_id}.json"
            latest_tmp.write_text(json.dumps({"run_id": run_id, "directory": run_id}) + "\n", encoding="utf-8")
            latest_tmp.replace(output / "latest.json")
            con.execute("UPDATE pipeline_runs SET status = 'success', finished_at = ? WHERE run_id = ?",
                        [datetime.now(timezone.utc), run_id])
            LOG.info("Run %s succeeded: %s", run_id, metrics)
            for warning in report["warnings"]:
                LOG.warning(warning)
            return report, published
        except Exception as exc:
            con.execute("UPDATE pipeline_runs SET status = 'failed', finished_at = ?, error = ? WHERE run_id = ?",
                        [datetime.now(timezone.utc), str(exc)[:2000], run_id])
            shutil.rmtree(stage, ignore_errors=True)
            LOG.exception("Run %s failed; inspect its audit record before using its outputs", run_id)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # NYC floating dates define the cohort. UTC is used only for audit timestamps.
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    parser.add_argument("--start", type=date.fromisoformat, default=yesterday - timedelta(days=1))
    parser.add_argument("--end", type=date.fromisoformat, default=yesterday)
    parser.add_argument("--max-records", type=int, default=100_000)
    parser.add_argument("--page-size", type=int, default=5_000)
    parser.add_argument("--etl-sample-size", type=int, default=1_000)
    parser.add_argument("--database", type=Path, default=Path("data/service_operations.duckdb"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    report, directory = run_pipeline(args.start, args.end, database=args.database, output=args.output,
                                    max_records=args.max_records, page_size=args.page_size,
                                    etl_sample_size=args.etl_sample_size)
    print(json.dumps({"output": str(directory.resolve()), **report}, indent=2))


if __name__ == "__main__":
    main()
