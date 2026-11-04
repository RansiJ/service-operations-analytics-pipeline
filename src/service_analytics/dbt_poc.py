"""Offline dbt experiment. Never opens or copies the operational database."""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import duckdb

from .pipeline import check_quality, initialize, load_raw, transform_sql

DEFAULT_DATABASE = Path('analytics/sandbox/service_requests_poc.duckdb')
RUN_ID = 'poc-selected'
SNAPSHOT_ID = 'poc-fixture-v1'
OBSERVED_AT = datetime(2026, 10, 14, tzinfo=timezone.utc)
SOURCE_ORDER = {
    'raw_requests': 'unique_key',
    'run_members': 'run_id, unique_key',
    'pipeline_runs': 'run_id',
}
STAGING_COLUMNS = (
    'request_id', 'created_at', 'closed_at', 'agency', 'agency_name',
    'category', 'borough', 'source_status', 'source_updated_at', 'observed_at',
)
ANALYTICAL_MODELS = {
    'requests': 'fct_service_requests',
    'metrics': 'mart_overall_metrics',
    'daily_metrics': 'mart_daily_metrics',
    'category_metrics': 'mart_category_metrics',
    'agency_metrics': 'mart_agency_metrics',
    'quality_issues': 'mart_quality_issues',
}
SCENARIOS = ('small', 'edge', 'empty', 'zero-baseline')


def fixture_rows():
    """Small synthetic dataset; integration tests additionally reuse tests/conftest.py."""
    base = {'created_date': '2026-10-01T00:00:00.000', 'agency': ' dot ',
            'agency_name': ' Department  of Transportation ',
            'complaint_type': 'Street  Condition', 'borough': ' Queens ',
            'source_updated_at': '2026-10-13T20:00:00Z'}
    return [
        {**base, 'unique_key': '101', 'status': ' Closed ', 'closed_date': '2026-10-01T02:00:00'},
        {**base, 'unique_key': '102', 'status': ' In   Progress '},
        {**base, 'unique_key': '103', 'status': 'Closed', 'closed_date': '2026-09-30T23:00:00'},
        {**base, 'unique_key': '104', 'created_date': 'bad', 'closed_date': 'bad',
         'agency': '', 'complaint_type': None, 'status': 'Closed'},
        {**base, 'unique_key': '105', 'status': None, 'closed_date': ' '},
        {**base, 'unique_key': '106', 'status': 'Open', 'closed_date': '2026-10-01T03:00:00'},
        {**base, 'unique_key': '107', 'status': 'Closed', 'closed_date': base['created_date']},
        {'status': 'Open'},
    ]


def edge_case_rows():
    """Weekly threshold, all lifecycle labels, duration boundaries and overlapping flags."""
    rows = []
    statuses = ('Open', 'In Progress', 'Assigned', 'Started', 'Pending', 'Closed')
    base = {'agency': ' dot ', 'agency_name': ' Test  Agency ',
            'complaint_type': 'Street  Condition', 'borough': ' Queens '}
    for day in range(1, 9):
        for number in range(3 if day == 8 else 2):
            created = f'2026-10-{day:02d}T00:00:00'
            status = statuses[(day + number) % len(statuses)]
            rows.append({**base, 'unique_key': f'day-{day}-{number}',
                         'created_date': created, 'status': status,
                         'closed_date': created if status == 'Closed' else None})
    # Other edge cases occur on day 10 or have invalid dates, preserving day 8's
    # exact 3 / mean(2,2,2,2,2,2,2) = 1.5 boundary and day 9's zero volume.
    created = datetime(2026, 10, 10)
    for label, hours in [('zero', 0), ('under24', 23.5), ('at24', 24),
                         ('under72', 71.5), ('at72', 72), ('under168', 167.5), ('at168', 168)]:
        rows.append({**base, 'unique_key': f'band-{label}', 'status': 'Closed',
                     'created_date': created.isoformat(),
                     'closed_date': (created + timedelta(hours=hours)).isoformat()})
    rows.extend([
        {'unique_key': 'overlap', 'created_date': 'bad', 'closed_date': 'bad',
         'status': 'Unexpected', 'agency': '', 'complaint_type': None},
        {**base, 'unique_key': 'negative', 'created_date': created.isoformat(),
         'closed_date': (created - timedelta(hours=1)).isoformat(), 'status': 'Closed'},
        {**base, 'unique_key': 'open-closure', 'created_date': created.isoformat(),
         'closed_date': created.isoformat(), 'status': 'Open'},
        {**base, 'unique_key': 'closed-no-date', 'created_date': created.isoformat(), 'status': 'Closed'},
        {**base, 'unique_key': 'flagged-eligible', 'created_date': created.isoformat(),
         'closed_date': (created + timedelta(hours=1)).isoformat(), 'status': 'Closed', 'agency': ''},
        {**base, 'unique_key': 'microseconds', 'created_date': ' 2026-10-10T00:00:00.123456 ',
         'closed_date': '2026-10-10T00:00:01.123456', 'status': ' Closed ',
         'source_updated_at': '2026-10-13T15:00:00-04:00'},
        {'unique_key': 'whitespace', 'created_date': created.isoformat(),
         'agency': '\t', 'complaint_type': '\t', 'status': '\tOpen\t'},
        {**base, 'unique_key': 'changed', 'created_date': created.isoformat(), 'status': 'Open'},
        {**base, 'unique_key': 'changed', 'created_date': created.isoformat(),
         'closed_date': created.isoformat(), 'status': 'Closed'},
        {}, {'unique_key': ' '}, {'unique_key': 42},
    ])
    return rows


