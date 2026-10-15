"""Bounded, keyset-paginated extraction from the public Socrata endpoint."""

from datetime import date
import logging
import time

import requests

URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
FIELDS = (
    "unique_key", "created_date", "closed_date", "agency", "agency_name",
    "complaint_type", "descriptor", "status", "borough",
    "resolution_action_updated_date",
)
SELECT = ",".join(FIELDS) + ",:updated_at as source_updated_at"
LOG = logging.getLogger(__name__)


def validate_window(start: date, end: date, max_records: int, page_size: int) -> None:
    if not 0 < (end - start).days <= 31:
        raise ValueError("Use a start-inclusive, end-exclusive window of 1 to 31 days")
    if not 1 <= max_records <= 100_000 or not 1 <= page_size <= 10_000:
        raise ValueError("max_records must be 1..100000 and page_size 1..10000")


def get_json(session, params: dict, *, sleep=time.sleep, attempts=3):
    """Retry only transient failures, with a bounded delay and request timeout."""
    for attempt in range(attempts):
        try:
            response = session.get(URL, params=params, timeout=(10, 60))
            if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
                if attempt + 1 == attempts:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 2 ** attempt
                LOG.warning("HTTP %s; retry %s/%s after %ss", response.status_code,
                            attempt + 1, attempts - 1, min(delay, 10))
                sleep(min(delay, 10))
                continue
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, list) or any(not isinstance(r, dict) for r in result):
                raise ValueError("API response must be a list of objects")
            return result
        except (requests.Timeout, requests.ConnectionError):
            if attempt + 1 == attempts:
                raise
            LOG.warning("Network failure; retry %s/%s", attempt + 1, attempts - 1)
            sleep(2 ** attempt)
    raise RuntimeError("Retry loop exhausted")


def extract(start: date, end: date, *, max_records=100_000, page_size=5_000, session=None):
    """Fail on truncation or observable source drift instead of publishing a biased sample.

    The source does not provide snapshot isolation across HTTP requests. Count checks
    detect some, but not all, concurrent changes. A later refresh reconciles the cohort.
    """
    validate_window(start, end, max_records, page_size)
    if session is None:
        with requests.Session() as owned_session:
            return extract(start, end, max_records=max_records, page_size=page_size,
                           session=owned_session)
    where = (f"created_date >= '{start.isoformat()}T00:00:00' AND "
             f"created_date < '{end.isoformat()}T00:00:00'")

    def source_count():
        return int(get_json(session, {"$select": "count(*) as n", "$where": where})[0]["n"])

    expected = source_count()
    if expected > max_records:
        raise ValueError(f"Window contains {expected:,} rows; cap is {max_records:,}. Narrow the window.")
    rows, last_key = [], None
    while len(rows) < expected:
        predicate = where
        if last_key is not None:
            predicate += " AND unique_key > '" + last_key.replace("'", "''") + "'"
        page = get_json(session, {
            "$select": SELECT, "$where": predicate, "$order": "unique_key ASC",
            "$limit": min(page_size, max_records - len(rows)),
        })
        if not page:
            raise ValueError("Source changed during pagination: early empty page")
        for row in page:
            key = row.get("unique_key")
            if not isinstance(key, str) or not key.strip() or (last_key is not None and key <= last_key):
                raise ValueError("Missing, duplicate or unordered API identifier")
            if "created_date" not in row:
                raise ValueError("API schema drift: created_date is absent")
            last_key = key
        rows.extend(page)
        LOG.info("Extracted %s / %s requests", len(rows), expected)
        if len(rows) > max_records:
            raise ValueError("Source exceeded configured download cap")
    if len(rows) != expected or source_count() != expected:
        raise ValueError("Source count changed during extraction; rerun the bounded window")
    return rows, expected
