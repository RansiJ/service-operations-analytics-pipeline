"""Full offline parity against unchanged transform.sql, including deliberate corruption."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import duckdb
import pytest

from service_analytics.dbt_poc import (
    ANALYTICAL_MODELS, RUN_ID, SCENARIOS, prepare_scenario, verify_full_parity,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_DBT = importlib.util.find_spec('dbt') is not None
requires_dbt = pytest.mark.skipif(not HAS_DBT, reason='Install optional group: uv sync --frozen --group dbt')


def run_dbt(database, tmp_path, command, variables, *, success=True):
    environment = dict(os.environ, DBT_POC_DATABASE=str(database),
                       DBT_LOG_PATH=str(tmp_path / 'logs'), DBT_TARGET_PATH=str(tmp_path / 'target'),
                       DBT_SEND_ANONYMOUS_USAGE_STATS='false')
    result = subprocess.run(
        [sys.executable, '-c', 'from dbt.cli.main import cli; cli()', command,
         '--project-dir', str(ROOT / 'analytics'), '--profiles-dir', str(ROOT / 'analytics'),
         '--vars', json.dumps(variables)],
        cwd=ROOT, env=environment, text=True, encoding='utf-8', errors='replace',
        capture_output=True, timeout=180,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.mark.parametrize('scenario,rows,days', [('small', 7, 3), ('edge', 32, 12),
                                              ('empty', 0, 3), ('zero-baseline', 1, 8)])
def test_synthetic_scenarios_have_explicit_audits(tmp_path, scenario, rows, days):
    database = tmp_path / f'{scenario}_poc.duckdb'
    prepared = prepare_scenario(database, scenario)
    assert prepared['rows'] == rows
    assert prepared['original_tables'] == 10
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute('SELECT count(*) FROM daily_metrics').fetchone()[0] == days
        assert con.execute('SELECT count(*) FROM requests').fetchone()[0] == rows
        if scenario == 'edge':
            assert con.execute('SELECT rejected_count, duplicate_count FROM pipeline_runs WHERE run_id=?', [RUN_ID]).fetchone() == (3, 1)


@requires_dbt
@pytest.mark.parametrize('scenario', SCENARIOS)
def test_full_dbt_parity_and_edge_contracts(tmp_path, scenario):
    database = tmp_path / f'{scenario}_poc.duckdb'
    prepared = prepare_scenario(database, scenario)
    variables = {'run_id': prepared['run_id'], 'snapshot_id': prepared['snapshot_id']}
    run_dbt(database, tmp_path, 'build', variables)
    report = verify_full_parity(database, **variables)
    assert report['full_parity'] and report['original_tables_unchanged'] == 10
    assert len(report['models']) == 6
    assert all(model['row_differences'] == 0 for model in report['models'].values())
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='dbt_staging'").fetchone()[0] == 7
        if scenario == 'edge':
            assert con.execute('''SELECT total_requests, open_requests, closed_requests,
                unknown_status_requests, resolution_eligible_requests, flagged_requests
                FROM dbt_staging.mart_overall_metrics''').fetchone() == (32, 16, 14, 2, 12, 6)
            assert con.execute("SELECT baseline_days, previous_7day_mean, volume_ratio, review_volume_spike FROM dbt_staging.mart_daily_metrics WHERE created_day='2026-10-08'").fetchone() == (7, 2, 1.5, True)
            assert con.execute("SELECT total_requests FROM dbt_staging.mart_daily_metrics WHERE created_day='2026-10-09'").fetchone() == (0,)
            assert con.execute("SELECT count(*) FROM dbt_staging.mart_daily_metrics WHERE created_day >= '2026-10-13'").fetchone() == (0,)
            assert con.execute("SELECT len(quality_flags) FROM dbt_staging.fct_service_requests WHERE request_id='overlap'").fetchone() == (5,)
            assert con.execute("SELECT is_valid, resolution_hours FROM dbt_staging.fct_service_requests WHERE request_id='flagged-eligible'").fetchone() == (False, 1)
            assert con.execute('SELECT sum(affected_requests) FROM dbt_staging.mart_quality_issues').fetchone() == (10,)
            expected_bands = {'zero': '0-24 hours', 'under24': '0-24 hours', 'at24': '24-72 hours',
                              'under72': '24-72 hours', 'at72': '72-168 hours',
                              'under168': '72-168 hours', 'at168': '168+ hours'}
            for label, band in expected_bands.items():
                assert con.execute('SELECT resolution_band FROM dbt_staging.fct_service_requests WHERE request_id=?', [f'band-{label}']).fetchone() == (band,)
        elif scenario == 'empty':
            assert con.execute('SELECT total_requests, median_resolution_hours, flagged_pct FROM dbt_staging.mart_overall_metrics').fetchone() == (0, None, None)
            assert con.execute('SELECT sum(total_requests) FROM dbt_staging.mart_daily_metrics').fetchone() == (0,)
        elif scenario == 'zero-baseline':
            assert con.execute("SELECT baseline_days, previous_7day_mean, volume_ratio, review_volume_spike FROM dbt_staging.mart_daily_metrics WHERE created_day='2026-10-08'").fetchone() == (7, 0, None, False)
        else:
            assert con.execute('SELECT count(*) FROM dbt_staging.mart_daily_metrics WHERE volume_ratio IS NOT NULL OR review_volume_spike').fetchone() == (0,)

    # Same row count is insufficient: independently corrupt every final output.
    if scenario == 'small':
        mutations = {
            'requests': 'UPDATE dbt_staging.fct_service_requests SET quality_flags = list_reverse(quality_flags) WHERE len(quality_flags)>1',
            'metrics': 'UPDATE dbt_staging.mart_overall_metrics SET median_resolution_hours=999',
            'daily_metrics': 'UPDATE dbt_staging.mart_daily_metrics SET baseline_days=99',
            'category_metrics': 'UPDATE dbt_staging.mart_category_metrics SET total_requests=total_requests+1',
            'agency_metrics': 'UPDATE dbt_staging.mart_agency_metrics SET flagged_requests=flagged_requests+1',
            'quality_issues': 'UPDATE dbt_staging.mart_quality_issues SET affected_requests=affected_requests+1',
        }
        for original, mutation in mutations.items():
            with duckdb.connect(str(database)) as con:
                con.execute(mutation)
            with pytest.raises(ValueError, match=ANALYTICAL_MODELS[original]):
                verify_full_parity(database, **variables)
            with duckdb.connect(str(database)) as con:
                con.execute(f'CREATE OR REPLACE TABLE dbt_staging.{ANALYTICAL_MODELS[original]} AS SELECT * FROM main.{original}')
        with duckdb.connect(str(database)) as con:
            con.execute('CREATE OR REPLACE TABLE dbt_staging.mart_overall_metrics AS SELECT * REPLACE (CAST(total_requests AS DOUBLE) AS total_requests) FROM main.metrics')
        with pytest.raises(ValueError, match='Schema parity'):
            verify_full_parity(database, **variables)


@requires_dbt
def test_invalid_database_is_rejected_before_schema_creation(tmp_path):
    database = tmp_path / 'protected.duckdb'
    with duckdb.connect(str(database)) as con:
        con.execute('CREATE TABLE protected_data AS SELECT 42 AS value')
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    output = run_dbt(database, tmp_path, 'build', {'run_id': RUN_ID, 'snapshot_id': 'poc-fixture-v1'}, success=False)
    assert 'POC requires' in output
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM information_schema.schemata WHERE schema_name='dbt_staging'").fetchone() == (0,)
