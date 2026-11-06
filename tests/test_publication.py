"""Offline foundations only; all DB/lock files use pytest's local temp directories."""

from dataclasses import replace
from datetime import date
import multiprocessing
import os
from pathlib import Path

import duckdb
import pytest
import requests

from service_analytics.dbt_poc import prepare_database
from service_analytics.pipeline import initialize, run_pipeline
from service_analytics.publication import (
    LockBusyError, Outcome, Phase, PublicationLock, PublicationTarget,
    ReconciliationRequired, RunState, assess_existing_state, get_publication_state,
    get_run, initialize_publication, record_run, validate_id,
)


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Publication tests must not use HTTP")
    monkeypatch.setattr(requests.sessions.Session, "request", denied)


@pytest.fixture
def metadata(tmp_path):
    with duckdb.connect(str(tmp_path / "metadata.duckdb")) as con:
        initialize_publication(con)
        yield con


def _advance_to(phase):
    state = RunState("run-1")
    for next_phase in list(Phase)[1:list(Phase).index(phase) + 1]:
        state = state.advance(next_phase, snapshot_id="snapshot-1")
    return state


def test_full_phase_chain_and_coherent_duplicate(metadata):
    state = RunState("run-1")
    record_run(metadata, state)
    for phase in list(Phase)[1:]:
        state = state.advance(phase, snapshot_id="snapshot-1")
        record_run(metadata, state)
        record_run(metadata, state)
        assert get_run(metadata, "run-1") == state
    assert state.outcome == Outcome.SUCCEEDED
    assert metadata.execute("SELECT count(*) FROM run_publications").fetchone()[0] == 1
    # Declared phases do not fabricate an actual published DB generation.
    assert get_publication_state(metadata) is None
    assert assess_existing_state(metadata) == "requires_reconciliation"


@pytest.mark.parametrize("identity", [None, "", " ", "a b", "../a", "x'; DROP TABLE x;--", "x" * 129])
def test_invalid_identity(identity):
    with pytest.raises(ValueError):
        validate_id(identity)


@pytest.mark.parametrize("kwargs", [
    {"phase": "unknown"}, {"attempt": 0}, {"attempt": True},
    {"phase": "raw_committed"}, {"snapshot_id": "invented-at-created"},
    {"outcome": "succeeded"}, {"outcome": "failed"},
    {"outcome": "requires_reconciliation", "error": "not committed"}, {"error": "unexpected"},
])
def test_inconsistent_state_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RunState("run-1", **kwargs)


@pytest.mark.parametrize("phase", [Phase.CANDIDATE_VALIDATED, Phase.TABLES_COMMITTED, Phase.PUBLISHED])
def test_forward_skips_are_rejected(phase):
    with pytest.raises(ValueError, match="next phase"):
        RunState("run-1").advance(phase, snapshot_id="snapshot-1")


def test_backward_unknown_and_identity_changes(metadata):
    state = _advance_to(Phase.RAW_COMMITTED)
    record_run(metadata, RunState("run-1"))
    record_run(metadata, state)
    with pytest.raises(ValueError):
        state.advance(Phase.CREATED)
    with pytest.raises(ValueError):
        state.advance("unknown")
    with pytest.raises(ValueError, match="cannot change"):
        state.advance(Phase.CANDIDATE_VALIDATED, snapshot_id="other")
    with pytest.raises(ValueError):
        record_run(metadata, replace(state, snapshot_id="other"))
    with pytest.raises(ValueError):
        record_run(metadata, replace(state, run_id="unregistered"))
    assert get_run(metadata, "run-1") == state


def test_failures_and_explicit_attempt_history(metadata):
    state = RunState("run-1")
    record_run(metadata, state)
    state = state.advance(Phase.RAW_COMMITTED, snapshot_id="snapshot-1")
    record_run(metadata, state)
    failure = state.failed("synthetic build failure")
    record_run(metadata, failure)
    retry = failure.retry()
    record_run(metadata, retry)
    assert get_run(metadata, "run-1", 1) == failure
    assert get_run(metadata, "run-1", 2) == retry
    with pytest.raises(ValueError):
        record_run(metadata, replace(retry, attempt=3))
    with pytest.raises(ValueError):
        record_run(metadata, replace(retry, snapshot_id="other"))
    with pytest.raises(ValueError):
        failure.advance(Phase.CANDIDATE_VALIDATED)


