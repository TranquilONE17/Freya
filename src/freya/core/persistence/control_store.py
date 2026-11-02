import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[4] / "data"
CONTROL_DATABASE_PATH = DATA_DIR / "freya_control.db"

# Each entry is one schema version. Never edit an entry that has shipped;
# append a new one instead.
MIGRATIONS = [
    """
    CREATE TABLE policy_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        revision INTEGER NOT NULL,
        grant_epoch INTEGER NOT NULL
    );

    INSERT INTO policy_state (id, revision, grant_epoch)
    VALUES (1, 0, 1);

    CREATE TABLE policy_rule (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        capability TEXT NOT NULL,
        effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (subject, capability, effect)
    );

    CREATE TABLE audit_event (
        event_id INTEGER PRIMARY KEY,
        operation_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        kind TEXT NOT NULL
            CHECK (kind IN ('decision', 'dispatch', 'outcome')),
        actor TEXT NOT NULL,
        client TEXT NOT NULL,
        domain TEXT NOT NULL,
        capability TEXT NOT NULL,
        provider TEXT,
        target_ref TEXT,
        decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
        decision_reason TEXT NOT NULL,
        policy_revision INTEGER,
        grant_epoch INTEGER,
        outcome TEXT,
        error_summary TEXT,
        arguments_digest TEXT,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL
    );

    CREATE INDEX audit_event_operation
        ON audit_event (operation_id);

    CREATE TRIGGER audit_event_no_update
        BEFORE UPDATE ON audit_event
    BEGIN
        SELECT RAISE(ABORT, 'audit_event is append-only');
    END;

    CREATE TRIGGER audit_event_no_delete
        BEFORE DELETE ON audit_event
    BEGIN
        SELECT RAISE(ABORT, 'audit_event is append-only');
    END;

    CREATE TABLE audit_checkpoint (
        checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        last_event_id INTEGER NOT NULL,
        row_hash TEXT NOT NULL,
        sink TEXT,
        sink_status TEXT
    );
    """,
    # Version 2: remember which default rule sets have been applied, so a
    # new default set can be added later without restoring rules the owner
    # removed. Stores seeded under version 1 already hold the system-tools
    # set.
    """
    CREATE TABLE policy_seed (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    INSERT INTO policy_seed (name, applied_at)
    SELECT 'alpha-system-tools', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    FROM policy_state
    WHERE revision > 0;
    """,
]


class ControlStore:
    """
    SQLite storage for Freya's policy and audit state.

    This is deliberately a separate database from the memory store.
    The durability settings (WAL journal, synchronous=FULL) are a
    provisional alpha choice.

    Another small store that wants the same handling passes its own
    migrations and path; it never shares a file with this one.
    """

    def __init__(self, path=CONTROL_DATABASE_PATH, migrations=None):
        self.path = Path(path)
        self._migrations = migrations
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
            timeout=5.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA foreign_keys = ON")

        self._migrate()

    def _migrate(self):
        migrations = (
            self._migrations
            if self._migrations is not None
            else MIGRATIONS
        )

        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            current = row[0] or 0

            if current > len(migrations):
                raise RuntimeError(
                    "Control database schema version "
                    f"{current} is newer than this code supports."
                )

            for version in range(current + 1, len(migrations) + 1):
                for statement in _split_statements(
                    migrations[version - 1]
                ):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (version,),
                )

    @property
    def schema_version(self):
        row = self.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return row[0]

    def execute(self, sql, parameters=()):
        with self._lock:
            return self._connection.execute(sql, parameters)

    @contextmanager
    def transaction(self):
        """
        Run a write transaction. The write lock is taken up front so
        that read-then-write sequences cannot interleave.
        """
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def close(self):
        with self._lock:
            self._connection.close()


def _split_statements(script):
    """
    Split a migration script into statements, keeping trigger bodies
    (which contain their own semicolons) intact.
    """
    statements = []
    buffer = ""

    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""

    if buffer.strip():
        raise ValueError("Incomplete SQL statement in migration.")

    return statements
