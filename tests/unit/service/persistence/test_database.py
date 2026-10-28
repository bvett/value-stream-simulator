"""Database ownership, snapshots, migration rollback, and initialization tests."""

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any, IO, NoReturn, TypedDict
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from value_stream.service.persistence.config import DatabaseConfig, DatabaseKind
from value_stream.service.persistence.database import SqliteDatabase
from value_stream.service.persistence.errors import DatabaseError, DatabaseErrorCode
from value_stream.service.persistence.migrations import (
    APPLICATION_IDS,
    DatabaseSchema,
    Migration,
    initial_schema,
)
from value_stream.service.persistence.payloads import PayloadRegistry, PayloadTable


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    count: int = 1


class DatabaseEntry(TypedDict):
    filename: str
    sha256: str


class SampleManifest(TypedDict):
    format_version: int
    databases: dict[str, DatabaseEntry]


def records_migration(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE records (id TEXT PRIMARY KEY, payload_version INTEGER, payload_json TEXT)"
    )


class TestSqliteDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.config = DatabaseConfig("application", self.root / "application.sqlite3")
        self.base = initial_schema("application")
        self.schema = DatabaseSchema(
            "application", self.base.migrations + (Migration(2, records_migration),)
        )
        self.registry = PayloadRegistry()
        self.registry.register("workspace", Record)
        self.registry.bind(PayloadTable("records", "workspace", introduced_in=2))
        self.identity = uuid4()

    def database(
        self,
        config: DatabaseConfig | None = None,
        schema: DatabaseSchema | None = None,
        payloads: PayloadRegistry | None = None,
    ) -> SqliteDatabase:
        manager = SqliteDatabase(
            config or self.config,
            schema=schema or self.schema,
            payloads=payloads or self.registry,
        )
        self.addCleanup(manager.close)
        return manager

    def insert(self, database: SqliteDatabase, name: str = "Example") -> None:
        value = self.registry.serialize("workspace", Record(id=self.identity, name=name))
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?)",
                (str(self.identity), value.version, value.text),
            )

    def rows(self, path: Path | None = None) -> list[tuple[str, int, str]]:
        with closing(sqlite3.connect(path or self.config.path)) as connection:
            return connection.execute("SELECT * FROM records").fetchall()

    def edit_file(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        with closing(sqlite3.connect(self.config.path)) as connection:
            connection.execute(sql, parameters)
            connection.commit()

    def require_backup(self, database: SqliteDatabase) -> Path:
        backup = database.last_backup
        assert backup is not None, "Expected a verified backup"
        return backup

    def bundle(self) -> tuple[Path, SampleManifest]:
        samples = self.root / "samples"
        samples.mkdir()
        source = samples / "application.sqlite3"
        database = self.database(DatabaseConfig("application", source)).open()
        self.insert(database)
        database.close()
        with closing(sqlite3.connect(source)) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
        # This fixture owns a fully closed rollback-journal snapshot. SQLite on
        # this host can leave an unused SHM file behind when changing modes.
        Path(str(source) + "-shm").unlink(missing_ok=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest: SampleManifest = {
            "format_version": 1,
            "databases": {"application": {"filename": source.name, "sha256": digest}},
        }
        (samples / "manifest.json").write_text(json.dumps(manifest))
        return source, manifest

    def test_construction_is_lazy_and_open_close_are_idempotent(self) -> None:
        config = DatabaseConfig("application", self.root / "new" / "database.sqlite3")
        database = self.database(config)
        self.assertFalse(config.path.parent.exists())
        database.close()
        with database as opened:
            self.assertIs(opened, database)
            self.assertIs(database.open(), database)
            with database.read() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                for name, expected in (
                    ("foreign_keys", 1),
                    ("trusted_schema", 0),
                    ("synchronous", 2),
                    ("journal_mode", "wal"),
                    ("busy_timeout", 5000),
                ):
                    self.assertEqual(connection.execute(f"PRAGMA {name}").fetchone()[0], expected)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(config.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(config.path.parent.stat().st_mode), 0o700)
        with self.assertRaises(DatabaseError):
            with database.read():
                pass

    def test_explicit_path_starts_empty_and_survives_reopen(self) -> None:
        database = self.database()
        with patch.object(
            database, "_copy_bundle", side_effect=AssertionError("unexpected bundle")
        ):
            database.open()
        self.insert(database)
        database.close()
        expected = self.rows()
        with self.database() as reopened:
            with reopened.read() as connection:
                self.assertEqual(connection.execute("SELECT * FROM records").fetchall(), expected)
            self.assertIsNone(reopened.last_backup)

    def test_default_copies_verified_bundle_bytes_and_keeps_ids(self) -> None:
        source, manifest = self.bundle()
        target = DatabaseConfig.resolve("application", data_dir=self.root / "user-data", environ={})
        database = self.database(target)
        real_link = os.link
        staged_hashes: list[str] = []

        def publish(stage: Path, destination: Path) -> None:
            staged_hashes.append(hashlib.sha256(Path(stage).read_bytes()).hexdigest())
            real_link(stage, destination)

        with (
            patch(
                "value_stream.service.persistence.database.resources.files", return_value=self.root
            ),
            patch("value_stream.service.persistence.database.os.link", side_effect=publish),
        ):
            database.open()
        self.assertEqual(staged_hashes, [manifest["databases"]["application"]["sha256"]])
        self.assertEqual(self.rows(target.path), self.rows(source))
        self.assertEqual(self.rows(target.path)[0][0], str(self.identity))
        database.close()
        with patch(
            "value_stream.service.persistence.database.resources.files",
            side_effect=AssertionError("existing data must not be replaced"),
        ):
            self.database(target).open()

    def test_absent_bundle_creates_empty_default(self) -> None:
        target = DatabaseConfig.resolve("application", data_dir=self.root / "user-data", environ={})
        with patch(
            "value_stream.service.persistence.database.resources.files", return_value=self.root
        ):
            self.database(target).open()
        self.assertEqual(self.rows(target.path), [])

    def test_invalid_bundle_never_publishes_or_falls_back_to_empty(self) -> None:
        source, original_manifest = self.bundle()
        manifest_path = source.parent / "manifest.json"
        target = DatabaseConfig.resolve("application", data_dir=self.root / "user-data", environ={})
        cases = ["missing", "malformed", "future", "filename", "checksum", "sidecar", "wrong-kind"]
        for case in cases:
            with self.subTest(case=case):
                manifest = json.loads(json.dumps(original_manifest))
                sidecar = source.with_name(source.name + "-wal")
                if case == "future":
                    manifest["format_version"] = 99
                elif case == "filename":
                    manifest["databases"]["application"]["filename"] = "other.sqlite3"
                elif case == "checksum":
                    manifest["databases"]["application"]["sha256"] = "incorrect"
                elif case == "sidecar":
                    sidecar.touch()
                elif case == "wrong-kind":
                    with closing(sqlite3.connect(source)) as connection:
                        connection.execute(
                            f"PRAGMA application_id = {APPLICATION_IDS[DatabaseKind.SIMULATION]}"
                        )
                    manifest["databases"]["application"]["sha256"] = hashlib.sha256(
                        source.read_bytes()
                    ).hexdigest()
                manifest_path.write_text("invalid" if case == "malformed" else json.dumps(manifest))
                if case == "missing":
                    manifest_path.unlink()
                database = self.database(target)
                with (
                    patch(
                        "value_stream.service.persistence.database.resources.files",
                        return_value=self.root,
                    ),
                    self.assertRaises(DatabaseError),
                ):
                    database.open()
                self.assertFalse(target.path.exists())
                self.assertEqual(list(target.path.parent.glob("*.tmp")), [])
                sidecar.unlink(missing_ok=True)

    def test_publication_cannot_overwrite_an_existing_target(self) -> None:
        real_link = os.link

        def race(stage: Path, destination: Path) -> None:
            Path(destination).write_bytes(b"existing data")
            real_link(stage, destination)

        with (
            patch("value_stream.service.persistence.database.os.link", side_effect=race),
            self.assertRaises(DatabaseError),
        ):
            self.database().open()
        self.assertEqual(self.config.path.read_bytes(), b"existing data")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_zero_byte_non_sqlite_and_unversioned_nonempty_files_are_preserved(self) -> None:
        for data in (b"", b"not a SQLite database"):
            with self.subTest(data=data):
                self.config.path.write_bytes(data)
                with self.assertRaises(DatabaseError):
                    self.database().open()
                self.assertEqual(self.config.path.read_bytes(), data)
                self.config.path.unlink()
        for table in ("unrelated", "sqliteXunrelated"):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.config.path)) as connection:
                    connection.execute(f'CREATE TABLE "{table}" (value TEXT)')
                    connection.commit()
                original = self.config.path.read_bytes()
                with self.assertRaises(DatabaseError):
                    self.database().open()
                self.assertEqual(self.config.path.read_bytes(), original)
                self.config.path.unlink()

    def test_valid_empty_sqlite_database_is_backed_up_before_initialization(self) -> None:
        with closing(sqlite3.connect(self.config.path)) as connection:
            connection.execute("VACUUM")
        database = self.database().open()
        self.assertIsNotNone(database.last_backup)
        with closing(sqlite3.connect(self.require_backup(database))) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_schema").fetchall(), [])

    def test_kind_schema_and_metadata_errors_do_not_modify_existing_files(self) -> None:
        database = self.database().open()
        database.close()
        for statement, code in (
            ("PRAGMA user_version = 999", DatabaseErrorCode.VERSION_UNSUPPORTED),
            ("UPDATE store_meta SET metadata_version = 2", DatabaseErrorCode.INVALID),
            ("UPDATE store_meta SET kind = 'simulation'", DatabaseErrorCode.INVALID),
        ):
            with self.subTest(statement=statement):
                self.edit_file(statement)
                before = self.config.path.read_bytes()
                with self.assertRaises(DatabaseError) as error:
                    self.database().open()
                self.assertEqual(error.exception.code, code)
                self.assertEqual(self.config.path.read_bytes(), before)
                self.edit_file("PRAGMA user_version = 2")
                self.edit_file("UPDATE store_meta SET metadata_version = 1, kind = 'application'")
        simulation = SqliteDatabase(DatabaseConfig("simulation", self.config.path))
        with self.assertRaises(DatabaseError) as error:
            simulation.open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.KIND_MISMATCH)
        self.edit_file("DROP TABLE store_meta")
        with self.assertRaises(DatabaseError):
            self.database().open()

    def test_future_or_invalid_payloads_are_rejected_before_writes(self) -> None:
        database = self.database().open()
        self.insert(database)
        database.close()
        for statement, code in (
            ("UPDATE records SET payload_version = 999", DatabaseErrorCode.PAYLOAD_UNSUPPORTED),
            (
                "UPDATE records SET payload_version = 1, payload_json = 'invalid'",
                DatabaseErrorCode.INVALID,
            ),
            ("UPDATE records SET payload_json = '{}'", DatabaseErrorCode.INVALID),
        ):
            with self.subTest(statement=statement):
                self.edit_file(statement)
                before = self.config.path.read_bytes()
                with self.assertRaises(DatabaseError) as error:
                    self.database().open()
                self.assertEqual(error.exception.code, code)
                self.assertEqual(self.config.path.read_bytes(), before)

    def test_foreign_key_failures_are_detected(self) -> None:
        database = self.database().open()
        database.close()
        with closing(sqlite3.connect(self.config.path)) as connection:
            connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
            connection.execute("INSERT INTO child VALUES (999)")
            connection.commit()
        with self.assertRaises(DatabaseError):
            self.database().open()

    def test_successful_migration_retains_verified_original_backup(self) -> None:
        self.database(schema=self.base).open().close()
        database = self.database().open()
        self.assertIsNotNone(database.last_backup)
        with closing(sqlite3.connect(self.require_backup(database))) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(
                backup.execute("SELECT name FROM sqlite_schema WHERE name='records'").fetchone()
            )
        self.insert(database)

    def test_failure_rolls_back_the_complete_migration_chain_and_version(self) -> None:
        database = self.database().open()
        self.insert(database)
        database.close()
        original_rows = self.rows()

        def third(connection: sqlite3.Connection) -> None:
            connection.execute("ALTER TABLE records ADD COLUMN temporary TEXT")
            connection.execute("UPDATE records SET payload_json = '{}' ")

        def fourth(connection: sqlite3.Connection) -> NoReturn:
            connection.execute("CREATE TABLE partial_change (id INTEGER)")
            raise RuntimeError("simulated migration failure")

        schema = DatabaseSchema(
            "application", self.schema.migrations + (Migration(3, third), Migration(4, fourth))
        )
        failed = self.database(schema=schema)
        with self.assertRaises(DatabaseError) as error:
            failed.open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.MIGRATION_FAILED)
        self.assertIn(str(failed.last_backup), str(error.exception))
        self.assertEqual(self.rows(), original_rows)
        with closing(sqlite3.connect(self.config.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertNotIn(
                "temporary", [row[1] for row in connection.execute("PRAGMA table_info(records)")]
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_schema WHERE name='partial_change'"
                ).fetchone()
            )
        self.assertEqual(self.rows(self.require_backup(failed)), original_rows)
        self.database().open()

    def test_post_migration_payload_validation_failure_also_rolls_back(self) -> None:
        database = self.database().open()
        self.insert(database)
        database.close()
        original = self.rows()

        def invalid_payload(connection: sqlite3.Connection) -> None:
            connection.execute("UPDATE records SET payload_json = '{}' ")

        schema = DatabaseSchema(
            "application", self.schema.migrations + (Migration(3, invalid_payload),)
        )
        with self.assertRaises(DatabaseError) as error:
            self.database(schema=schema).open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.MIGRATION_FAILED)
        self.assertEqual(self.rows(), original)

    def test_backup_contains_committed_wal_data_and_is_independent(self) -> None:
        database = self.database().open()
        with database.read() as connection:
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        self.insert(database)
        self.assertGreater(Path(str(self.config.path) + "-wal").stat().st_size, 0)
        snapshot = database.backup()
        self.assertEqual(self.rows(snapshot), self.rows())
        self.assertFalse(Path(str(snapshot) + "-wal").exists())
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)

    def test_abrupt_exit_preserves_committed_wal_data_during_preflight(self) -> None:
        self.database().open().close()
        payload = self.registry.serialize("workspace", Record(id=self.identity, name="Crash"))
        code = (
            "import os, sqlite3, sys\n"
            "connection = sqlite3.connect(sys.argv[1])\n"
            "connection.execute('PRAGMA journal_mode=WAL')\n"
            "connection.execute('PRAGMA wal_autocheckpoint=0')\n"
            "connection.execute('INSERT INTO records VALUES (?, 1, ?)', (sys.argv[2], sys.argv[3]))\n"
            "connection.commit()\n"
            "os._exit(0)\n"
        )
        subprocess.run(
            [sys.executable, "-c", code, str(self.config.path), str(self.identity), payload.text],
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.assertGreater(Path(str(self.config.path) + "-wal").stat().st_size, 0)
        database = self.database()
        with patch.object(database, "_connect", wraps=database._connect) as connect:
            database.open()
        readonly = [call for call in connect.call_args_list if call.kwargs.get("mode") == "ro"]
        self.assertTrue(readonly)
        self.assertFalse(readonly[0].kwargs["immutable"])
        with database.read() as connection:
            row = connection.execute("SELECT * FROM records").fetchone()
        self.assertEqual(row, (str(self.identity), 1, payload.text))

    def test_payload_upgrade_migration_preserves_ids_and_historical_backup(self) -> None:
        database = self.database().open()
        self.insert(database)
        database.close()
        original = self.rows()
        registry = PayloadRegistry()

        def update_count(value: dict[str, Any]) -> dict[str, Any]:
            return {**value, "count": 2}

        registry.register("workspace", Record, version=2, upgrades={1: update_count})
        registry.bind(PayloadTable("records", "workspace", introduced_in=2))

        def upgrade(connection: sqlite3.Connection) -> None:
            for identity, version, text in connection.execute("SELECT * FROM records").fetchall():
                current = registry.deserialize("workspace", version, text)
                encoded = registry.serialize("workspace", current)
                connection.execute(
                    "UPDATE records SET payload_version = ?, payload_json = ? WHERE id = ?",
                    (encoded.version, encoded.text, identity),
                )

        schema = DatabaseSchema("application", self.schema.migrations + (Migration(3, upgrade),))
        upgraded = self.database(schema=schema, payloads=registry).open()
        self.assertEqual(self.rows(self.require_backup(upgraded)), original)
        identity, version, text = self.rows()[0]
        self.assertEqual(identity, str(self.identity))
        self.assertEqual(version, 2)
        loaded = registry.deserialize("workspace", version, text)
        assert isinstance(loaded, Record)
        self.assertEqual(loaded.count, 2)

    def test_backup_verification_failure_discards_only_its_partial_snapshot(self) -> None:
        database = self.database().open()
        self.insert(database)
        original = self.rows()
        counts = database._table_counts
        calls = 0

        def mismatched(connection: sqlite3.Connection) -> dict[str, int]:
            nonlocal calls
            calls += 1
            return counts(connection) if calls == 1 else {"records": 999}

        with (
            patch.object(database, "_table_counts", side_effect=mismatched),
            self.assertRaises(DatabaseError) as error,
        ):
            database.backup()
        self.assertEqual(error.exception.code, DatabaseErrorCode.BACKUP_FAILED)
        self.assertIsNone(database.last_backup)
        self.assertEqual(list(self.root.glob("*.backup")), [])
        self.assertEqual(self.rows(), original)

    def test_backup_permission_failure_prevents_any_migration(self) -> None:
        self.database(schema=self.base).open().close()
        apply = Mock(side_effect=records_migration)
        schema = DatabaseSchema("application", self.base.migrations + (Migration(2, apply),))
        database = self.database(schema=schema)
        with (
            patch(
                "value_stream.service.persistence.database.tempfile.mkstemp",
                side_effect=PermissionError("denied"),
            ),
            self.assertRaises(DatabaseError) as error,
        ):
            database.open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.BACKUP_FAILED)
        apply.assert_not_called()
        self.assertIsNone(database._connection)
        self.database(schema=self.base).open()

    def test_closed_snapshot_verification_failure_prevents_migration(self) -> None:
        database = self.database().open()
        with (
            patch.object(database, "_inspect", side_effect=ValueError("verification failed")),
            self.assertRaises(DatabaseError) as error,
        ):
            database.backup()
        self.assertEqual(error.exception.code, DatabaseErrorCode.BACKUP_FAILED)
        self.assertEqual(list(self.root.glob("*.backup")), [])

    def test_transactions_rollback_on_python_and_sqlite_failures(self) -> None:
        database = self.database().open()
        for error in (RuntimeError("stop"), KeyboardInterrupt()):
            with self.subTest(error=error), self.assertRaises(type(error)):
                with database.transaction() as connection:
                    connection.execute("INSERT INTO records VALUES ('id', 1, '{}')")
                    raise error
            self.assertEqual(self.rows(), [])
        with self.assertRaises(DatabaseError):
            with database.transaction() as connection:
                connection.execute("INSERT INTO missing_table VALUES ('secret-value')")
        with self.assertRaises(DatabaseError) as error:
            with database.read() as connection:
                connection.execute("SELECT * FROM missing_table")
        self.assertNotIn("secret-value", str(error.exception))
        self.insert(database)

    def test_nested_transactions_close_and_backup_inside_transaction_are_rejected(self) -> None:
        database = self.database().open()
        with database.transaction():
            with self.assertRaises(DatabaseError):
                with database.transaction():
                    pass
            with self.assertRaises(DatabaseError):
                database.close()
            with self.assertRaises(DatabaseError):
                database.backup()
        self.insert(database)

    def test_reads_and_schema_validators_cannot_accidentally_write(self) -> None:
        database = self.database().open()
        self.insert(database)
        original = self.rows()
        with self.assertRaises(DatabaseError):
            with database.read() as connection:
                connection.execute("DELETE FROM records")
        self.assertEqual(self.rows(), original)
        database.close()

        def invalid_validator(connection: sqlite3.Connection, version: int) -> None:
            connection.execute("DELETE FROM records")

        schema = DatabaseSchema("application", self.schema.migrations, validate=invalid_validator)
        with self.assertRaises(DatabaseError):
            self.database(schema=schema).open()
        self.assertEqual(self.rows(), original)
        # Read-only validation must restore the connection setting before writes.
        with self.database() as reopened:
            with reopened.transaction() as connection:
                connection.execute("DELETE FROM records")
        self.assertEqual(self.rows(), [])

    def test_threaded_transactions_are_serialized_and_close_can_release_other_thread(self) -> None:
        database = self.database().open()

        def insert(index: int) -> None:
            record = Record(id=uuid4(), name=str(index))
            encoded = self.registry.serialize("workspace", record)
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    (str(record.id), encoded.version, encoded.text),
                )

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(insert, range(20)))
            executor.submit(database.close).result()
        self.assertEqual(len(self.rows()), 20)
        self.database().open()

    def test_ownership_excludes_same_process_and_an_independent_process(self) -> None:
        database = self.database().open()
        with self.assertRaises(DatabaseError) as error:
            self.database().open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.IN_USE)
        code = (
            "import sys\n"
            "from value_stream.service.persistence.database import SqliteDatabase\n"
            "from value_stream.service.persistence.config import DatabaseConfig\n"
            "from value_stream.service.persistence.errors import DatabaseError\n"
            "try:\n"
            "    SqliteDatabase(DatabaseConfig('application', sys.argv[1])).open()\n"
            "except DatabaseError as error:\n"
            "    print(error.code)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.config.path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), DatabaseErrorCode.IN_USE)
        database.close()
        self.database().open()

    def test_permission_failure_is_actionable_and_retry_can_open(self) -> None:
        database = self.database()
        with (
            patch(
                "value_stream.service.persistence.database._create_directory",
                side_effect=PermissionError("denied"),
            ),
            self.assertRaises(DatabaseError) as error,
        ):
            database.open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.PERMISSION)
        database.open()

    def test_file_read_and_write_permission_failures_preserve_data(self) -> None:
        database = self.database().open()
        self.insert(database)
        database.close()
        original = self.config.path.read_bytes()
        real_open = Path.open
        for denied_mode in ("rb", "rb+"):

            def denied(
                path: Path,
                mode: str = "r",
                buffering: int = -1,
                encoding: str | None = None,
                errors: str | None = None,
                newline: str | None = None,
            ) -> IO[Any]:
                if path == self.config.path and mode == denied_mode:
                    raise PermissionError("denied")
                return real_open(path, mode, buffering, encoding, errors, newline)

            with self.subTest(mode=denied_mode):
                with (
                    patch.object(Path, "open", new=denied),
                    self.assertRaises(DatabaseError) as error,
                ):
                    self.database().open()
                self.assertEqual(error.exception.code, DatabaseErrorCode.PERMISSION)
                self.assertEqual(self.config.path.read_bytes(), original)
        self.database().open()

    def test_schema_configuration_and_validator_failures_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DatabaseSchema("application", ())
        with self.assertRaises(ValueError):
            DatabaseSchema("application", (Migration(2, records_migration),))
        with self.assertRaises(ValueError):
            SqliteDatabase(self.config, schema=initial_schema("simulation"))
        self.database().open().close()
        schema = DatabaseSchema(
            "application",
            self.schema.migrations,
            validate=Mock(side_effect=RuntimeError("secret-value")),
        )
        with self.assertRaises(DatabaseError) as error:
            self.database(schema=schema).open()
        self.assertNotIn("secret-value", str(error.exception))

    def test_initialization_failure_leaves_no_database_and_retry_works(self) -> None:
        def fail(connection: sqlite3.Connection) -> NoReturn:
            connection.execute("CREATE TABLE partial_change (id INTEGER)")
            raise RuntimeError("interrupted initialization")

        broken = DatabaseSchema("application", self.base.migrations + (Migration(2, fail),))
        with self.assertRaises(DatabaseError) as error:
            self.database(schema=broken).open()
        self.assertEqual(error.exception.code, DatabaseErrorCode.MIGRATION_FAILED)
        self.assertFalse(self.config.path.exists())
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        self.database().open()