def prepare_scenario(database=DEFAULT_DATABASE, scenario='small', *, run_id=RUN_ID):
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown POC scenario: {scenario}')
    rows = {'small': fixture_rows, 'edge': edge_case_rows, 'empty': lambda: [],
            'zero-baseline': lambda: [{'unique_key': 'after-zero-week',
                                      'created_date': '2026-10-08T00:00:00', 'status': 'Open'}]}[scenario]()
    end = date(2026, 10, {'small': 4, 'edge': 13, 'empty': 4, 'zero-baseline': 9}[scenario])
    snapshot_id = SNAPSHOT_ID if scenario == 'small' else f'poc-{scenario}-v2'
    return prepare_database(database, rows, window_end=end, run_id=run_id, snapshot_id=snapshot_id)


def fingerprint(con, table):
    # All identifiers come from the schema, not user-supplied SQL.
    order = SOURCE_ORDER.get(table, 'to_json(t)')
    return con.execute(
        f'''SELECT md5(coalesce(string_agg(to_json(t), chr(10) ORDER BY {order}), ''))
            FROM main."{table}" t'''
    ).fetchone()[0]


def original_hashes(con):
    tables = con.execute("""SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
          AND table_name <> 'dbt_poc_snapshot' ORDER BY table_name""").fetchall()
    return {table: fingerprint(con, table) for (table,) in tables}


def validate_test_path(database):
    database = Path(database).resolve()
    if not database.name.endswith('_poc.duckdb'):
        raise ValueError('Use a dedicated *_poc.duckdb test database')
    return database


def prepare_database(database=DEFAULT_DATABASE, rows=None, *,
                     window_start=date(2026, 10, 1), window_end=date(2026, 10, 4),
                     run_id=RUN_ID, snapshot_id=SNAPSHOT_ID):
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError('Explicit nonempty run_id and snapshot_id required')
    from .extract import validate_window
    validate_window(window_start, window_end, 100_000, 5_000)
    database = validate_test_path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        raise FileExistsError(f'Refusing to overwrite {database}')
    rows = fixture_rows() if rows is None else rows
    with TemporaryDirectory(prefix='dbt-poc-', dir=database.parent) as directory:
        temporary_database = Path(directory) / database.name
        with duckdb.connect(str(temporary_database)) as con:
            con.execute("SET TimeZone = 'UTC'")
            con.execute('BEGIN')
            initialize(con)
            for cohort_id, inputs in (
                ('poc-previous', [{'unique_key': 'outside', 'status': 'Open'},
                                  {'unique_key': '101', 'status': 'Open'}]),
                (run_id, rows),
            ):
                con.execute('''INSERT INTO pipeline_runs
                    (run_id, started_at, finished_at, window_start, window_end, status,
                     source_count, extracted_count)
                    VALUES (?, ?, ?, ?, ?, 'success', ?, ?)''',
                            [cohort_id, OBSERVED_AT, OBSERVED_AT, window_start,
                             window_end, len(inputs), len(inputs)])
                counts = load_raw(con, inputs, cohort_id, OBSERVED_AT)
                con.execute('''UPDATE pipeline_runs SET loaded_count = ?, rejected_count = ?,
                    duplicate_count = ? WHERE run_id = ?''',
                            [counts['loaded_count'], counts['rejected_count'],
                             counts['duplicate_count'], cohort_id])
            transform_sql(con, run_id)
            metrics = check_quality(con, counts['loaded_count'])
            con.execute('UPDATE pipeline_runs SET flagged_count = ? WHERE run_id = ?',
                        [metrics['flagged_requests'], run_id])
            hashes = original_hashes(con)
            con.execute('''CREATE TABLE dbt_poc_snapshot (
                snapshot_id VARCHAR PRIMARY KEY, run_id VARCHAR, raw_hash VARCHAR,
                members_hash VARCHAR, runs_hash VARCHAR, original_hashes JSON)''')
            con.execute('INSERT INTO dbt_poc_snapshot VALUES (?, ?, ?, ?, ?, ?)',
                        [snapshot_id, run_id, hashes['raw_requests'], hashes['run_members'],
                         hashes['pipeline_runs'], json.dumps(hashes, sort_keys=True)])
            con.execute('COMMIT')
        # Closed connection and exclusive destination: never copy a live writer or overwrite.
        with temporary_database.open('rb') as source, database.open('xb') as target:
            shutil.copyfileobj(source, target)
    return {'database': str(database), 'run_id': run_id, 'snapshot_id': snapshot_id,
            'rows': counts['loaded_count'], 'original_tables': len(hashes)}


