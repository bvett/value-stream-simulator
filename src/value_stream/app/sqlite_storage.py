"""SQLite workspace adapter with normalized inputs, runs, and lazy result payloads."""

import sqlite3
import time
from contextlib import contextmanager
from threading import RLock
from typing import Iterator, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from value_stream.service.persistence.config import DatabaseConfig, DatabaseKind
from value_stream.service.persistence.database import SqliteDatabase
from value_stream.service.persistence.errors import DatabaseError, DatabaseErrorCode
from value_stream.service.persistence.migrations import DatabaseSchema, Migration, initial_schema
from value_stream.service.persistence.payloads import PayloadRegistry, PayloadTable
from value_stream.service.schemas import ResultData
from .generation import canonical, fingerprint
from .schemas import (
    AppModel,
    ENGINE_VERSION,
    GENERATOR_VERSION,
    OutcomeSummary,
    RunRequest,
    RunStatus,
    TaskSet,
    Workspace,
)
from .settings import AppSettings
from .storage import RunRecord, StorageUsage, UpstreamKind, WorkspaceOperations

ModelT = TypeVar("ModelT", bound=BaseModel)


class WorkspacePayload(Workspace):
    """Editor state; related task sets and runs are stored in their own tables."""

    task_sets: list[TaskSet] = Field(default_factory=list, exclude=True)
    runs: list[RunStatus] = Field(default_factory=list, exclude=True)


class RunHeader(RunStatus):
    """Run status without its independently stored scenario outcomes."""

    outcomes: list[OutcomeSummary] = Field(default_factory=list, exclude=True)


class RunPayload(AppModel):
    """Versioned run request and execution metadata, independent of raw results."""

    status: RunHeader
    request: RunRequest
    request_hash: str
    cache_keys: list[str]
    service_indices: list[int]
    service_outcomes: dict[int, int]
    upstream_kind: UpstreamKind | None = None
    upstream_identity: str | None = None


def workspace_schema() -> DatabaseSchema:
    """Return metadata version one followed by the real workspace schema migration."""

    def create_tables(connection: sqlite3.Connection) -> None:
        """Create application-owned tables and constraints in one migration transaction."""
        statements = (
            "CREATE TABLE workspaces (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
            "input_bytes INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "payload_version INTEGER NOT NULL, payload_json TEXT NOT NULL)",
            "CREATE TABLE task_sets (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL "
            "REFERENCES workspaces(id) ON DELETE CASCADE, spec_hash TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, "
            "generator_version TEXT NOT NULL, byte_count INTEGER NOT NULL, payload_version "
            "INTEGER NOT NULL, "
            "payload_json TEXT NOT NULL, UNIQUE(workspace_id, id), UNIQUE(workspace_id, "
            "spec_hash))",
            "CREATE TABLE result_blobs (result_key TEXT PRIMARY KEY, byte_count INTEGER NOT NULL, "
            "engine_version TEXT NOT NULL, generator_version TEXT NOT NULL, payload_version "
            "INTEGER NOT NULL, "
            "payload_json TEXT NOT NULL)",
            "CREATE TABLE runs (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL "
            "REFERENCES workspaces(id) ON DELETE CASCADE, task_set_id TEXT NOT NULL, "
            "request_id TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, input_bytes INTEGER NOT NULL, "
            "result_bytes INTEGER NOT NULL, reservation INTEGER NOT NULL, service_cursor "
            "INTEGER NOT NULL, "
            "last_cursor INTEGER NOT NULL, job_id TEXT, upstream_kind TEXT, upstream_identity"
            " TEXT, "
            "payload_version INTEGER NOT NULL, payload_json TEXT NOT NULL, "
            "UNIQUE(workspace_id, request_id), "
            "FOREIGN KEY(workspace_id, task_set_id) REFERENCES task_sets(workspace_id, id))",
            "CREATE TABLE run_outcomes (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE "
            "CASCADE, "
            "scenario_index INTEGER NOT NULL CHECK(scenario_index >= 0), scenario_id TEXT NOT"
            " NULL, "
            "cursor INTEGER CHECK(cursor > 0), status TEXT NOT NULL, "
            "result_key TEXT REFERENCES result_blobs(result_key), "
            "payload_version INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY "
            "KEY(run_id, scenario_index), "
            "UNIQUE(run_id, scenario_id), UNIQUE(run_id, cursor))",
        )
        for statement in statements:
            connection.execute(statement)
        for statement in (
            "CREATE INDEX run_workspace_order ON runs(workspace_id, created_at, id)",
            "CREATE INDEX run_active_state ON runs(state)",
            "CREATE INDEX run_task_sets ON runs(task_set_id)",
            "CREATE INDEX outcome_result_refs ON run_outcomes(result_key)",
            "CREATE INDEX tasks_workspace ON task_sets(workspace_id)",
        ):
            connection.execute(statement)

    return DatabaseSchema(
        DatabaseKind.APPLICATION,
        initial_schema(DatabaseKind.APPLICATION).migrations + (Migration(2, create_tables),),
    )


