from datetime import date
from unittest.mock import Mock

import pytest
import requests

from service_analytics.extract import extract, get_json, validate_window

START, END = date(2026, 10, 1), date(2026, 10, 3)


def response(data, status=200, headers=None):
    value = Mock(status_code=status, headers=headers or {})
    value.json.return_value = data
    if status >= 400:
        value.raise_for_status.side_effect = requests.HTTPError(str(status))
    return value


def session_for(*responses):
    session = Mock()
    session.get.side_effect = responses
    return session


def test_keyset_pagination_and_field_selection():
    session = session_for(response([{"n": "3"}]),
                          response([{"unique_key": "1", "created_date": "2026-10-01"}, {"unique_key": "2", "created_date": "2026-10-01"}]),
                          response([{"unique_key": "3", "created_date": "2026-10-02"}]), response([{"n": "3"}]))
    rows, count = extract(START, END, page_size=2, session=session)
    assert len(rows) == count == 3
    params = session.get.call_args_list[2].kwargs["params"]
    assert "unique_key > '2'" in params["$where"]
    assert params["$order"] == "unique_key ASC"
    assert ":updated_at as source_updated_at" in params["$select"]
    assert "incident_address" not in params["$select"]
    assert session.get.call_args.kwargs["timeout"] == (10, 60)


def test_cap_fails_before_download():
    session = session_for(response([{"n": "200"}]))
    with pytest.raises(ValueError, match="Narrow the window"):
        extract(START, END, max_records=100, session=session)
    assert session.get.call_count == 1


@pytest.mark.parametrize("page", [[], [{"unique_key": "1"}], [{"created_date": "2026-10-01"}],
                                    [{"unique_key": "1", "created_date": "x"}, {"unique_key": "1", "created_date": "x"}]])
def test_pagination_or_schema_errors(page):
    with pytest.raises(ValueError):
        extract(START, END, session=session_for(response([{"n": "2"}]), response(page)))


def test_source_drift_fails():
    with pytest.raises(ValueError, match="count changed"):
        extract(START, END, session=session_for(response([{"n": "1"}]),
                response([{"unique_key": "1", "created_date": "2026-10-01"}]), response([{"n": "2"}])))


def test_empty_window_is_explicit():
    assert extract(START, END, session=session_for(response([{"n": "0"}]), response([{"n": "0"}]))) == ([], 0)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_retry(status):
    sleep = Mock()
    session = session_for(response([], status, {"Retry-After": "999"}), response([{"ok": True}]))
    assert get_json(session, {}, sleep=sleep) == [{"ok": True}]
    sleep.assert_called_once_with(10)


def test_http_error_not_retried():
    session = session_for(response([], 400))
    with pytest.raises(requests.HTTPError):
        get_json(session, {}, sleep=Mock())
    assert session.get.call_count == 1


@pytest.mark.parametrize("failure", [requests.Timeout, requests.ConnectionError])
def test_network_retry_is_bounded(failure):
    session = session_for(failure(), failure(), failure())
    with pytest.raises(failure):
        get_json(session, {}, sleep=Mock())
    assert session.get.call_count == 3


def test_server_retry_exhaustion():
    session = session_for(*(response([], 503) for _ in range(3)))
    with pytest.raises(requests.HTTPError):
        get_json(session, {}, sleep=Mock())
    assert session.get.call_count == 3


@pytest.mark.parametrize("data", [{"error": "bad"}, [1]])
def test_bad_json_shape(data):
    with pytest.raises(ValueError, match="list of objects"):
        get_json(session_for(response(data)), {})


@pytest.mark.parametrize("days,cap,page", [(0, 10, 2), (32, 10, 2), (1, 100001, 2), (1, 10, 0)])
def test_invalid_configuration(days, cap, page):
    from datetime import timedelta
    with pytest.raises(ValueError):
        validate_window(START, START + timedelta(days=days), cap, page)
