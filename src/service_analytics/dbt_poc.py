"""Offline dbt experiment. Never opens or copies the operational database."""

import argparse
from datetime import date, datetime, timezone
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


def prepare_database(database=DEFAULT_DATABASE, rows=None):
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
            for run_id, inputs in (
                ('poc-previous', [{'unique_key': 'outside', 'status': 'Open'},
                                  {'unique_key': '101', 'status': 'Open'}]),
                (RUN_ID, rows),
            ):
                con.execute('''INSERT INTO pipeline_runs
                    (run_id, started_at, finished_at, window_start, window_end, status,
                     source_count, extracted_count)
                    VALUES (?, ?, ?, ?, ?, 'success', ?, ?)''',
                            [run_id, OBSERVED_AT, OBSERVED_AT, date(2026, 10, 1),
                             date(2026, 10, 4), len(inputs), len(inputs)])
                counts = load_raw(con, inputs, run_id, OBSERVED_AT)
                con.execute('''UPDATE pipeline_runs SET loaded_count = ?, rejected_count = ?,
                    duplicate_count = ? WHERE run_id = ?''',
                            [counts['loaded_count'], counts['rejected_count'],
                             counts['duplicate_count'], run_id])
            transform_sql(con, RUN_ID)
            metrics = check_quality(con, counts['loaded_count'])
            con.execute('UPDATE pipeline_runs SET flagged_count = ? WHERE run_id = ?',
                        [metrics['flagged_requests'], RUN_ID])
            hashes = original_hashes(con)
            con.execute('''CREATE TABLE dbt_poc_snapshot (
                snapshot_id VARCHAR PRIMARY KEY, run_id VARCHAR, raw_hash VARCHAR,
                members_hash VARCHAR, runs_hash VARCHAR, original_hashes JSON)''')
            con.execute('INSERT INTO dbt_poc_snapshot VALUES (?, ?, ?, ?, ?, ?)',
                        [SNAPSHOT_ID, RUN_ID, hashes['raw_requests'], hashes['run_members'],
                         hashes['pipeline_runs'], json.dumps(hashes, sort_keys=True)])
            con.execute('COMMIT')
        # Closed connection and exclusive destination: never copy a live writer or overwrite.
        with temporary_database.open('rb') as source, database.open('xb') as target:
            shutil.copyfileobj(source, target)
    return {'database': str(database), 'run_id': RUN_ID, 'snapshot_id': SNAPSHOT_ID,
            'rows': counts['loaded_count'], 'original_tables': len(hashes)}


def verify_database(database=DEFAULT_DATABASE):
    database = validate_test_path(database)
    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        expected = json.loads(con.execute('SELECT original_hashes FROM dbt_poc_snapshot').fetchone()[0])
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
                                            [RUN_ID, SNAPSHOT_ID]).fetchone()[0]
        if differences or provenance_differences:
            raise ValueError(f'Staging parity failed: {differences} row differences, '
                             f'{provenance_differences} provenance differences')
        count = con.execute('SELECT count(*) FROM dbt_staging.stg_service_requests').fetchone()[0]
    return {'rows': count, 'normalized_columns_compared': len(STAGING_COLUMNS),
            'row_differences': differences, 'provenance_differences': provenance_differences,
            'original_tables_unchanged': len(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'verify'))
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    result = (prepare_database if args.command == 'prepare' else verify_database)(args.database)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
