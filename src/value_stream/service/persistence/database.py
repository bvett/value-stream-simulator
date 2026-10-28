"""Owned SQLite connections with verified initialization and backed-up migrations."""

import errno
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from threading import RLock
from types import TracebackType
from typing import Iterator

from filelock import BaseFileLock, FileLock, Timeout

from .config import DatabaseConfig
from .errors import DatabaseError, DatabaseErrorCode
from .migrations import APPLICATION_IDS, METADATA_VERSION, DatabaseSchema, initial_schema
from .payloads import PayloadRegistry


def _io_error(error: OSError | sqlite3.Error) -> DatabaseError:
    """Translate filesystem/SQLite errors without echoing stored data.

    Args:
        error: An operating-system or SQLite exception.

    Returns:
        A safe permission or invalid-database diagnostic.
    """
    permission = isinstance(error, PermissionError) or getattr(error, "errno", None) in (
        errno.EACCES,
        errno.EPERM,
        errno.EROFS,
    )
    sqlite_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    permission = permission or sqlite_code in (sqlite3.SQLITE_PERM, sqlite3.SQLITE_READONLY)
    code = DatabaseErrorCode.PERMISSION if permission else DatabaseErrorCode.INVALID
    message = (
        "Database access was denied; check file and directory permissions."
        if permission
        else "The database could not be opened or validated."
    )
    return DatabaseError(code, message)


def _create_directory(path: Path) -> None:
    """Create only missing directories with restrictive permissions."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)


def _flush_directory(path: Path) -> None:
    """Persist a newly published filename where directory fsync is supported."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(descriptor)


@contextmanager
def _read_only(connection: sqlite3.Connection) -> Iterator[None]:
    """Prevent accidental writes during validation and public read operations."""
    previous = connection.execute("PRAGMA query_only").fetchone()[0]
    connection.execute("PRAGMA query_only = ON")
    try:
        yield
    finally:
        connection.execute(f"PRAGMA query_only = {previous}")


