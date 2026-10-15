"""Small ETL example: transform dates and validate in Python BEFORE loading."""

from datetime import datetime
import re

import duckdb


def parse_date(value):
    if not value or not str(value).strip():
        return None
    try:
        result = datetime.fromisoformat(str(value).strip())
        # Source business dates are NYC floating timestamps, not UTC instants.
        if result.tzinfo is not None:
            return None
        return result
    except ValueError:
        return None


def transform(rows):
    """Keep one row per nonblank ID; rejected IDs remain in an explicit return value."""
    accepted, rejected = {}, []
    for row in rows:
        key = row.get("unique_key")
        if not isinstance(key, str) or not key.strip():
            rejected.append({"reason": "missing_identifier", "source": row})
            continue
        created, closed = parse_date(row.get("created_date")), parse_date(row.get("closed_date"))
        status = re.sub(r"\s+", " ", (row.get("status") or "").strip()).upper()
        lifecycle = ("closed" if status == "CLOSED" else "open"
                     if status in {"OPEN", "IN PROGRESS", "ASSIGNED", "STARTED", "PENDING"} else "unknown")
        hours = ((closed - created).total_seconds() / 3600
                 if lifecycle == "closed" and created and closed and closed >= created else None)
        issues = []
        if created is None:
            issues.append("missing_or_invalid_created_date")
        if row.get("closed_date") and str(row["closed_date"]).strip() and closed is None:
            issues.append("invalid_closed_date")
        if created and closed and closed < created:
            issues.append("negative_resolution_interval")
        if lifecycle == "closed" and closed is None:
            issues.append("closed_without_date")
        if lifecycle == "open" and closed is not None:
            issues.append("open_with_closed_date")
        if lifecycle == "unknown":
            issues.append("unknown_status")
        accepted[key] = (key, created, closed, lifecycle, hours, issues)
    return list(accepted.values()), rejected


def load_demo(con: duckdb.DuckDBPyConnection, rows):
    transformed, rejected = transform(rows)  # Python work happens before INSERT.
    con.execute("""CREATE OR REPLACE TABLE etl_demo (
        request_id VARCHAR PRIMARY KEY, created_at TIMESTAMP, closed_at TIMESTAMP,
        lifecycle VARCHAR, resolution_hours DOUBLE, date_status_issues VARCHAR[]
    )""")
    if transformed:
        con.executemany("INSERT INTO etl_demo VALUES (?, ?, ?, ?, ?, ?)", transformed)
    return len(transformed), len(rejected)
