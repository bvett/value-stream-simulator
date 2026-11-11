"""Transactional simulation jobs with durable cursors and startup finalization."""

import sqlite3
import time
from contextlib import contextmanager
from threading import RLock
from typing import Iterator
from uuid import UUID, uuid4

from pydantic import BaseModel

from ..job_store import (
    CapacityExceeded,
    JobOperations,
    JobNotFound,
    SubmissionConflict,
    _Job,
)
from ..schemas import JobStatus, OutcomeData, OutcomePage
from ..settings import ServiceSettings
from .config import DatabaseConfig, DatabaseKind
from .database import SqliteDatabase
from .errors import DatabaseError, DatabaseErrorCode
from .migrations import DatabaseSchema, Migration, initial_schema
from .payloads import PayloadRegistry, PayloadTable


class JobMetadata(BaseModel):
    """Versioned optional job metadata, independent of execution requests."""

    metadata_version: int = 1


def job_schema() -> DatabaseSchema:
    """Add normalized simulation tables to the ownership metadata foundation."""

    def initialize(connection: sqlite3.Connection) -> None:
        """Create bounded service data with cascading submission/outcome ownership."""
        statements = (
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL "
            "CHECK(state IN ('queued','running','completed','completed_with_errors','cancelled')), "
            "model_count INTEGER NOT NULL CHECK(model_count > 0), "
            "result_bytes INTEGER NOT NULL CHECK(result_bytes >= 0), "
            "created_at REAL NOT NULL, terminal_at REAL, "
            "last_cursor INTEGER NOT NULL CHECK(last_cursor >= 0), "
            "payload_version INTEGER NOT NULL, payload_json TEXT NOT NULL)",
            "CREATE TABLE job_models (job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
            "model_index INTEGER NOT NULL CHECK(model_index >= 0), "
            "state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')), "
            "cursor INTEGER CHECK(cursor > 0), byte_count INTEGER NOT NULL CHECK(byte_count >= 0), "
            "payload_version INTEGER, payload_json TEXT, PRIMARY KEY(job_id,model_index), "
            "UNIQUE(job_id,cursor), CHECK ((state IN ('queued','running') AND cursor IS NULL "
            "AND payload_version IS NULL AND payload_json IS NULL) OR "
            "(state IN ('succeeded','failed','cancelled') AND cursor IS NOT NULL "
            "AND payload_version IS NOT NULL AND payload_json IS NOT NULL)))",
            "CREATE TABLE submissions (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
            "job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE)",
            "CREATE INDEX jobs_expiry ON jobs(terminal_at)",
            "CREATE INDEX jobs_active ON jobs(state)",
        )
        for statement in statements:
            connection.execute(statement)

    base = initial_schema(DatabaseKind.SIMULATION)

    def validate(connection: sqlite3.Connection, version: int) -> None:
        """Reject relational counters or identities inconsistent with durable outcomes."""
        if version < 2:
            return
        registry = job_payloads()
        for job_id, state, count, size, terminal, cursor in connection.execute(
            "SELECT id,state,model_count,result_bytes,terminal_at,last_cursor FROM jobs"
        ):
            UUID(job_id)
            rows = connection.execute(
                "SELECT model_index,state,cursor,byte_count,payload_version,payload_json "
                "FROM job_models WHERE job_id=? ORDER BY model_index",
                (job_id,),
            ).fetchall()
            valid = (
                [row[0] for row in rows] == list(range(count))
                and sum(row[3] for row in rows) == size
                and sorted(row[2] for row in rows if row[2] is not None)
                == list(range(1, cursor + 1))
            )
            unfinished = any(row[1] in ("queued", "running") for row in rows)
            valid = valid and (unfinished == (terminal is None))
            if unfinished:
                valid = valid and state in ("queued", "running")
            elif state == "cancelled":
                valid = valid and any(row[1] == "cancelled" for row in rows)
            else:
                expected = (
                    "completed_with_errors"
                    if any(row[1] == "failed" for row in rows)
                    else "completed"
                )
                valid = valid and state == expected
            for index, model_state, completion, byte_count, payload_version, text in rows:
                if text is None:
                    valid = valid and byte_count == 0
                    continue
                outcome = registry.deserialize("outcome", payload_version, text)
                if not isinstance(outcome, OutcomeData):
                    raise TypeError("Expected an outcome payload")
                result_size = (
                    len(outcome.result.model_dump_json().encode("utf-8"))
                    if outcome.result is not None
                    else 0
                )
                valid = valid and (
                    outcome.model_index == index
                    and outcome.status == model_state
                    and outcome.cursor == completion
                    and byte_count == result_size
                )
            if not valid:
                raise DatabaseError(
                    DatabaseErrorCode.INVALID, "Stored job counters or outcomes are inconsistent."
                )
        for (submission_id,) in connection.execute("SELECT id FROM submissions"):
            UUID(submission_id)

    return DatabaseSchema(base.kind, base.migrations + (Migration(2, initialize),), validate)