class SqliteDatabase:
    """Own one local database until close, validating before any schema writes."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        schema: DatabaseSchema | None = None,
        payloads: PayloadRegistry | None = None,
    ) -> None:
        """Configure lazy opening without creating files or acquiring locks.

        Args:
            config: Resolved owner, path, and bundled-initialization policy.
            schema: Complete trusted migration chain for this component.
            payloads: Model/table registry supplied by the owning adapter.

        Raises:
            ValueError: If the schema belongs to another database kind.
        """
        self.config = config
        self.schema = schema or initial_schema(config.kind)
        if self.schema.kind != config.kind:
            raise ValueError("The schema and database kind must match.")
        self.payloads = payloads or PayloadRegistry()
        self.last_backup: Path | None = None
        self._mutex = RLock()
        self._connection: sqlite3.Connection | None = None
        self._ownership: BaseFileLock | None = None

    def _connect(self, path: Path, *, mode: str, immutable: bool = False) -> sqlite3.Connection:
        """Open a connection with safe local settings and an explicit file mode."""
        uri = f"{path.as_uri()}?mode={mode}"
        if immutable:
            uri += "&immutable=1"
        connection = sqlite3.connect(
            uri,
            uri=True,
            isolation_level=None,
            check_same_thread=False,
            timeout=5,
        )
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA trusted_schema = OFF")
        except BaseException:
            connection.close()
            raise
        return connection

    def _validate(self, connection: sqlite3.Connection) -> int:
        """Check integrity, identity, schema, and registered payloads without writes."""
        with _read_only(connection):
            return self._validate_contents(connection)

    def _validate_contents(self, connection: sqlite3.Connection) -> int:
        """Inspect metadata and rows while the connection enforces read-only SQL."""
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise DatabaseError(DatabaseErrorCode.INVALID, "Database integrity validation failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DatabaseError(DatabaseErrorCode.INVALID, "Database relationships are invalid.")
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        objects = connection.execute(
            "SELECT name, type FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        if version == 0 and application_id == 0 and not objects:
            return 0
        if application_id != APPLICATION_IDS[self.config.kind]:
            raise DatabaseError(
                DatabaseErrorCode.KIND_MISMATCH, "The file belongs to a different database kind."
            )
        if not 1 <= version <= self.schema.version:
            raise DatabaseError(
                DatabaseErrorCode.VERSION_UNSUPPORTED, "The database schema version is unsupported."
            )
        if ("store_meta", "table") not in objects:
            raise DatabaseError(
                DatabaseErrorCode.INVALID, "Database ownership metadata is missing."
            )
        metadata = connection.execute(
            "SELECT singleton, kind, metadata_version FROM store_meta"
        ).fetchall()
        if metadata != [(1, self.config.kind.value, METADATA_VERSION)]:
            raise DatabaseError(
                DatabaseErrorCode.INVALID, "Database ownership metadata is invalid."
            )
        if self.schema.validate is not None:
            try:
                self.schema.validate(connection, version)
            except DatabaseError:
                raise
            except Exception as exc:
                raise DatabaseError(
                    DatabaseErrorCode.INVALID, "Database schema validation failed."
                ) from exc
        self.payloads.validate_database(connection, version)
        return version

    def _inspect(self, path: Path) -> int:
        """Validate an existing file through a read-only connection."""
        if not path.is_file() or path.stat().st_size == 0:
            raise DatabaseError(DatabaseErrorCode.INVALID, "The existing database file is invalid.")
        with path.open("rb") as reader:
            if reader.read(16) != b"SQLite format 3\x00":
                raise DatabaseError(
                    DatabaseErrorCode.INVALID, "The existing file is not a SQLite database."
                )
        # A clean WAL-mode main file may have no sidecars. Some SQLite builds
        # cannot inspect that file with mode=ro alone. Under our ownership lock,
        # immutable reads are safe ONLY when no journal can contain newer data.
        immutable = not any(
            Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
        )
        connection = self._connect(path, mode="ro", immutable=immutable)
        try:
            return self._validate(connection)
        finally:
            connection.close()

    def _copy_bundle(self, destination: Path) -> bool:
        """Copy a closed packaged database, requiring its manifest and matching hash."""
        directory = resources.files("value_stream.service.persistence").joinpath("samples")
        source = directory.joinpath(self.config.filename)
        try:
            reader = source.open("rb")
        except FileNotFoundError:
            return False
        with reader:
            manifest = json.loads(directory.joinpath("manifest.json").read_text(encoding="utf-8"))
            version = manifest["format_version"]
            if isinstance(version, bool) or not isinstance(version, int) or version != 1:
                raise DatabaseError(
                    DatabaseErrorCode.VERSION_UNSUPPORTED,
                    "The sample manifest version is unsupported.",
                )
            entry = manifest["databases"][self.config.kind.value]
            if entry["filename"] != self.config.filename:
                raise ValueError("Unexpected bundled filename")
            if any(
                directory.joinpath(self.config.filename + suffix).is_file()
                for suffix in ("-wal", "-shm", "-journal")
            ):
                raise ValueError("A bundled snapshot must not require sidecars")
            with destination.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
        with destination.open("rb") as reader:
            digest = hashlib.file_digest(reader, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError("Bundled database checksum does not match")
        return True

    def _initialize(self) -> None:
        """Stage and atomically publish a verified new database without overwriting one."""
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.config.path.name}.", suffix=".tmp", dir=self.config.path.parent
        )
        os.close(descriptor)
        stage = Path(name)
        try:
            bundled = self.config.use_bundle and self._copy_bundle(stage)
            if not bundled:
                connection = self._connect(stage, mode="rw")
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self.schema.apply(connection, 0)
                    self._validate(connection)
                    connection.execute("COMMIT")
                except BaseException as exc:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    if isinstance(exc, Exception):
                        raise DatabaseError(
                            DatabaseErrorCode.MIGRATION_FAILED,
                            "Database initialization failed; no database was published.",
                        ) from exc
                    raise
                finally:
                    connection.close()
            self._inspect(stage)
            with stage.open("rb+") as reader:
                os.fsync(reader.fileno())
            # A same-directory hard link publishes atomically and cannot replace an
            # existing target, even if a noncooperating writer ignores our lock.
            os.link(stage, self.config.path)
            stage.unlink()
            _flush_directory(self.config.path.parent)
        finally:
            stage.unlink(missing_ok=True)

    def open(self) -> "SqliteDatabase":
        """Acquire ownership and safely initialize, migrate, and open the database.

        Returns:
            This manager, ready for reads and explicit transactions.

        Raises:
            DatabaseError: If ownership, compatibility, backup, or migration fails.
        """
        with self._mutex:
            if self._connection is not None:
                return self
            try:
                _create_directory(self.config.path.parent)
                self._ownership = FileLock(
                    str(self.config.path) + ".lock", timeout=0, thread_local=False
                )
                self._ownership.acquire()
                if not self.config.path.exists():
                    self._initialize()
                version = self._inspect(self.config.path)
                # An OS-level probe distinguishes denied file access from SQLite's
                # generic CANTOPEN, which otherwise hides the permission failure.
                with self.config.path.open("rb+"):
                    pass
                self._connection = self._connect(self.config.path, mode="rw")
                if version < self.schema.version:
                    self._migrate(version)
                self._connection.execute("PRAGMA journal_mode = WAL")
                self._connection.execute("PRAGMA synchronous = FULL")
                return self
            except BaseException as exc:
                self.close()
                if isinstance(exc, Timeout):
                    raise DatabaseError(
                        DatabaseErrorCode.IN_USE, "Another owner is using this database."
                    ) from exc
                if isinstance(exc, (OSError, sqlite3.Error)):
                    raise _io_error(exc) from exc
                if isinstance(exc, (ValueError, KeyError, TypeError)):
                    raise DatabaseError(
                        DatabaseErrorCode.INVALID, "The database or bundled sample is invalid."
                    ) from exc
                raise

    def _require_connection(self) -> sqlite3.Connection:
        """Return the owned connection, requiring callers to open the manager first."""
        if self._connection is None:
            raise DatabaseError(DatabaseErrorCode.INVALID, "The database is not open.")
        return self._connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Hold the connection mutex for a short read operation.

        Yields:
            The owned connection; callers must not write or retain it.

        Raises:
            DatabaseError: If the database is closed or a SQLite read fails.
        """
        with self._mutex:
            try:
                connection = self._require_connection()
                with _read_only(connection):
                    yield connection
            except sqlite3.Error as exc:
                raise _io_error(exc) from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit related writes together, rolling back on every exceptional exit.

        Yields:
            A connection inside BEGIN IMMEDIATE. Do not call executescript,
            COMMIT, ROLLBACK, or await inside this context.

        Raises:
            DatabaseError: If the manager is closed, nested, or SQLite fails.
        """
        with self._mutex:
            connection = self._require_connection()
            if connection.in_transaction:
                raise DatabaseError(
                    DatabaseErrorCode.INVALID, "Nested transactions are unsupported."
                )
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except BaseException as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise _io_error(exc) from exc
                raise

    @staticmethod
    def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
        """Count snapshot tables with safely quoted SQLite-owned names."""
        names = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT GLOB 'sqlite_*'"
        ).fetchall()
        return {
            name: connection.execute(
                'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
            ).fetchone()[0]
            for (name,) in names
        }

    def backup(self) -> Path:
        """Create and verify an independent snapshot including committed WAL data.

        Returns:
            The retained, verified backup path beside the database.

        Raises:
            DatabaseError: If backup creation or verification fails. No migration
                may proceed after this failure.
        """
        with self._mutex:
            connection = self._require_connection()
            if connection.in_transaction:
                raise DatabaseError(
                    DatabaseErrorCode.BACKUP_FAILED, "Backups require no active transaction."
                )
            destination: sqlite3.Connection | None = None
            path: Path | None = None
            try:
                version = self._validate(connection)
                counts = self._table_counts(connection)
                descriptor, name = tempfile.mkstemp(
                    prefix=self.config.path.name + ".",
                    suffix=".backup",
                    dir=self.config.path.parent,
                )
                os.close(descriptor)
                path = Path(name)
                destination = self._connect(path, mode="rw")
                connection.backup(destination)
                destination.execute("PRAGMA journal_mode = DELETE")
                if (
                    self._validate(destination) != version
                    or self._table_counts(destination) != counts
                ):
                    raise ValueError("Snapshot verification failed")
                destination.close()
                destination = None
                if self._inspect(path) != version:
                    raise ValueError("Closed snapshot verification failed")
                with path.open("rb+") as reader:
                    os.fsync(reader.fileno())
                _flush_directory(path.parent)
                self.last_backup = path
                return path
            except BaseException as exc:
                if destination is not None:
                    destination.close()
                if path is not None:
                    path.unlink(missing_ok=True)
                if isinstance(exc, Exception):
                    raise DatabaseError(
                        DatabaseErrorCode.BACKUP_FAILED,
                        "Database backup could not be created and verified; "
                        "no migration was applied.",
                    ) from exc
                raise

    def _migrate(self, previous_version: int) -> None:
        """Back up first, then atomically apply and validate the complete chain."""
        backup = self.backup()
        try:
            with self.transaction() as connection:
                self.schema.apply(connection, previous_version)
                self._validate(connection)
        except Exception as exc:
            raise DatabaseError(
                DatabaseErrorCode.MIGRATION_FAILED,
                f"Migration failed and was rolled back. Verified backup: {backup}",
            ) from exc

    def close(self) -> None:
        """Close the connection before releasing ownership; repeated calls are safe.

        Raises:
            DatabaseError: If called inside an active transaction.
        """
        with self._mutex:
            if self._connection is not None and self._connection.in_transaction:
                raise DatabaseError(
                    DatabaseErrorCode.INVALID, "Cannot close inside an active transaction."
                )
            try:
                if self._connection is not None:
                    self._connection.close()
            finally:
                self._connection = None
                if self._ownership is not None:
                    self._ownership.release()
                    self._ownership = None

    def __enter__(self) -> "SqliteDatabase":
        """Open the manager for a context-managed lifetime."""
        return self.open()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Release the connection and ownership after the context exits."""
        self.close()
