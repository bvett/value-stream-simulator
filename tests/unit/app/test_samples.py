"""Complete aggregate imports, sample generation, and mutable example availability."""

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from examples.build_sample_databases import build, execute, identity, snapshot
from value_stream.app.examples import available_examples
from value_stream.app.sample_import import import_samples, main, read_rows, validate
from value_stream.app.schemas import EditorRequest, TaskSetSpec
from value_stream.app.settings import AppSettings
from value_stream.app.sqlite_storage import SqliteWorkspaceStore
from value_stream.app.storage import RunRecord
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.schemas import MetadataData, ResultData, SummaryData


def minimal_result(item: tuple[RunRecord, int]) -> ResultData:
    """Use small valid outcomes for routine generator/import contract tests."""
    record, index = item
    return ResultData(
        model_index=index,
        model=record.status.outcomes[index].scenario.model,
        summary_result=SummaryData(completion_time=3, total_delivered_value=1, loss=0.1),
        metadata=MetadataData(event_metadata=[], resource_metadata=[]),
    )


class TestSamples(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "samples" / "application.sqlite3"
        with patch("examples.build_sample_databases.execute", side_effect=minimal_result):
            self.manifest = build(self.source.parent, task_count=2)
        self.target = DatabaseConfig("application", self.root / "target.sqlite3")

    def test_builder_has_fixed_ids_real_worker_protocol_and_closed_hashes(self) -> None:
        with self.assertRaises(FileExistsError):
            build(self.source.parent)
        for entry in self.manifest["databases"].values():
            path = self.source.parent / entry["filename"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
            self.assertFalse(Path(str(path) + "-wal").exists())
        store = SqliteWorkspaceStore(DatabaseConfig("application", self.source))
        try:
            workspace = store.get(identity("readme-workspace"))
            self.assertEqual(len(workspace.runs), 2)
            self.assertEqual(workspace.baseline_id, identity("readme-baseline"))
            self.assertEqual(workspace.latest_id, identity("readme-efficiency-11"))
            record = store.run(workspace.id, workspace.runs[0].id)
            self.assertEqual(execute((record, 0)).model, record.status.outcomes[0].scenario.model)
            with patch("examples.build_sample_databases.subprocess.run") as run:
                run.return_value.stdout = b'{"error":{"code":"FAILED"}}'
                with self.assertRaises(RuntimeError):
                    execute((record, 0))
        finally:
            store.close()
        with patch("examples.build_sample_databases.sqlite3.connect") as connect:
            connect.return_value.execute.return_value.fetchone.return_value = ("corrupt",)
            with self.assertRaises(RuntimeError):
                snapshot(self.root / "bad.sqlite3")
        sidecar = Path(str(self.source) + "-wal")
        sidecar.write_bytes(b"not-checkpointed")
        with patch("examples.build_sample_databases.sqlite3.connect") as connect:
            connect.return_value.execute.return_value.fetchone.return_value = ("ok",)
            with self.assertRaises(RuntimeError):
                snapshot(self.source)
        sidecar.unlink()

    def test_import_is_idempotent_preserves_ids_and_reports_whole_workspace_conflicts(self) -> None:
        before = self.source.read_bytes()
        report = import_samples(self.target, self.source)
        self.assertEqual(report.imported, [str(identity("readme-workspace"))])
        self.assertEqual(import_samples(self.target, self.source).unchanged, report.imported)
        self.assertEqual(self.source.read_bytes(), before)
        store = SqliteWorkspaceStore(self.target)
        workspace = store.get(identity("readme-workspace"))
        store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=workspace.revision,
                task_spec=TaskSetSpec(count=3),
                definitions=workspace.definitions,
            ),
        )
        store.close()
        self.assertEqual(import_samples(self.target, self.source).conflicting, report.imported)
        store = SqliteWorkspaceStore(self.target)
        self.assertEqual(store.get(workspace.id).task_spec.count, 3)
        store.delete_workspace(workspace.id)
        store.close()
        self.assertEqual(import_samples(self.target, self.source).imported, report.imported)

    def test_conflicting_shared_result_and_foreign_owned_ids_skip_complete_aggregate(self) -> None:
        import_samples(self.target, self.source)
        store = SqliteWorkspaceStore(self.target)
        with store.database.transaction() as connection:
            # Preserve an unrelated result row while deleting the sample aggregate directly.
            connection.execute("DELETE FROM runs")
            connection.execute("DELETE FROM task_sets")
            connection.execute("DELETE FROM workspaces")
            connection.execute("UPDATE result_blobs SET engine_version='different'")
        store.close()
        report = import_samples(self.target, self.source)
        self.assertTrue(report.conflicting)
        with sqlite3.connect(self.target.path) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM workspaces").fetchone()[0], 0)

    def test_invalid_source_never_creates_target_and_operational_errors_do_not_replace(
        self,
    ) -> None:
        for settings in (
            AppSettings(max_input_bytes=1, max_result_bytes=1),
            AppSettings(max_tasks=1),
            AppSettings(max_models=1),
            AppSettings(max_retained_runs=1),
        ):
            with self.assertRaises(ValueError):
                import_samples(self.target, self.source, settings=settings)
            self.assertFalse(self.target.path.exists())
        with self.assertRaises(ValueError):
            import_samples(DatabaseConfig("application", self.source), self.source)
        with self.assertRaises(ValueError):
            import_samples(DatabaseConfig("simulation", self.target.path), self.source)
        bad = self.root / "bad.sqlite3"
        bad.write_bytes(b"not sqlite")
        with self.assertRaises(Exception):
            import_samples(self.target, bad)
        self.assertFalse(self.target.path.exists())
        with sqlite3.connect(self.source) as connection:
            connection.execute("UPDATE runs SET reservation=1")
        with self.assertRaises(ValueError):
            import_samples(self.target, self.source)
        self.assertFalse(self.target.path.exists())

    def test_validation_rejects_missing_pointers_outcomes_and_payload_identity(self) -> None:
        with sqlite3.connect(self.source) as connection:
            original = read_rows(connection)
        import copy

        mutations = [
            ("workspaces", "revision", 99),
            ("runs", "state", "running"),
            ("run_outcomes", "scenario_id", "wrong"),
            ("run_outcomes", "result_key", "wrong"),
            ("result_blobs", "byte_count", -1),
            ("task_sets", "id", "wrong"),
            ("runs", "last_cursor", 99),
        ]
        for table, key, value in mutations:
            data = copy.deepcopy(original)
            data.rows[table][0][key] = value
            with self.subTest(table=table, key=key), self.assertRaises(ValueError):
                validate(data, AppSettings())
        data = copy.deepcopy(original)
        data.rows["run_outcomes"].pop()
        with self.assertRaises(ValueError):
            validate(data, AppSettings())
        data = copy.deepcopy(original)
        row = data.rows["workspaces"][0]
        value = json.loads(row["payload_json"])
        value["baseline_id"] = "00000000-0000-0000-0000-000000000001"
        row["payload_json"] = json.dumps(value)
        with self.assertRaises(ValueError):
            validate(data, AppSettings())

    def test_source_result_model_and_relationship_checks(self) -> None:
        with sqlite3.connect(self.source) as connection:
            data = read_rows(connection)
        row = data.rows["result_blobs"][0]
        value = json.loads(row["payload_json"])
        value["model"]["deployment_cadence"] = 999
        row["payload_json"] = json.dumps(value)
        with self.assertRaisesRegex(ValueError, "model differs"):
            validate(data, AppSettings())
        data.rows["result_blobs"].clear()
        with self.assertRaisesRegex(ValueError, "missing"):
            validate(data, AppSettings())

    def test_fault_after_insert_rolls_back_every_aggregate_and_capacity_failure(self) -> None:
        store = SqliteWorkspaceStore(self.target)
        original = store.database.transaction

        @contextmanager
        def failed() -> Iterator[sqlite3.Connection]:
            with original() as connection:
                yield connection
                raise RuntimeError("after actual writes")

        with (
            patch("value_stream.app.sample_import.SqliteWorkspaceStore", return_value=store),
            patch.object(store.database, "transaction", side_effect=failed),
        ):
            with self.assertRaisesRegex(RuntimeError, "actual writes"):
                import_samples(self.target, self.source)
        with sqlite3.connect(self.target.path) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM workspaces").fetchone()[0], 0)
        store = SqliteWorkspaceStore(self.target)
        store.create()
        store.close()
        with self.assertRaises(ValueError):
            import_samples(self.target, self.source, settings=AppSettings(max_workspaces=1))

    def test_catalog_filters_deleted_records_and_cli_exit_codes(self) -> None:
        import_samples(self.target, self.source)
        store = SqliteWorkspaceStore(self.target)
        with patch("value_stream.app.examples.resources.files", return_value=self.root):
            self.assertEqual(len(available_examples(store).examples), 9)
            store.comparison(
                identity("readme-workspace"), identity("readme-efficiency-11"), "delete"
            )
            self.assertEqual(len(available_examples(store).examples), 8)
            store.delete_workspace(identity("readme-workspace"))
            self.assertFalse(available_examples(store).examples)
        store.close()
        with patch("value_stream.app.examples.resources.files", return_value=self.root / "missing"):
            store = SqliteWorkspaceStore(self.target)
            self.assertFalse(available_examples(store).examples)
            store.close()
        args = ["import", "--database", str(self.target.path), "--source", str(self.source)]
        with patch("sys.argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        store = SqliteWorkspaceStore(self.target)
        workspace = store.get(identity("readme-workspace"))
        store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=workspace.revision,
                task_spec=TaskSetSpec(count=3),
                definitions=workspace.definitions,
            ),
        )
        store.close()
        with patch("sys.argv", args), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)
        with (
            patch(
                "sys.argv",
                [
                    "import",
                    "--database",
                    str(self.target.path),
                    "--source",
                    str(self.root / "missing"),
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(), 1)

    def test_optional_payload_defaults_and_unsupported_versions(self) -> None:
        with sqlite3.connect(self.source) as connection:
            for identity_value, text in connection.execute(
                "SELECT id,payload_json FROM runs"
            ).fetchall():
                payload = json.loads(text)
                payload.pop("upstream_kind", None)
                payload.pop("upstream_identity", None)
                connection.execute(
                    "UPDATE runs SET payload_json=? WHERE id=?",
                    (json.dumps(payload), identity_value),
                )
        self.assertTrue(import_samples(self.target, self.source).imported)
        self.assertTrue(import_samples(self.target, self.source).unchanged)
        with sqlite3.connect(self.source) as connection:
            connection.execute("UPDATE runs SET payload_version=999")
        other = DatabaseConfig("application", self.root / "unsupported.sqlite3")
        with self.assertRaises(Exception):
            import_samples(other, self.source)
        self.assertFalse(other.path.exists())

    def test_default_bundle_checksum_and_empty_initialized_source(self) -> None:
        with patch("value_stream.app.sample_import.resources.files", return_value=self.root):
            self.assertTrue(import_samples(self.target).imported)
            manifest_path = self.source.parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["databases"]["application"]["sha256"] = "wrong"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "checksum"):
                import_samples(self.target)
        from value_stream.service.persistence.database import SqliteDatabase

        empty = self.root / "empty.sqlite3"
        manager = SqliteDatabase(DatabaseConfig("application", empty)).open()
        manager.close()
        report = import_samples(
            DatabaseConfig("application", self.root / "empty-target.sqlite3"), empty
        )
        self.assertFalse(report.imported)
        unknown = self.root / "unknown.sqlite3"
        with sqlite3.connect(unknown) as connection:
            connection.execute("VACUUM")
        with self.assertRaisesRegex(ValueError, "initialized"):
            import_samples(self.target, unknown)
