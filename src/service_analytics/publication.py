"""Opt-in metadata and cooperative local exclusion; no pipeline or publication IO.

Phases record caller assertions, not proof that RAW, models or files exist.
There is intentionally no writer for publication_state in this first delivery.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
import errno
import hashlib
import json
import os
from pathlib import Path
import re


class Phase(StrEnum):
    CREATED = "created"
    RAW_COMMITTED = "raw_committed"
    CANDIDATE_VALIDATED = "candidate_validated"
    ARTIFACTS_READY = "artifacts_ready"
    TABLES_COMMITTED = "tables_committed"
    PUBLISHED = "published"


class Outcome(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    SUCCEEDED = "succeeded"


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Identity must be 1..128 ASCII letters, digits, underscores or hyphens")
    return value


@dataclass(frozen=True)
class RunState:
    run_id: str
    attempt: int = 1
    phase: Phase = Phase.CREATED
    snapshot_id: str | None = None
    outcome: Outcome = Outcome.ACTIVE
    error: str | None = None

    def __post_init__(self):
        validate_id(self.run_id)
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        object.__setattr__(self, "phase", Phase(self.phase))
        object.__setattr__(self, "outcome", Outcome(self.outcome))
        if self.snapshot_id is not None:
            validate_id(self.snapshot_id)
        if (self.phase == Phase.CREATED) != (self.snapshot_id is None):
            raise ValueError("snapshot_id is absent at created and required after raw_committed")
        failed = self.outcome in (Outcome.FAILED, Outcome.REQUIRES_RECONCILIATION)
        if failed != (isinstance(self.error, str) and bool(self.error.strip())) or (
            self.error is not None and (not failed or len(self.error) > 2000)
        ):
            raise ValueError("Failure requires a nonblank error of at most 2000 characters")
        after_t2 = self.phase in (Phase.TABLES_COMMITTED, Phase.PUBLISHED)
        if failed and (self.outcome == Outcome.REQUIRES_RECONCILIATION) != after_t2:
            raise ValueError("After tables_committed a failure requires reconciliation, not rollback")
        if not failed and (self.outcome == Outcome.SUCCEEDED) != (self.phase == Phase.PUBLISHED):
            raise ValueError("Only published can have succeeded outcome")

    def advance(self, phase, *, snapshot_id=None):
        phases = list(Phase)
        phase = Phase(phase)
        if self.outcome != Outcome.ACTIVE or phases.index(phase) != phases.index(self.phase) + 1:
            raise ValueError("Only the next phase of an active attempt is allowed")
        if self.snapshot_id is not None and snapshot_id not in (None, self.snapshot_id):
            raise ValueError("snapshot_id cannot change within a run")
        return replace(self, phase=phase, snapshot_id=snapshot_id or self.snapshot_id,
                       outcome=Outcome.SUCCEEDED if phase == Phase.PUBLISHED else Outcome.ACTIVE)

    def failed(self, error):
        outcome = (Outcome.REQUIRES_RECONCILIATION
                   if self.phase in (Phase.TABLES_COMMITTED, Phase.PUBLISHED) else Outcome.FAILED)
        return replace(self, outcome=outcome, error=error)

    def retry(self):
        """Explicit metadata-only retry before T2; preserve the previous attempt's error."""
        if self.outcome != Outcome.FAILED:
            raise ValueError("Only a failed pre-T2 attempt can be retried")
        return replace(self, attempt=self.attempt + 1, outcome=Outcome.ACTIVE, error=None)