def workspace_payloads() -> PayloadRegistry:
    """Bind application models without importing them into shared database infrastructure."""
    registry = PayloadRegistry()
    for kind, model, table in (
        ("workspace", WorkspacePayload, "workspaces"),
        ("task_set", TaskSet, "task_sets"),
        ("run", RunPayload, "runs"),
        ("outcome", OutcomeSummary, "run_outcomes"),
        ("result", ResultData, "result_blobs"),
    ):
        registry.register(kind, model)
        registry.bind(PayloadTable(table, kind, introduced_in=2))
    return registry


class SqliteWorkspaceStore(WorkspaceOperations):
    """Persist workspace operations directly in SQLite transactions, without a memory mirror."""

    def __init__(self, config: DatabaseConfig, settings: AppSettings | None = None) -> None:
        """Open an explicitly constructed adapter; server lifespan wiring is a later milestone.

        Args:
            config: Application database ownership and initialization configuration.
            settings: Admission and storage limits, separate from connection settings.
        """
        if config.kind != DatabaseKind.APPLICATION:
            raise ValueError("Workspace storage requires an application database")
        self.settings = settings or AppSettings()
        self.payloads = workspace_payloads()
        self.database = SqliteDatabase(
            config, schema=workspace_schema(), payloads=self.payloads
        ).open()
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None
        self._writing = False

    @contextmanager
    def _atomic(self, write: bool = True) -> Iterator[None]:
        """Reuse a surrounding operation's connection without nesting transactions."""
        with self._lock:
            if self._connection is not None:
                if write and not self._writing:
                    raise RuntimeError("Cannot promote a read operation to a write")
                yield
                return
            context = self.database.transaction() if write else self.database.read()
            with context as connection:
                self._connection, self._writing = connection, write
                try:
                    yield
                finally:
                    self._connection, self._writing = None, False

    def _sql(self) -> sqlite3.Connection:
        """Require the operation's locked connection before issuing SQL."""
        if self._connection is None:
            raise RuntimeError("Storage operations require an atomic context")
        return self._connection

    def _decode(self, kind: str, version: object, text: object, model: type[ModelT]) -> ModelT:
        """Validate raw database values and narrow them to the expected model."""
        value = self.payloads.deserialize(kind, version, text)
        if not isinstance(value, model):
            raise DatabaseError(DatabaseErrorCode.INVALID, "Unexpected stored payload model")
        return value

    def _workspace(self, workspace_id: UUID) -> Workspace | None:
        """Assemble editor state and run summaries without selecting raw result blobs."""
        connection = self._sql()
        row = connection.execute(
            "SELECT payload_version, payload_json FROM workspaces WHERE id=?", (str(workspace_id),)
        ).fetchone()
        if row is None:
            return None
        state = self._decode("workspace", row[0], row[1], WorkspacePayload)
        workspace = Workspace.model_validate(state.model_dump())
        workspace.task_sets = [
            self._decode("task_set", version, text, TaskSet)
            for version, text in connection.execute(
                "SELECT payload_version, payload_json FROM task_sets WHERE workspace_id=? "
                "ORDER BY rowid",
                (str(workspace_id),),
            )
        ]
        workspace.runs = [
            self._status(run_id, version, text)
            for run_id, version, text in connection.execute(
                "SELECT id, payload_version, payload_json FROM runs WHERE workspace_id=? "
                "ORDER BY created_at, rowid",
                (str(workspace_id),),
            ).fetchall()
        ]
        return workspace

    def _status(self, run_id: str, version: object, text: object) -> RunStatus:
        """Join a run header to its ordered scenario snapshots."""
        payload = self._decode("run", version, text, RunPayload)
        outcomes = [
            self._decode("outcome", v, t, OutcomeSummary)
            for v, t in self._sql().execute(
                "SELECT payload_version, payload_json FROM run_outcomes WHERE run_id=? ORDER "
                "BY scenario_index",
                (run_id,),
            )
        ]
        return RunStatus.model_validate({**payload.status.model_dump(), "outcomes": outcomes})

    def _write_workspace(self, workspace: Workspace) -> None:
        """Write editor/task rows while leaving independently changed runs untouched."""
        connection = self._sql()
        encoded = self.payloads.serialize(
            "workspace", WorkspacePayload.model_validate(workspace.model_dump())
        )
        now = time.time()
        size = len(canonical(workspace.model_dump(mode="json", exclude={"runs"})).encode())
        connection.execute(
            "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, "
            "input_bytes=excluded.input_bytes, "
            "updated_at=excluded.updated_at, payload_version=excluded.payload_version, "
            "payload_json=excluded.payload_json",
            (str(workspace.id), workspace.revision, size, now, now, encoded.version, encoded.text),
        )
        for task_set in workspace.task_sets:
            encoded = self.payloads.serialize("task_set", task_set)
            connection.execute(
                "INSERT INTO task_sets VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    str(task_set.id),
                    str(workspace.id),
                    fingerprint(task_set.spec.model_dump()),
                    task_set.content_hash,
                    task_set.generator_version,
                    len(encoded.text.encode()),
                    encoded.version,
                    encoded.text,
                ),
            )
        keep = {str(t.id) for t in workspace.task_sets}
        for (identity,) in connection.execute(
            "SELECT id FROM task_sets WHERE workspace_id=?", (str(workspace.id),)
        ).fetchall():
            if identity not in keep:
                connection.execute("DELETE FROM task_sets WHERE id=?", (identity,))

    def _record(self, run_id: UUID) -> RunRecord | None:
        """Load a frozen run and result references, without loading result payloads."""
        row = (
            self._sql()
            .execute(
                "SELECT workspace_id, task_set_id, created_at, updated_at, result_bytes, "
                "reservation, service_cursor, payload_version, payload_json FROM runs WHERE id=?",
                (str(run_id),),
            )
            .fetchone()
        )
        if row is None:
            return None
        owner, task_id, created, updated, result_bytes, reservation, cursor, version, text = row
        payload = self._decode("run", version, text, RunPayload)
        tasks = (
            self._sql()
            .execute("SELECT payload_version, payload_json FROM task_sets WHERE id=?", (task_id,))
            .fetchone()
        )
        if tasks is None:
            raise DatabaseError(DatabaseErrorCode.INVALID, "Run task set is missing")
        status = self._status(str(run_id), version, text)
        references = {
            UUID(sid): key
            for sid, key in self._sql().execute(
                "SELECT scenario_id, result_key FROM run_outcomes WHERE run_id=? AND cursor "
                "IS NOT NULL AND status='succeeded'",
                (str(run_id),),
            )
        }
        return RunRecord(
            workspace_id=UUID(owner),
            status=status,
            task_set=self._decode("task_set", tasks[0], tasks[1], TaskSet),
            request=payload.request,
            request_hash=payload.request_hash,
            cache_keys=payload.cache_keys,
            results=references,
            service_indices=payload.service_indices,
            service_cursor=cursor,
            service_outcomes=payload.service_outcomes,
            reservation=reservation,
            result_bytes=result_bytes,
            created_at=created,
            updated_at=updated,
            upstream_kind=payload.upstream_kind,
            upstream_identity=payload.upstream_identity,
        )

    def _write_record(self, record: RunRecord) -> None:
        """Write one run's metadata and outcome references within the current transaction."""
        payload = RunPayload(
            status=RunHeader.model_validate(record.status.model_dump()),
            request=record.request,
            request_hash=record.request_hash,
            cache_keys=record.cache_keys,
            service_indices=record.service_indices,
            service_outcomes=record.service_outcomes,
            upstream_kind=record.upstream_kind,
            upstream_identity=record.upstream_identity,
        )
        encoded = self.payloads.serialize("run", payload)
        values = (
            str(record.status.id),
            str(record.workspace_id),
            str(record.task_set.id),
            str(record.request.request_id),
            record.request_hash,
            record.status.state,
            record.created_at,
            record.updated_at,
            len(canonical(record.status.model_dump(mode="json")).encode()),
            record.result_bytes,
            record.reservation,
            record.service_cursor,
            record.status.last_cursor,
            str(record.status.job_id) if record.status.job_id else None,
            record.upstream_kind,
            record.upstream_identity,
            encoded.version,
            encoded.text,
        )
        self._sql().execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at, "
            "input_bytes=excluded.input_bytes, result_bytes=excluded.result_bytes, "
            "reservation=excluded.reservation, "
            "service_cursor=excluded.service_cursor, last_cursor=excluded.last_cursor, "
            "job_id=excluded.job_id, "
            "upstream_kind=excluded.upstream_kind, upstream_identity=excluded.upstream_identity, "
            "payload_version=excluded.payload_version, payload_json=excluded.payload_json",
            values,
        )
        for index, outcome in enumerate(record.status.outcomes):
            encoded = self.payloads.serialize("outcome", outcome)
            key = record.results.get(outcome.scenario.id)
            if key is None and not outcome.cursor and index not in record.service_indices:
                key = record.cache_keys[index]
            self._sql().execute(
                "INSERT INTO run_outcomes VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id,scenario_index) DO UPDATE SET cursor=excluded.cursor, "
                "status=excluded.status,result_key=excluded.result_key,payload_version=excluded.payload_version,"
                " "
                "payload_json=excluded.payload_json",
                (
                    str(record.status.id),
                    index,
                    str(outcome.scenario.id),
                    outcome.cursor or None,
                    outcome.status,
                    key,
                    encoded.version,
                    encoded.text,
                ),
            )

    def _records(self) -> list[tuple[UUID, UUID]]:
        """Query indexed nonterminal owner/run identities."""
        return [
            (UUID(owner), UUID(identity))
            for owner, identity in self._sql().execute(
                "SELECT workspace_id,id FROM runs WHERE state NOT IN "
                "('completed','completed_with_errors','cancelled','failed') ORDER BY "
                "created_at,rowid"
            )
        ]

    def _find_request(self, workspace_id: UUID, request_id: UUID) -> RunRecord | None:
        """Use the unique request index before evaluating admission limits."""
        row = (
            self._sql()
            .execute(
                "SELECT id FROM runs WHERE workspace_id=? AND request_id=?",
                (str(workspace_id), str(request_id)),
            )
            .fetchone()
        )
        return self._record(UUID(row[0])) if row else None

    def _blob_size(self, key: str) -> int | None:
        """Fetch only immutable result size metadata."""
        row = (
            self._sql()
            .execute("SELECT byte_count FROM result_blobs WHERE result_key=?", (key,))
            .fetchone()
        )
        return row[0] if row else None

    def _blob(self, key: str) -> ResultData:
        """Decode raw result JSON only on an explicit result/cache read."""
        row = (
            self._sql()
            .execute(
                "SELECT payload_version,payload_json FROM result_blobs WHERE result_key=?", (key,)
            )
            .fetchone()
        )
        if row is None:
            raise DatabaseError(DatabaseErrorCode.INVALID, "Referenced result is missing")
        return self._decode("result", row[0], row[1], ResultData)

    def _put_blob(self, key: str, result: ResultData, size: int) -> None:
        """Store one immutable execution result with its original provenance."""
        encoded = self.payloads.serialize("result", result)
        self._sql().execute(
            "INSERT INTO result_blobs VALUES (?,?,?,?,?,?)",
            (key, size, ENGINE_VERSION, GENERATOR_VERSION, encoded.version, encoded.text),
        )

    def _usage(self) -> StorageUsage:
        """Aggregate logical serialized input bytes, blobs, and outstanding reservations."""
        connection = self._sql()
        workspaces, workspace_bytes = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(input_bytes),0) FROM workspaces"
        ).fetchone()
        run_bytes, reservations = connection.execute(
            "SELECT COALESCE(SUM(input_bytes),0),COALESCE(SUM(reservation),0) FROM runs"
        ).fetchone()
        result_bytes = connection.execute(
            "SELECT COALESCE(SUM(byte_count),0) FROM result_blobs"
        ).fetchone()[0]
        return StorageUsage(
            workspaces,
            workspace_bytes + run_bytes,
            result_bytes,
            reservations,
            len(self._records()),
        )

    def _remove_run(self, run_id: UUID) -> None:
        """Delete a run; foreign keys remove only its outcome references."""
        self._sql().execute("DELETE FROM runs WHERE id=?", (str(run_id),))

    def _remove_workspace(self, workspace_id: UUID) -> None:
        """Delete runs before their frozen task sets and owning workspace."""
        self._sql().execute("DELETE FROM runs WHERE workspace_id=?", (str(workspace_id),))
        self._sql().execute("DELETE FROM workspaces WHERE id=?", (str(workspace_id),))

    def _collect_blobs(self) -> None:
        """Reclaim unreferenced results; pending cached outcomes hold foreign-key references."""
        self._sql().execute(
            "DELETE FROM result_blobs WHERE NOT EXISTS "
            "(SELECT 1 FROM run_outcomes WHERE result_key=result_blobs.result_key)"
        )

    def close(self) -> None:
        """Release the connection and process ownership after callers finish using the store."""
        with self._lock:
            self.database.close()
