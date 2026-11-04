"""Optional dbt subprocess tests; all data is deterministic and local."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import duckdb
import pytest

from service_analytics.dbt_poc import (
    RUN_ID, SNAPSHOT_ID, prepare_database, verify_database,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_DBT = importlib.util.find_spec('dbt') is not None


def test_prepare_refuses_overwrite_and_operational_names(tmp_path):
    database = tmp_path / 'existing_poc.duckdb'
    database.write_bytes(b'original bytes')
    with pytest.raises(FileExistsError):
        prepare_database(database)
    assert database.read_bytes() == b'original bytes'
    with pytest.raises(ValueError, match='dedicated'):
        prepare_database(tmp_path / 'service_operations.duckdb')
    assert not (tmp_path / 'service_operations.duckdb').exists()


def test_prepare_is_deterministic_and_preserves_raw_membership_semantics(tmp_path, rows):
    first, second = (tmp_path / name for name in ('first_poc.duckdb', 'second_poc.duckdb'))
    for path in (first, second):
        assert prepare_database(path, rows)['rows'] == 7
    snapshots = []
    for path in (first, second):
        with duckdb.connect(str(path), read_only=True) as con:
            snapshots.append(con.execute('SELECT * FROM dbt_poc_snapshot').fetchall())
            assert con.execute('SELECT count(*) FROM raw_requests').fetchone()[0] == 8
            assert con.execute('SELECT count(*) FROM requests').fetchone()[0] == 7
            assert con.execute("SELECT last_run_id FROM raw_requests WHERE unique_key='101'").fetchone()[0] == RUN_ID
            assert con.execute("SELECT count(*) FROM run_members WHERE unique_key='101'").fetchone()[0] == 2
            assert con.execute('SELECT count(*) FROM raw_rejections').fetchone()[0] == 1
    assert snapshots[0] == snapshots[1]


@pytest.mark.skipif(not HAS_DBT, reason='Install optional group: uv sync --frozen --group dbt')
def test_dbt_staging_parity_guards_and_quality_retention(tmp_path, rows):
    database = tmp_path / 'integration_poc.duckdb'
    # Reuse the original fixture, including deliberately retained anomalies.
    extended = rows + [
        {'unique_key': '108', 'created_date': ' 2026-10-01T01:02:03.123456 ',
         'closed_date': ' ', 'status': ' In\t  Progress ', 'agency': '  d  ot ',
         'agency_name': ' Test  Agency ', 'borough': '  New  York ',
         'complaint_type': ' Some\n Category ', 'source_updated_at': '2026-10-13T15:00:00-04:00'},
        {'unique_key': '109', 'created_date': '', 'status': '', 'agency': None},
        # SQL trim removes spaces before whitespace collapse; preserve that exact order.
        {'unique_key': '110', 'status': '\tOpen\t', 'agency': '\t', 'complaint_type': '\t'},
        # Last duplicate wins using the original loader.
        {**rows[0], 'status': ' Closed ', 'agency': ' dot '},
    ]
    prepare_database(database, extended)
    environment = dict(os.environ, DBT_POC_DATABASE=str(database),
                       DBT_LOG_PATH=str(tmp_path / 'logs'),
                       DBT_TARGET_PATH=str(tmp_path / 'target'),
                       DBT_SEND_ANONYMOUS_USAGE_STATS='false')

    def dbt(command, variables=None, success=True):
        arguments = [sys.executable, '-c', 'from dbt.cli.main import cli; cli()', command,
                     '--project-dir', str(ROOT / 'analytics'),
                     '--profiles-dir', str(ROOT / 'analytics')]
        if variables is not None:
            arguments += ['--vars', json.dumps(variables)]
        result = subprocess.run(arguments, cwd=ROOT, env=environment, text=True,
                                encoding='utf-8', errors='replace', capture_output=True, timeout=90)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout + result.stderr

    variables = {'run_id': RUN_ID, 'snapshot_id': SNAPSHOT_ID}
    dbt('debug')
    dbt('build', variables)
    assert verify_database(database) == {
        'rows': 10, 'normalized_columns_compared': 10, 'row_differences': 0,
        'provenance_differences': 0, 'original_tables_unchanged': 10,
    }
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute("SELECT created_at FROM dbt_staging.stg_service_requests WHERE request_id='104'").fetchone() == (None,)
        assert con.execute("SELECT source_status FROM dbt_staging.stg_service_requests WHERE request_id='107'").fetchone() == ('UNSPECIFIED',)
        original_staging = con.execute('SELECT * FROM dbt_staging.stg_service_requests ORDER BY request_id').fetchall()
    dbt('run', variables)
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute('SELECT * FROM dbt_staging.stg_service_requests ORDER BY request_id').fetchall() == original_staging

    # Required vars and invalid selections must fail, never silently choose latest.
    assert 'snapshot_id' in dbt('run', {}, success=False)
    assert 'run_id' in dbt('run', {'snapshot_id': SNAPSHOT_ID}, success=False)
    assert 'snapshot' in dbt('run', {**variables, 'run_id': 'poc-previous'}, success=False).lower()
    assert 'snapshot' in dbt('run', {**variables, 'snapshot_id': 'unknown'}, success=False).lower()
    assert verify_database(database)['original_tables_unchanged'] == 10

    # A stale materialization must fail cohort tests, even when sources are intact.
    with duckdb.connect(str(database)) as con:
        con.execute("DELETE FROM dbt_staging.stg_service_requests WHERE request_id='102'")
    assert 'cohort_matches' in dbt('test', variables, success=False)
    dbt('build', variables)

    # Editing the known source snapshot invalidates its identity before model replacement.
    with duckdb.connect(str(database)) as con:
        con.execute("UPDATE raw_requests SET status='Changed' WHERE unique_key='101'")
    assert 'snapshot' in dbt('run', variables, success=False).lower()
    with pytest.raises(ValueError, match='Original tables changed'):
        verify_database(database)