_COLUMNS = "run_id, attempt, phase, snapshot_id, outcome, error"
_PHASES = ", ".join(repr(p.value) for p in Phase)
_OUTCOMES = ", ".join(repr(o.value) for o in Outcome)
_DDL = (
    f"""CREATE TABLE IF NOT EXISTS main.run_publications (
        run_id VARCHAR NOT NULL, attempt INTEGER NOT NULL CHECK (attempt > 0),
        phase VARCHAR NOT NULL CHECK (phase IN ({_PHASES})), snapshot_id VARCHAR,
        outcome VARCHAR NOT NULL CHECK (outcome IN ({_OUTCOMES})), error VARCHAR,
        PRIMARY KEY (run_id, attempt),
        CHECK ((phase = 'created') = (snapshot_id IS NULL))
    )""",
    """CREATE TABLE IF NOT EXISTS main.publication_state (
        slot VARCHAR PRIMARY KEY CHECK (slot = 'analytics'),
        run_id VARCHAR NOT NULL, attempt INTEGER NOT NULL CHECK (attempt > 0),
        snapshot_id VARCHAR NOT NULL, artifact_manifest_sha256 VARCHAR NOT NULL
    )""",
)
_SCHEMAS = {
    "run_publications": [("run_id", "VARCHAR"), ("attempt", "INTEGER"), ("phase", "VARCHAR"),
                         ("snapshot_id", "VARCHAR"), ("outcome", "VARCHAR"), ("error", "VARCHAR")],
    "publication_state": [("slot", "VARCHAR"), ("run_id", "VARCHAR"), ("attempt", "INTEGER"),
                          ("snapshot_id", "VARCHAR"), ("artifact_manifest_sha256", "VARCHAR")],
}


def initialize_publication(con):
    """Explicit, atomic opt-in DDL. Owns its transaction; no active caller transaction.

Reject incompatible columns/keys. This is not a migration of legacy publications.
"""
    con.execute("BEGIN")
    try:
        for ddl in _DDL:
            con.execute(ddl)
        for table, expected in _SCHEMAS.items():
            actual = [row[:2] for row in con.execute(f"DESCRIBE main.{table}").fetchall()]
            keys = con.execute("""SELECT constraint_column_names FROM duckdb_constraints()
                WHERE schema_name='main' AND table_name=? AND constraint_type='PRIMARY KEY'""",
                               [table]).fetchall()
            expected_key = ["run_id", "attempt"] if table == "run_publications" else ["slot"]
            if actual != expected or keys != [(expected_key,)]:
                raise ValueError(f"Incompatible publication metadata: {table}; manual migration required")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def get_run(con, run_id, attempt=1):
    validate_id(run_id)
    if type(attempt) is not int or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    row = con.execute(f"SELECT {_COLUMNS} FROM main.run_publications WHERE run_id=? AND attempt=?",
                      [run_id, attempt]).fetchone()
    return RunState(*row) if row else None


def record_run(con, state):
    """Record a legal assertion; no hidden COMMIT. Caller coordinates writers/transactions."""
    old = get_run(con, state.run_id, state.attempt)
    values = (state.run_id, state.attempt, state.phase.value, state.snapshot_id,
              state.outcome.value, state.error)
    if old == state:
        return  # Coherent duplicate, including a duplicate published assertion.
    if old is None:
        previous = con.execute(f"""SELECT {_COLUMNS} FROM main.run_publications WHERE run_id=?
            ORDER BY attempt DESC LIMIT 1""", [state.run_id]).fetchone()
        expected = RunState(*previous).retry() if previous else RunState(state.run_id)
        if state != expected:
            raise ValueError("New run must start at created; retries must preserve identity and phase")
        con.execute("INSERT INTO main.run_publications VALUES (?, ?, ?, ?, ?, ?)", values)
        return
    if state.phase == old.phase:
        expected = old.failed(state.error)
    else:
        expected = old.advance(state.phase, snapshot_id=state.snapshot_id)
    if state != expected:
        raise ValueError("Incompatible run identity, outcome or phase update")
    # Compare all prior fields as well as the key: stale writers cannot overwrite a newer row.
    changed = con.execute("""UPDATE main.run_publications SET phase=?, snapshot_id=?, outcome=?, error=?
        WHERE run_id=? AND attempt=? AND phase=? AND snapshot_id IS NOT DISTINCT FROM ?
          AND outcome=? AND error IS NOT DISTINCT FROM ? RETURNING run_id""",
                          [state.phase.value, state.snapshot_id, state.outcome.value, state.error,
                           old.run_id, old.attempt, old.phase.value, old.snapshot_id,
                           old.outcome.value, old.error]).fetchone()
    if not changed:
        raise ValueError("Run metadata changed concurrently; reread before retrying")