def job_payloads() -> PayloadRegistry:
    """Register service-only payload models and independent JSON versions."""
    registry = PayloadRegistry()
    registry.register("job", JobMetadata)
    registry.register("outcome", OutcomeData)
    registry.bind(PayloadTable("jobs", "job", introduced_in=2))
    registry.bind(PayloadTable("job_models", "outcome", introduced_in=2, nullable=True))
    return registry


class SqliteJobStore(JobOperations):
    """Reuse job transitions with SQL snapshots, never an in-memory job mirror.

    Construction acquires ownership, validates/migrates, and finalizes interrupted
    jobs before expiry or any scheduler can inspect the store. Every public
    operation is one transaction; worker waits happen outside these operations.
    """

    def __init__(self, config: DatabaseConfig, settings: ServiceSettings | None = None) -> None:
        """Open a simulation database and recover committed unfinished work.

        Args:
            config: Explicit simulation database location and bundle policy.
            settings: Service capacity and terminal retention policy.
        """
        if config.kind != DatabaseKind.SIMULATION:
            raise ValueError("Job storage requires a simulation database")
        self.settings = settings or ServiceSettings()
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None
        self.payloads = job_payloads()
        self.database = SqliteDatabase(config, schema=job_schema(), payloads=self.payloads).open()
        self._recovering = True
        try:
            self.interrupt_unfinished()
            self._recovering = False
            with self._atomic():
                self._prune()
        except BaseException:
            self.database.close()
            raise

    @contextmanager
    def _atomic(self) -> Iterator[object]:
        """Reuse the outer transaction for nested transition/admission operations."""
        with self._lock:
            if self._connection is not None:
                yield self._connection
            else:
                with self.database.transaction() as connection:
                    self._connection = connection
                    try:
                        yield connection
                    finally:
                        self._connection = None

    @property
    def _sql(self) -> sqlite3.Connection:
        """Require every SQL operation to participate in an owned transaction."""
        if self._connection is None:
            raise RuntimeError("Job operation requires a transaction")
        return self._connection

    def _prune(self) -> None:
        """Expire terminal service jobs and their submission mappings only."""
        if self._recovering:
            return
        self._sql.execute(
            "DELETE FROM jobs WHERE terminal_at IS NOT NULL AND terminal_at <= ?",
            (time.time() - self.settings.job_ttl_seconds,),
        )

    def _unfinished(self) -> list[UUID]:
        """Select recovery work before any TTL pruning."""
        return [
            UUID(row[0])
            for row in self._sql.execute(
                "SELECT id FROM jobs WHERE terminal_at IS NULL ORDER BY created_at,id"
            )
        ]

    def _retained_bytes(self) -> int:
        """Read committed logical result usage for transactional admission."""
        return self._sql.execute("SELECT coalesce(sum(result_bytes),0) FROM jobs").fetchone()[0]

    def _get(self, job_id: UUID) -> _Job:
        """Load transition metadata without decoding immutable committed outcomes.

        SQL snapshots carry the committed cursor and only newly appended outcomes;
        page() is the explicit read boundary for retained result payloads.
        """
        self._prune()
        row = self._sql.execute(
            "SELECT state,created_at,result_bytes,terminal_at,last_cursor FROM jobs WHERE id=?",
            (str(job_id),),
        ).fetchone()
        if row is None:
            raise JobNotFound(str(job_id))
        states = [
            item[0]
            for item in self._sql.execute(
                "SELECT state FROM job_models WHERE job_id=? ORDER BY model_index", (str(job_id),)
            )
        ]
        return _Job(
            job_id,
            states,
            row[1],
            status=row[0],
            result_bytes=row[2],
            terminal_at=row[3],
            last_cursor=row[4],
        )

    def status(self, job_id: UUID) -> JobStatus:
        """Poll relational counters without decoding retained result payloads."""
        with self._atomic():
            self._prune()
            row = self._sql.execute(
                "SELECT state,model_count,last_cursor FROM jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise JobNotFound(str(job_id))
            counts = dict(
                self._sql.execute(
                    "SELECT state,count(*) FROM job_models WHERE job_id=? GROUP BY state",
                    (str(job_id),),
                )
            )
            return JobStatus(
                job_id=job_id,
                status=row[0],
                total_models=row[1],
                last_cursor=row[2],
                queued_models=counts.get("queued", 0),
                running_models=counts.get("running", 0),
                succeeded_models=counts.get("succeeded", 0),
                failed_models=counts.get("failed", 0),
                cancelled_models=counts.get("cancelled", 0),
            )

    def page(self, job_id: UUID, after: int) -> OutcomePage:
        """Decode only completions newer than the requested durable cursor."""
        with self._atomic():
            status = self.status(job_id)
            outcomes: list[OutcomeData] = []
            for version, text in self._sql.execute(
                "SELECT payload_version,payload_json FROM job_models "
                "WHERE job_id=? AND cursor>? ORDER BY cursor",
                (str(job_id), after),
            ):
                outcome = self.payloads.deserialize("outcome", version, text)
                if not isinstance(outcome, OutcomeData):
                    raise TypeError("Expected an outcome payload")
                outcomes.append(outcome)
            return OutcomePage(outcomes=outcomes, next_cursor=status.last_cursor)

    def start_model(self, job_id: UUID, index: int) -> bool:
        """Conditionally start a queued model without reading outcome JSON."""
        with self._atomic():
            status = self.status(job_id)
            if not 0 <= index < status.total_models:
                raise IndexError(index)
            changed = self._sql.execute(
                "UPDATE job_models SET state='running' WHERE job_id=? AND model_index=? AND state='queued'",
                (str(job_id), index),
            ).rowcount
            if changed:
                self._sql.execute("UPDATE jobs SET state='running' WHERE id=?", (str(job_id),))
            return bool(changed)

    def _save(self, job: _Job) -> None:
        """Commit counters and model transitions alongside immutable outcome rows."""
        previous_cursor = self._sql.execute(
            "SELECT last_cursor FROM jobs WHERE id=?", (str(job.job_id),)
        ).fetchone()[0]
        self._sql.execute(
            "UPDATE jobs SET state=?,result_bytes=?,terminal_at=?,last_cursor=? WHERE id=?",
            (job.status, job.result_bytes, job.terminal_at, job.last_cursor, str(job.job_id)),
        )
        outcomes = {outcome.model_index: outcome for outcome in job.outcomes}
        for index, state in enumerate(job.states):
            outcome = outcomes.get(index)
            if outcome is None:
                self._sql.execute(
                    "UPDATE job_models SET state=? WHERE job_id=? AND model_index=? AND cursor IS NULL",
                    (state, str(job.job_id), index),
                )
            elif outcome.cursor > previous_cursor:
                payload = self.payloads.serialize("outcome", outcome)
                size = (
                    len(outcome.result.model_dump_json().encode("utf-8"))
                    if outcome.result is not None
                    else 0
                )
                self._sql.execute(
                    "UPDATE job_models SET state=?,cursor=?,byte_count=?,payload_version=?,payload_json=? "
                    "WHERE job_id=? AND model_index=? AND cursor IS NULL",
                    (
                        state,
                        outcome.cursor,
                        size,
                        payload.version,
                        payload.text,
                        str(job.job_id),
                        index,
                    ),
                )

    def create(self, model_count: int) -> UUID:
        """Reserve a new job without a client submission identifier."""
        return self.reserve(model_count, None, "")[0]

    def reserve(
        self, model_count: int, submission_id: UUID | None, fingerprint: str
    ) -> tuple[UUID, bool]:
        """Resolve retries before capacity checks and atomically reserve all models."""
        with self._atomic():
            self._prune()
            if submission_id is not None:
                previous = self._sql.execute(
                    "SELECT fingerprint,job_id FROM submissions WHERE id=?", (str(submission_id),)
                ).fetchone()
                if previous is not None:
                    if previous[0] != fingerprint:
                        raise SubmissionConflict("submission ID already used for different inputs")
                    return UUID(previous[1]), False
            count, active = self._sql.execute(
                "SELECT count(*),coalesce(sum(terminal_at IS NULL),0) FROM jobs"
            ).fetchone()
            if (
                count >= self.settings.max_retained_jobs
                or active >= self.settings.max_active_jobs + self.settings.max_queued_jobs
                or self._retained_bytes() >= self.settings.max_retained_bytes
            ):
                raise CapacityExceeded("job capacity is full")
            if model_count <= 0:
                raise ValueError("A job requires at least one model")
            job_id = uuid4()
            payload = self.payloads.serialize("job", JobMetadata())
            self._sql.execute(
                "INSERT INTO jobs VALUES (?, 'queued', ?, 0, ?, NULL, 0, ?, ?)",
                (str(job_id), model_count, time.time(), payload.version, payload.text),
            )
            self._sql.executemany(
                "INSERT INTO job_models VALUES (?,?,'queued',NULL,0,NULL,NULL)",
                [(str(job_id), index) for index in range(model_count)],
            )
            if submission_id is not None:
                self._sql.execute(
                    "INSERT INTO submissions VALUES (?,?,?)",
                    (str(submission_id), fingerprint, str(job_id)),
                )
            return job_id, True

    def close(self) -> None:
        """Close connections and release file ownership after workers have joined."""
        with self._lock:
            self.database.close()