def test_post_t2_failure_requires_reconciliation():
    state = _advance_to(Phase.TABLES_COMMITTED)
    failure = state.failed("synthetic audit error")
    assert failure.phase == state.phase
    assert failure.outcome == Outcome.REQUIRES_RECONCILIATION
    with pytest.raises(ValueError):
        failure.retry()
    with pytest.raises(ValueError):
        replace(failure, outcome=Outcome.FAILED)


def _store_through(con, phase):
    state = RunState("run-1")
    record_run(con, state)
    for next_phase in list(Phase)[1:list(Phase).index(phase) + 1]:
        state = state.advance(next_phase, snapshot_id="snapshot-1")
        record_run(con, state)
    return state


@pytest.mark.parametrize("phase", [Phase.RAW_COMMITTED, Phase.TABLES_COMMITTED])
def test_terminal_failure_rejects_new_error_and_exact_replay_never_writes(metadata, phase):
    failure = _store_through(metadata, phase).failed("first error <detail> & evidence")
    record_run(metadata, failure)
    assert failure.failed(failure.error) is failure
    with pytest.raises(ValueError, match="immutable"):
        failure.failed("replacement error")
    with pytest.raises(ValueError):
        failure.advance(Phase.PUBLISHED)

    class ReadOnlyReplay:
        def execute(self, query, parameters):
            assert query.lstrip().startswith("SELECT"), "Exact replay must not issue a write"
            return metadata.execute(query, parameters)

    record_run(ReadOnlyReplay(), failure)
    assert get_run(metadata, "run-1") == failure


@pytest.mark.parametrize("phase", [Phase.RAW_COMMITTED, Phase.TABLES_COMMITTED])
@pytest.mark.parametrize("field", ["error", "snapshot_id", "phase", "outcome"])
def test_persistence_rejects_constructible_terminal_edits(metadata, phase, field):
    failure = _store_through(metadata, phase).failed("original error")
    record_run(metadata, failure)
    changes = {
        "error": {"error": "original error "},
        "snapshot_id": {"snapshot_id": "other-snapshot"},
        "phase": {"phase": list(Phase)[list(Phase).index(phase) + 1]},
        "outcome": {"outcome": Outcome.ACTIVE, "error": None},
    }
    altered = replace(failure, **changes[field])  # Valid value, illegal historical edit.
    with pytest.raises(ValueError, match="immutable"):
        record_run(metadata, altered)
    assert get_run(metadata, "run-1") == failure
    if phase == Phase.TABLES_COMMITTED:
        with pytest.raises(ValueError):
            failure.retry()


def test_retry_preserves_terminal_history_even_after_new_attempt(metadata):
    failure = _store_through(metadata, Phase.RAW_COMMITTED).failed("first attempt error")
    record_run(metadata, failure)
    retry = failure.retry()
    record_run(metadata, retry)
    with pytest.raises(ValueError, match="immutable"):
        record_run(metadata, replace(failure, error="rewritten after retry"))
    with pytest.raises(ValueError):
        record_run(metadata, replace(failure, outcome=Outcome.ACTIVE, error=None))
    record_run(metadata, failure)
    assert get_run(metadata, "run-1", 1) == failure
    assert get_run(metadata, "run-1", 2) == retry


def test_published_success_is_strictly_terminal_and_not_a_publication_certificate(metadata):
    published = _store_through(metadata, Phase.PUBLISHED)
    with pytest.raises(ValueError, match="post-publication handling is not implemented"):
        published.failed("inconsistency discovered later")
    with pytest.raises(ValueError):
        published.retry()
    with pytest.raises(ValueError):
        published.advance(Phase.PUBLISHED)
    # Constructor can express externally declared metadata; persistence still refuses the edit.
    inconsistent = replace(published, outcome=Outcome.REQUIRES_RECONCILIATION, error="late discovery")
    with pytest.raises(ValueError, match="immutable"):
        record_run(metadata, inconsistent)
    record_run(metadata, published)
    assert get_run(metadata, "run-1") == published
    assert get_publication_state(metadata) is None
    assert assess_existing_state(metadata) == "requires_reconciliation"


def test_stale_active_read_cannot_overwrite_concurrent_terminal_failure(metadata):
    active = _store_through(metadata, Phase.RAW_COMMITTED)
    concurrent_failure = active.failed("concurrent terminal error")

    class InterleavedConnection:
        def execute(self, query, parameters):
            if query.lstrip().startswith("SELECT") and "AND attempt=?" in query:
                row = metadata.execute(query, parameters).fetchone()
                record_run(metadata, concurrent_failure)

                class CapturedRead:
                    def fetchone(self):
                        return row
                return CapturedRead()
            return metadata.execute(query, parameters)

    with pytest.raises(ValueError, match="changed concurrently"):
        record_run(InterleavedConnection(), active.advance(Phase.CANDIDATE_VALIDATED))
    assert get_run(metadata, "run-1") == concurrent_failure