def verify_database(database=DEFAULT_DATABASE, *, run_id=RUN_ID, snapshot_id=SNAPSHOT_ID):
    """Phase 1 staging API retained for callers; CLI verify uses full parity below."""
    database = validate_test_path(database)
    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        snapshots = con.execute('SELECT run_id, snapshot_id, original_hashes FROM dbt_poc_snapshot').fetchall()
        if len(snapshots) != 1 or snapshots[0][:2] != (run_id, snapshot_id):
            raise ValueError('Selected run_id/snapshot_id does not match the known snapshot')
        expected = json.loads(snapshots[0][2])
        if original_hashes(con) != expected:
            raise ValueError('Original tables changed after POC preparation')
        columns = ', '.join(STAGING_COLUMNS)
        differences = con.execute(f'''
            WITH expected AS (SELECT {columns} FROM main.requests),
                 actual AS (SELECT {columns} FROM dbt_staging.stg_service_requests)
            SELECT count(*) FROM (
                (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
                UNION ALL
                (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected))''').fetchone()[0]
        # Raw closure text and provenance were added to staging and also need parity.
        provenance_differences = con.execute('''SELECT count(*)
            FROM dbt_staging.stg_service_requests s
            LEFT JOIN main.raw_requests r ON s.request_id = r.unique_key
            WHERE s.raw_closed_date IS DISTINCT FROM r.closed_date
               OR s.last_run_id IS DISTINCT FROM r.last_run_id
               OR s.run_id IS DISTINCT FROM ? OR s.snapshot_id IS DISTINCT FROM ?''',
                                            [run_id, snapshot_id]).fetchone()[0]
        if differences or provenance_differences:
            raise ValueError(f'Staging parity failed: {differences} row differences, '
                             f'{provenance_differences} provenance differences')
        count = con.execute('SELECT count(*) FROM dbt_staging.stg_service_requests').fetchone()[0]
    return {'rows': count, 'normalized_columns_compared': len(STAGING_COLUMNS),
            'row_differences': differences, 'provenance_differences': provenance_differences,
            'original_tables_unchanged': len(expected)}


def verify_full_parity(database=DEFAULT_DATABASE, *, run_id=RUN_ID, snapshot_id=SNAPSHOT_ID):
    """Compare all six original outputs by schema and unordered exact row multisets.

    No float tolerance: the same pinned DuckDB evaluates identical expressions.
    EXCEPT ALL preserves duplicates and compares NULL, timestamps and ordered lists.
    """
    report = verify_database(database, run_id=run_id, snapshot_id=snapshot_id)
    models = {}
    with duckdb.connect(str(validate_test_path(database)), read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        for original, model in ANALYTICAL_MODELS.items():
            expected_schema = [row[:2] for row in con.execute(f'DESCRIBE main.{original}').fetchall()]
            actual_schema = [row[:2] for row in con.execute(f'DESCRIBE dbt_staging.{model}').fetchall()]
            if actual_schema != expected_schema:
                raise ValueError(f'Schema parity failed for {model}: {actual_schema} != {expected_schema}')
            columns = ', '.join(f'"{name}"' for name, _ in expected_schema)
            differences = con.execute(f'''SELECT count(*) FROM (
                (SELECT {columns} FROM main.{original} EXCEPT ALL
                 SELECT {columns} FROM dbt_staging.{model})
                UNION ALL
                (SELECT {columns} FROM dbt_staging.{model} EXCEPT ALL
                 SELECT {columns} FROM main.{original}))''').fetchone()[0]
            if differences:
                raise ValueError(f'Full parity failed for {model}: {differences} row differences')
            models[model] = {'original': original,
                             'rows': con.execute(f'SELECT count(*) FROM main.{original}').fetchone()[0],
                             'columns': len(expected_schema), 'row_differences': differences}
    return {**report, 'full_parity': True, 'models': models}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'verify'))
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--scenario', choices=SCENARIOS, default='small', help='Synthetic preparation scenario')
    parser.add_argument('--run-id', default=RUN_ID)
    parser.add_argument('--snapshot-id', default=SNAPSHOT_ID, help='Explicit snapshot to verify; never infer latest')
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare_scenario(args.database, args.scenario, run_id=args.run_id)
    else:
        result = verify_full_parity(args.database, run_id=args.run_id, snapshot_id=args.snapshot_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
