from datetime import date, datetime, timezone

import duckdb
import pytest

from service_analytics.pipeline import initialize, load_raw, transform_sql


@pytest.fixture
def rows():
    return [
        {"unique_key": "101", "created_date": "2026-10-01T00:00:00.000", "closed_date": "2026-10-01T02:00:00.000", "status": "Closed", "agency": " dot ", "complaint_type": "Street  Condition"},
        {"unique_key": "102", "created_date": "2026-10-01T01:00:00.000", "status": "Open", "agency": "DOT", "complaint_type": "Street Condition"},
        {"unique_key": "103", "created_date": "2026-10-02T01:00:00.000", "closed_date": "2026-10-02T00:00:00.000", "status": "Closed", "agency": "DEP", "complaint_type": "Water"},
        {"unique_key": "104", "created_date": "not-a-date", "closed_date": "also-bad", "status": "Closed", "agency": "", "complaint_type": None},
        {"unique_key": "105", "created_date": "2026-10-02T00:00:00.000", "closed_date": "2026-10-02T00:00:00.000", "status": "Closed", "agency": "DOT", "complaint_type": "Street Condition"},
        {"unique_key": "106", "created_date": "2026-10-02T00:00:00.000", "closed_date": "2026-10-02T02:00:00.000", "status": "Open", "agency": "DOT", "complaint_type": "Street Condition"},
        {"unique_key": "107", "created_date": "2026-10-02T00:00:00.000", "status": "Unspecified", "agency": "DOT", "complaint_type": "Street Condition"},
        {"created_date": "2026-10-02T00:00:00.000", "status": "Open"},
    ]


@pytest.fixture
def model(rows):
    con = duckdb.connect()
    initialize(con)
    con.execute("INSERT INTO pipeline_runs (run_id, window_start, window_end) VALUES ('test', ?, ?)",
                [date(2026, 10, 1), date(2026, 10, 4)])
    counts = load_raw(con, rows, "test", datetime(2026, 10, 14, tzinfo=timezone.utc))
    transform_sql(con, "test")
    yield con, counts
    con.close()