def test_empty_and_opt_in_initialization_is_idempotent(metadata):
    assert assess_existing_state(metadata) == "empty"
    assert get_publication_state(metadata) is None
    record_run(metadata, RunState("run-1"))
    initialize_publication(metadata)
    assert get_run(metadata, "run-1") == RunState("run-1")
    assert get_publication_state(metadata) is None


def test_legacy_success_is_not_imported_or_overwritten(tmp_path):
    with duckdb.connect(str(tmp_path / "legacy.duckdb")) as con:
        initialize(con)
        con.execute("INSERT INTO pipeline_runs (run_id, status) VALUES ('old', 'success')")
        con.execute("CREATE TABLE metrics AS SELECT 42::BIGINT AS total_requests")
        assert assess_existing_state(con) == "requires_reconciliation"
        initialize_publication(con)
        initialize_publication(con)
        assert con.execute("SELECT run_id, status FROM pipeline_runs").fetchall() == [("old", "success")]
        assert con.execute("SELECT * FROM metrics").fetchone() == (42,)
        assert get_publication_state(con) is None
        assert con.execute("SELECT count(*) FROM run_publications").fetchone() == (0,)
        assert assess_existing_state(con) == "requires_reconciliation"


def test_incompatible_metadata_rolls_back_ddl(tmp_path):
    with duckdb.connect(str(tmp_path / "incompatible.duckdb")) as con:
        con.execute("CREATE TABLE run_publications (original INTEGER)")
        con.execute("INSERT INTO run_publications VALUES (42)")
        with pytest.raises(ValueError, match="manual migration"):
            initialize_publication(con)
        assert con.execute("SELECT * FROM run_publications").fetchall() == [(42,)]
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='publication_state'").fetchone() == (0,)


def test_unrecognized_legacy_relations_are_not_called_empty(metadata):
    metadata.execute("CREATE TABLE unrecognized_legacy AS SELECT 42 AS value")
    assert assess_existing_state(metadata) == "requires_reconciliation"


def test_metadata_update_respects_caller_rollback(metadata):
    metadata.execute("BEGIN")
    record_run(metadata, RunState("rolled-back"))
    metadata.execute("ROLLBACK")
    assert get_run(metadata, "rolled-back") is None


def test_publication_pointer_is_singleton_but_not_certified(metadata):
    metadata.execute("INSERT INTO publication_state VALUES ('analytics', 'run-1', 1, 'snapshot-1', ?)", ["a" * 64])
    with pytest.raises(duckdb.ConstraintException):
        metadata.execute("INSERT INTO publication_state VALUES ('other', 'run-2', 1, 'snapshot-2', ?)", ["b" * 64])
    assert get_publication_state(metadata)["run_id"] == "run-1"
    assert assess_existing_state(metadata) == "requires_reconciliation"


def test_original_pipeline_and_poc_do_not_initialize_metadata(tmp_path, rows):
    db = tmp_path / "original.duckdb"
    run_pipeline(date(2026, 10, 1), date(2026, 10, 4), database=db,
                 output=tmp_path / "outputs", extractor=lambda *a, **kw: (rows, len(rows)))
    poc = tmp_path / "unchanged_poc.duckdb"
    assert prepare_database(poc, rows)["original_tables"] == 10
    for path in (db, poc):
        with duckdb.connect(str(path), read_only=True) as con:
            assert con.execute("""SELECT count(*) FROM information_schema.tables
                WHERE table_name IN ('run_publications', 'publication_state')""").fetchone() == (0,)


def _probe_worker(database, output, root, channel):
    """One actual spawned process, commanded over a pipe; no sleeps for coordination."""
    target = PublicationTarget(Path(database), Path(output), Path(root))
    try:
        while channel.recv() == "probe":
            try:
                with PublicationLock(target):
                    channel.send("acquired")
                    assert channel.recv() == "release"
                channel.send("released")
            except LockBusyError:
                channel.send("busy")
    finally:
        channel.close()


def _receive(channel):
    assert channel.poll(30), "Child process did not reach the expected IPC barrier"
    return channel.recv()