def get_publication_state(con):
    """Read declared DB metadata only. It cannot certify files or an actual publication."""
    cursor = con.execute("SELECT * FROM main.publication_state")
    row = cursor.fetchone()
    return dict(zip([column[0] for column in cursor.description], row)) if row else None


def assess_existing_state(con):
    """Conservative preflight; deliberately never returns a verified publication."""
    tables = {row[0] for row in con.execute("""SELECT table_name FROM information_schema.tables
        WHERE table_schema='main'""").fetchall()}
    if tables - {"run_publications", "publication_state"}:
        return "requires_reconciliation"
    for table in ("run_publications", "publication_state"):
        if table in tables and con.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]:
            return "requires_reconciliation"
    return "empty"  # Not success: no publication has been established.


def _canonical(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ValueError("Use an absolute local path, not a relative, device or network path")
    return Path(os.path.normcase(str(path.resolve())))


@dataclass(frozen=True)
class PublicationTarget:
    database: Path
    output_root: Path
    allowed_root: Path

    def __post_init__(self):
        root, db, output = map(_canonical, (self.allowed_root, self.database, self.output_root))
        if not root.is_dir() or not db.is_relative_to(root) or not output.is_relative_to(root):
            raise ValueError("Database and output root must be within the explicit allowed root")
        if db.suffix != ".duckdb" or not db.parent.is_dir() or db.is_dir():
            raise ValueError("Use a .duckdb file with an existing parent directory")
        if db.exists() and db.stat().st_nlink > 1:
            raise ValueError("Hard-linked database aliases are not supported")
        if output == db or (output.exists() and not output.is_dir()):
            raise ValueError("output_root must designate a directory")
        for field, value in (("database", db), ("output_root", output), ("allowed_root", root)):
            object.__setattr__(self, field, value)

    @property
    def lock_path(self):
        key = hashlib.sha256(str(self.database).encode("utf-8")).hexdigest()
        return self.database.parent / f".publication-{key}.lock"


class LockBusyError(TimeoutError):
    """Another cooperative coordinator owns this database lock (nonblocking)."""


class ReconciliationRequired(ValueError):
    """Persistent lock binding is incompatible or incomplete; never overwrite it."""


class PublicationLock:
    """Stable descriptor lock, fail immediately when busy. Never unlink the lock file.

The bytes after the reserved lock byte bind one DB to one output root across
sessions. This metadata is not a publication marker or protection from raw DuckDB IO.
"""

    def __init__(self, target):
        self.target = target
        self._handle = None

    def __enter__(self):
        if self._handle is not None:
            raise RuntimeError("Lock instance is already acquired")
        path = self.target.lock_path
        if path.is_symlink():
            raise ValueError("Lock file must not be a symlink")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        handle = os.fdopen(fd, "r+b", buffering=0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            elif os.name == "posix":
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise NotImplementedError("Only Windows and POSIX local locking are supported")
            acquired = True
            binding = {"version": 1, "database": str(self.target.database),
                       "output_root": str(self.target.output_root)}
            if os.fstat(fd).st_size == 0:
                handle.write(b"\0" + json.dumps(binding, sort_keys=True).encode("utf-8"))
                os.fsync(fd)
            else:
                handle.seek(1)
                try:
                    existing = json.loads(handle.read(16384).decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    raise ReconciliationRequired("Incomplete lock binding; inspect manually") from exc
                if existing != binding:
                    raise ReconciliationRequired("Database is bound to a different output root or lock identity")
            self._handle = handle
            return self
        except OSError as exc:
            if not acquired and exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise LockBusyError("Database coordinator lock is busy; retry after its owner exits") from exc
            raise
        finally:
            if self._handle is None:
                handle.close()  # Also releases any OS lock acquired before a binding error.

    def __exit__(self, *exc_info):
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()