def test_real_process_exclusion_and_release(tmp_path):
    target = PublicationTarget(tmp_path / "shared.duckdb", tmp_path / "outputs", tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_probe_worker,
                              args=(str(target.database), str(target.output_root), str(tmp_path), child))
    process.start()
    child.close()
    try:
        with PublicationLock(target):
            parent.send("probe")
            assert _receive(parent) == "busy"
        with pytest.raises(RuntimeError, match="owner failed"):
            with PublicationLock(target):
                raise RuntimeError("owner failed")
        parent.send("probe")
        assert _receive(parent) == "acquired"
        with pytest.raises(LockBusyError):
            with PublicationLock(target):
                pytest.fail("Two coordinators acquired the same DB lock")
        parent.send("release")
        assert _receive(parent) == "released"
        parent.send("stop")
        process.join(30)
        assert process.exitcode == 0
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()  # Only this test's owned child, never a PID/name search.
            process.join(10)


def test_exception_release_distinct_databases_and_stable_binding(tmp_path):
    target = PublicationTarget(tmp_path / "one.duckdb", tmp_path / "out", tmp_path)
    other = PublicationTarget(tmp_path / "two.duckdb", tmp_path / "out", tmp_path)
    with pytest.raises(RuntimeError, match="synthetic"):
        with PublicationLock(target), PublicationLock(other):
            raise RuntimeError("synthetic owner exception")
    binding = target.lock_path.read_bytes()
    with PublicationLock(target), PublicationLock(other):
        pass
    assert target.lock_path.read_bytes() == binding
    assert not target.database.exists()  # Lock acquisition does not open/create DuckDB.
    incompatible = PublicationTarget(target.database, tmp_path / "different-output", tmp_path)
    with pytest.raises(ReconciliationRequired, match="different output"):
        with PublicationLock(incompatible):
            pass
    with PublicationLock(target):
        pass  # Binding rejection also released its descriptor.


def test_equivalent_paths_have_one_identity(tmp_path):
    (tmp_path / "alias").mkdir()
    first = PublicationTarget(tmp_path / "same.duckdb", tmp_path / "out", tmp_path)
    equivalent = PublicationTarget(tmp_path / "alias" / ".." / "same.duckdb", tmp_path / "." / "out", tmp_path)
    assert first == equivalent
    assert first.lock_path == equivalent.lock_path
    if os.name == "nt":
        uppercase = PublicationTarget(Path(str(first.database).upper()), Path(str(first.output_root).upper()), tmp_path)
        assert uppercase.lock_path == first.lock_path
    with PublicationLock(first):
        with pytest.raises(LockBusyError):
            with PublicationLock(equivalent):
                pass


@pytest.mark.parametrize("kind", ["relative", "outside-db", "outside-output", "extension", "directory", "output-file", "network"])
def test_unauthorized_or_ambiguous_paths(tmp_path, kind):
    db, out = tmp_path / "safe.duckdb", tmp_path / "out"
    if kind == "relative": db = Path("relative.duckdb")
    if kind == "outside-db": db = tmp_path.parent / "outside.duckdb"
    if kind == "outside-output": out = tmp_path.parent / "outside-output"
    if kind == "extension": db = tmp_path / "wrong.sql"
    if kind == "directory": db.mkdir()
    if kind == "output-file": out.write_text("not a directory")
    if kind == "network": db = Path("//server/share/test.duckdb")
    with pytest.raises(ValueError):
        PublicationTarget(db, out, tmp_path)


def test_corrupt_binding_is_not_silently_replaced(tmp_path):
    target = PublicationTarget(tmp_path / "safe.duckdb", tmp_path / "out", tmp_path)
    target.lock_path.write_bytes(b"\0partial-json")
    for _ in range(2):
        with pytest.raises(ReconciliationRequired, match="Incomplete"):
            with PublicationLock(target):
                pass
    assert target.lock_path.read_bytes() == b"\0partial-json"


def test_hardlink_alias_is_explicitly_unsupported(tmp_path):
    original = tmp_path / "original.duckdb"
    original.write_bytes(b"not opened as a database")
    os.link(original, tmp_path / "alias.duckdb")
    with pytest.raises(ValueError, match="Hard-linked"):
        PublicationTarget(original, tmp_path / "out", tmp_path)


def test_initialization_does_not_commit_callers_work(metadata):
    metadata.execute("BEGIN")
    metadata.execute("CREATE TABLE caller_work AS SELECT 42 AS value")
    with pytest.raises(duckdb.TransactionException):
        initialize_publication(metadata)
    metadata.execute("ROLLBACK")
    assert metadata.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='caller_work'").fetchone() == (0,)
