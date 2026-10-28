"""Common snapshot, retention, and transaction contracts for both workspace adapters."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from value_stream.app.errors import AppError
from value_stream.app.schemas import (
    EditorRequest,
    RunRequest,
    ScenarioDefinition,
    TaskSetSpec,
)
from value_stream.app.settings import AppSettings
from value_stream.app.sqlite_storage import SqliteWorkspaceStore
from value_stream.app.storage import (
    CompletedOutcome,
    InMemoryWorkspaceStore,
    RunChanges,
    RunRecord,
    WorkspaceOperations,
)
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.database import SqliteDatabase
from value_stream.service.schemas import (
    ErrorEnvelope,
    MetadataData,
    ResultData,
    Status,
    SummaryData,
)


class TestWorkspaceStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = DatabaseConfig("application", Path(self.directory.name) / "app.sqlite3")
        settings = AppSettings(min_interactive_seconds=0.001)
        self.stores: list[WorkspaceOperations] = [
            InMemoryWorkspaceStore(settings),
            SqliteWorkspaceStore(self.config, settings),
        ]
        for store in self.stores:
            self.addCleanup(store.close)

    def reopen(self, store: WorkspaceOperations) -> WorkspaceOperations:
        if isinstance(store, SqliteWorkspaceStore):
            store.close()
            reopened = SqliteWorkspaceStore(self.config, store.settings)
            self.addCleanup(reopened.close)
            return reopened
        return store

    def arrange(
        self,
        store: WorkspaceOperations,
        count: int = 2,
        definitions: list[ScenarioDefinition] | None = None,
    ) -> RunRecord:
        workspace = store.create()
        preview = store.save_editor(
            workspace.id,
            EditorRequest(
                expected_revision=0,
                task_spec=TaskSetSpec(count=count),
                definitions=definitions or [ScenarioDefinition(sweeps={"team_size": [1, 2]})],
            ),
        )
        tasks = store.get(workspace.id).task_sets[0]
        return store.register(
            workspace.id,
            RunRequest(request_id=uuid4(), preview_digest=preview.digest),
            preview.scenarios,
            tasks,
        )[0]

    @staticmethod
    def result(record: RunRecord, index: int = 0) -> ResultData:
        return ResultData(
            model_index=index,
            model=record.status.outcomes[index].scenario.model,
            summary_result=SummaryData(completion_time=3, total_delivered_value=1, loss=-0.5),
            metadata=MetadataData(event_metadata=[], resource_metadata=[]),
        )

    def finish(self, store: WorkspaceOperations, record: RunRecord) -> RunRecord:
        return store.complete_outcomes(
            record.workspace_id,
            record.status.id,
            [
                CompletedOutcome(i, Status.SUCCEEDED, self.result(record, i))
                for i, outcome in enumerate(record.status.outcomes)
                if not outcome.cursor
            ],
            terminal_state="completed",
        )

    def next_run(self, store: WorkspaceOperations, record: RunRecord) -> RunRecord:
        return store.register(
            record.workspace_id,
            RunRequest(
                request_id=uuid4(), preview_digest=store.preview(record.workspace_id).digest
            ),
            [o.scenario for o in record.status.outcomes],
            record.task_set,
        )[0]

    def test_snapshots_and_results_are_detached_and_survive_reopen(self) -> None:
        for store in self.stores:
            with self.subTest(adapter=type(store).__name__):
                record = self.arrange(store)
                snapshot = store.get(record.workspace_id)
                snapshot.definitions[0].name = "changed outside storage"
                record.status.name = "changed outside storage"
                self.assertNotEqual(
                    store.get(record.workspace_id).definitions[0].name, snapshot.definitions[0].name
                )
                self.assertNotEqual(
                    store.run(record.workspace_id, record.status.id).status.name, record.status.name
                )
                final = self.finish(store, record)
                expected = store.result(final, final.status.outcomes[1].scenario.id)
                returned = store.result(final, final.status.outcomes[1].scenario.id)
                returned.summary_result.completion_time = 999
                reopened = self.reopen(store)
                restored = reopened.run(final.workspace_id, final.status.id)
                self.assertEqual(restored.status, final.status)
                self.assertEqual(
                    reopened.result(restored, final.status.outcomes[1].scenario.id), expected
                )
                self.assertEqual(expected.model_index, 1)
                self.assertEqual(reopened.get(record.workspace_id).baseline_id, final.status.id)
                self.assertGreater(restored.created_at, 1_000_000_000)

    def test_atomic_page_replay_and_out_of_order_models(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            page = [CompletedOutcome(1, Status.SUCCEEDED, self.result(record, 1), service_cursor=1)]
            first = store.complete_outcomes(
                record.workspace_id, record.status.id, page, service_cursor=1
            )
            self.assertEqual(first.status.outcomes[1].cursor, 1)
            store = self.reopen(store)
            replay = store.complete_outcomes(
                record.workspace_id, record.status.id, page, service_cursor=1
            )
            self.assertEqual(replay.result_bytes, first.result_bytes)
            self.assertEqual(replay.reservation, first.reservation)
            self.assertEqual(replay.status.last_cursor, 1)
            final = store.complete_outcomes(
                record.workspace_id,
                record.status.id,
                [CompletedOutcome(0, Status.SUCCEEDED, self.result(record), service_cursor=2)],
                service_cursor=2,
                terminal_state="completed",
            )
            self.assertEqual([o.cursor for o in final.status.outcomes], [2, 1])
            self.assertEqual(final.service_cursor, 2)
            self.assertEqual(final.reservation, 0)
            self.assertEqual(
                store.complete_outcomes(
                    record.workspace_id, record.status.id, page, service_cursor=1
                ).status,
                final.status,
            )

    def test_fault_after_blob_insert_rolls_back_results_and_cursors(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            original = store._write_record

            def fail_after_write(value: RunRecord) -> None:
                original(value)
                raise RuntimeError("crash before commit")

            with (
                patch.object(store, "_write_record", side_effect=fail_after_write),
                self.assertRaises(RuntimeError),
            ):
                store.complete_outcomes(
                    record.workspace_id,
                    record.status.id,
                    [CompletedOutcome(0, Status.SUCCEEDED, self.result(record), service_cursor=1)],
                    service_cursor=1,
                )
            restored = store.run(record.workspace_id, record.status.id)
            self.assertEqual(restored.results, {})
            self.assertEqual(restored.service_cursor, 0)
            self.assertEqual(restored.reservation, record.reservation)
            with self.assertRaises(AppError):
                store.cached_result(record.cache_keys[0])
            self.finish(store, record)

    def test_invalid_pages_never_advance_checkpoint(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            valid = CompletedOutcome(0, Status.SUCCEEDED, self.result(record), service_cursor=1)
            cases: list[tuple[list[CompletedOutcome], int | None]] = [
                ([valid], None),
                ([], -1),
                ([], 3),
                ([replace(valid, service_cursor=None)], 1),
                ([replace(valid, service_cursor=0)], 1),
                ([replace(valid, service_cursor=2)], 1),
                ([replace(valid, index=99)], 1),
                ([], 1),
                ([replace(valid, service_cursor=2)], 2),
                ([valid, valid], 1),
            ]
            for outcomes, cursor in cases:
                with self.subTest(adapter=type(store).__name__, cursor=cursor, outcomes=outcomes):
                    with self.assertRaises(AppError):
                        store.complete_outcomes(
                            record.workspace_id, record.status.id, outcomes, service_cursor=cursor
                        )
                    self.assertEqual(
                        store.run(record.workspace_id, record.status.id).service_cursor, 0
                    )
            store.complete_outcomes(
                record.workspace_id, record.status.id, [valid], service_cursor=1
            )
            with self.assertRaises(AppError):
                store.complete_outcomes(
                    record.workspace_id,
                    record.status.id,
                    [replace(valid, index=1)],
                    service_cursor=1,
                )

    def test_invalid_outcome_shapes_and_terminal_states_are_atomic(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            error = ErrorEnvelope(code="FAILED", message="failure")
            cases = [
                CompletedOutcome(-1, Status.CANCELLED),
                CompletedOutcome(5, Status.CANCELLED),
                CompletedOutcome(0, Status.RUNNING),
                CompletedOutcome(0, Status.SUCCEEDED),
                CompletedOutcome(0, Status.FAILED),
                CompletedOutcome(0, Status.CANCELLED, error=error),
                CompletedOutcome(0, Status.FAILED, error=error, cached=True),
            ]
            wrong = self.result(record).model_copy(deep=True)
            wrong.model.deployment_cadence += 1
            cases.append(CompletedOutcome(0, Status.SUCCEEDED, wrong))
            for completion in cases:
                with self.assertRaises(AppError):
                    store.complete_outcomes(record.workspace_id, record.status.id, [completion])
            for state in ("running", "completed"):
                with self.assertRaises(AppError):
                    store.complete_outcomes(
                        record.workspace_id, record.status.id, [], terminal_state=state
                    )
            first = store.complete_outcomes(
                record.workspace_id, record.status.id, [CompletedOutcome(0, Status.CANCELLED)]
            )
            with self.assertRaises(AppError):
                store.complete_outcomes(
                    record.workspace_id,
                    record.status.id,
                    [CompletedOutcome(0, Status.FAILED, error=error)],
                )
            self.assertEqual(store.run(record.workspace_id, record.status.id).status, first.status)

    def test_failure_retains_success_and_late_updates_cannot_change_terminal(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            error = ErrorEnvelope(code="MODEL_FAILED", message="a failure")
            final = store.complete_outcomes(
                record.workspace_id,
                record.status.id,
                [
                    CompletedOutcome(0, Status.SUCCEEDED, self.result(record)),
                    CompletedOutcome(1, Status.FAILED, error=error),
                ],
                terminal_state="completed_with_errors",
                run_error=error,
            )
            self.assertEqual(len(final.results), 1)
            late = store.patch_run(
                record.workspace_id, record.status.id, RunChanges(state="running", error=None)
            )
            self.assertEqual(late.status, final.status)
            self.assertEqual(
                store.complete_outcomes(record.workspace_id, record.status.id, []).status,
                final.status,
            )

    def test_patch_preserves_cancellation_and_distinguishes_clear_error(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            owner, run_id = record.workspace_id, record.status.id
            error = ErrorEnvelope(code="OFFLINE", message="retry")
            store.patch_run(
                owner,
                run_id,
                RunChanges(
                    state="reconnecting",
                    error=error,
                    upstream_kind="external",
                    upstream_identity="http://service",
                    job_id=uuid4(),
                ),
            )
            store.patch_run(owner, run_id, RunChanges(cancel_requested=True, superseded=True))
            updated = store.patch_run(owner, run_id, RunChanges(state="running", retry_paused=True))
            self.assertEqual(updated.status.state, "cancelling")
            self.assertEqual(updated.status.error, error)
            self.assertTrue(updated.status.superseded)
            updated = store.patch_run(owner, run_id, RunChanges(error=None))
            self.assertIsNone(updated.status.error)
            self.assertEqual(updated.upstream_identity, "http://service")
            self.assertEqual(store.active_records()[0][0], owner)
            store.active_records()[0][1].status.name = "detached"
            self.assertNotEqual(store.run(owner, run_id).status.name, "detached")
            with self.assertRaises(AppError):
                store.patch_run(owner, run_id, RunChanges(state="completed"))

    def test_idempotency_precedes_limits_and_stale_caller_state(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            workspace = store.get(record.workspace_id)
            workspace.runs = []
            store.settings = replace(
                store.settings, max_active_runs=1, max_result_bytes=1, max_input_bytes=1
            )
            prior, created = store.register(
                record.workspace_id, record.request, [], record.task_set
            )
            self.assertFalse(created)
            self.assertEqual(prior.status.id, record.status.id)
            matched = store.previous(workspace, record.request)
            assert matched is not None
            self.assertEqual(matched.status.id, record.status.id)
            changed = record.request.model_copy(update={"name": "different"})
            with self.assertRaisesRegex(AppError, "different inputs"):
                store.previous(workspace, changed)

    def test_saved_history_is_not_pruned_and_shared_blobs_survive_delete(self) -> None:
        for store in self.stores:
            first = self.finish(store, self.arrange(store))
            second = self.finish(store, self.next_run(store, first))
            store.settings = replace(store.settings, max_retained_runs=2)
            with self.assertRaisesRegex(AppError, "Delete a saved comparison"):
                self.next_run(store, first)
            self.assertEqual(len(store.get(first.workspace_id).runs), 2)
            store.comparison(first.workspace_id, first.status.id, "delete")
            self.assertIsNotNone(store.result(second, second.status.outcomes[0].scenario.id))
            self.assertEqual(store.get(first.workspace_id).baseline_id, None)
            store.comparison(second.workspace_id, second.status.id, "delete")
            with self.assertRaises(AppError):
                store.cached_result(first.cache_keys[0])

    def test_pending_cache_references_protect_results_and_indexes_are_normalized(self) -> None:
        for store in self.stores:
            first = self.finish(store, self.arrange(store))
            second = self.next_run(store, first)
            self.assertEqual(second.service_indices, [])
            store.comparison(first.workspace_id, first.status.id, "delete")
            final = store.complete_outcomes(
                second.workspace_id,
                second.status.id,
                [
                    CompletedOutcome(i, Status.SUCCEEDED, store.cached_result(key), cached=True)
                    for i, key in enumerate(second.cache_keys)
                ],
                terminal_state="completed",
            )
            self.assertTrue(all(o.cached for o in final.status.outcomes))
            self.assertEqual(
                store.result(final, final.status.outcomes[1].scenario.id).model_index, 1
            )
            store.delete_workspace(final.workspace_id)
            with self.assertRaises(AppError):
                store.cached_result(first.cache_keys[0])

    def test_lowered_limits_keep_reads_and_deletion_available(self) -> None:
        for store in self.stores:
            record = self.finish(store, self.arrange(store))
            store.settings = replace(
                store.settings,
                max_input_bytes=1,
                max_result_bytes=1,
                max_model_bytes=1,
                max_workspaces=1,
                max_retained_runs=1,
            )
            self.assertEqual(store.run(record.workspace_id, record.status.id).status, record.status)
            self.assertIsNotNone(store.result(record, record.status.outcomes[0].scenario.id))
            with self.assertRaises(AppError):
                store.create()
            store.comparison(record.workspace_id, record.status.id, "unpin")
            store.delete_workspace(record.workspace_id)

    def test_budget_failures_rollback_pages_without_discarding_saved_data(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            store.settings = replace(store.settings, max_model_bytes=1)
            with self.assertRaises(AppError):
                self.finish(store, record)
            self.assertEqual(store.run(record.workspace_id, record.status.id).status.last_cursor, 0)
            store.settings = replace(store.settings, max_model_bytes=10_000, max_run_bytes=1)
            with self.assertRaises(AppError):
                self.finish(store, record)
            store.settings = replace(store.settings, max_model_bytes=10_000, max_run_bytes=10_000)
            self.finish(store, record)
            store.settings = replace(store.settings, max_result_bytes=1)
            new = store.create()
            preview = store.save_editor(
                new.id,
                EditorRequest(
                    expected_revision=0,
                    task_spec=TaskSetSpec(count=3),
                    definitions=[ScenarioDefinition()],
                ),
            )
            with self.assertRaisesRegex(AppError, "Result storage"):
                store.register(
                    new.id,
                    RunRequest(request_id=uuid4(), preview_digest=preview.digest),
                    preview.scenarios,
                    store.get(new.id).task_sets[0],
                )
            self.assertEqual(
                store.run(record.workspace_id, record.status.id).status.state, "completed"
            )

    def test_reserved_budget_cannot_be_exceeded(self) -> None:
        for store in self.stores:
            store.settings = replace(store.settings, max_model_bytes=1, max_run_bytes=1)
            record = self.arrange(store)
            store.settings = replace(store.settings, max_model_bytes=10000, max_run_bytes=10000)
            with self.assertRaisesRegex(AppError, "reserved result budget"):
                self.finish(store, record)

    def test_comparison_pins_baseline_and_task_set_deletion(self) -> None:
        for store in self.stores:
            first = self.finish(store, self.arrange(store))
            second = self.finish(store, self.next_run(store, first))
            store.settings = replace(store.settings, max_pins=1)
            store.comparison(first.workspace_id, first.status.id, "pin")
            with self.assertRaises(AppError):
                store.comparison(second.workspace_id, second.status.id, "pin")
            store.comparison(first.workspace_id, first.status.id, "unpin")
            store.comparison(second.workspace_id, second.status.id, "pin")
            workspace = store.get(first.workspace_id)
            store.save_editor(
                workspace.id,
                EditorRequest(
                    expected_revision=workspace.revision,
                    task_spec=TaskSetSpec(count=3),
                    definitions=workspace.definitions,
                ),
            )
            changed = store.get(workspace.id)
            extra_tasks = changed.current_task_set
            restored = store.comparison(workspace.id, first.status.id, "baseline")
            self.assertEqual(restored.current_task_set, first.task_set.id)
            assert extra_tasks is not None
            store.delete_task_set(workspace.id, extra_tasks, restored.revision)
            self.assertEqual(len(store.get(workspace.id).task_sets), 1)
            with self.assertRaises(AppError):
                store.comparison(workspace.id, first.status.id, "unknown")

    def test_invalid_editor_inputs_and_admission_do_not_change_state(self) -> None:
        for store in self.stores:
            workspace = store.create()
            with self.assertRaises(AppError):
                store.preview(workspace.id)
            duplicate = ScenarioDefinition()
            requests = [
                EditorRequest(
                    expected_revision=1, task_spec=TaskSetSpec(), definitions=[duplicate]
                ),
                EditorRequest(
                    expected_revision=0, task_spec=TaskSetSpec(count=1001), definitions=[duplicate]
                ),
                EditorRequest(
                    expected_revision=0, task_spec=TaskSetSpec(), definitions=[duplicate, duplicate]
                ),
            ]
            for request in requests:
                with self.assertRaises(AppError):
                    store.save_editor(workspace.id, request)
                self.assertEqual(store.get(workspace.id).revision, 0)
            store.settings = replace(store.settings, max_input_bytes=1)
            with self.assertRaises(AppError):
                store.save_editor(
                    workspace.id,
                    EditorRequest(
                        expected_revision=0, task_spec=TaskSetSpec(count=1), definitions=[duplicate]
                    ),
                )
            self.assertEqual(store.get(workspace.id).revision, 0)
            with self.assertRaises(AppError):
                store.create()

    def test_missing_foreign_and_in_use_objects_are_rejected(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            other = store.create()
            for owner, run_id in (
                (uuid4(), record.status.id),
                (record.workspace_id, uuid4()),
                (other.id, record.status.id),
            ):
                with self.assertRaises(AppError):
                    store.run(owner, run_id)
            with self.assertRaises(AppError):
                store.delete_workspace(record.workspace_id)
            with self.assertRaises(AppError):
                store.delete_task_set(record.workspace_id, record.task_set.id, 1)
            with self.assertRaises(AppError):
                store.delete_task_set(record.workspace_id, uuid4(), 1)
            with self.assertRaises(AppError):
                store.delete_task_set(record.workspace_id, uuid4(), 0)
            with self.assertRaises(AppError):
                store.result(record, uuid4())
            with self.assertRaises(AppError):
                store.comparison(record.workspace_id, record.status.id, "delete")
            with self.assertRaises(AppError):
                self.next_run(store, record)

    def test_active_global_limits_distinct_scenarios_and_task_integrity(self) -> None:
        for store in self.stores:
            record = self.arrange(store)
            store.settings = replace(store.settings, max_active_runs=1)
            workspace = store.create()
            preview = store.save_editor(
                workspace.id,
                EditorRequest(
                    expected_revision=0,
                    task_spec=TaskSetSpec(count=1),
                    definitions=[ScenarioDefinition()],
                ),
            )
            tasks = store.get(workspace.id).task_sets[0]
            request = RunRequest(request_id=uuid4(), preview_digest=preview.digest)
            with self.assertRaises(AppError):
                store.register(workspace.id, request, preview.scenarios, tasks)
            self.finish(store, record)
            for scenarios in ([], [preview.scenarios[0], preview.scenarios[0]]):
                with self.assertRaises(AppError):
                    store.register(workspace.id, request, scenarios, tasks)
            with self.assertRaises(AppError):
                store.register(workspace.id, request, preview.scenarios, record.task_set)
            altered = tasks.model_copy(deep=True)
            altered.tasks[0].initial_value = 999
            with self.assertRaises(AppError):
                store.register(workspace.id, request, preview.scenarios, altered)

    def test_task_limit_and_spec_reuse(self) -> None:
        for store in self.stores:
            record = self.finish(store, self.arrange(store))
            workspace = store.get(record.workspace_id)
            original = workspace.task_sets[0].id
            same = store.save_editor(
                workspace.id,
                EditorRequest(
                    expected_revision=workspace.revision,
                    task_spec=workspace.task_spec,
                    definitions=workspace.definitions,
                ),
            )
            self.assertEqual(same.task_set_id, original)
            store.settings = replace(store.settings, max_task_sets=1)
            with self.assertRaises(AppError):
                store.save_editor(
                    workspace.id,
                    EditorRequest(
                        expected_revision=same.workspace_revision,
                        task_spec=TaskSetSpec(count=3),
                        definitions=workspace.definitions,
                    ),
                )

    def test_sqlite_migrates_metadata_and_reads_no_blobs_for_snapshots(self) -> None:
        sql_store = self.stores[1]
        sql_store.close()
        assert isinstance(sql_store, SqliteWorkspaceStore)
        with SqliteDatabase(
            DatabaseConfig("application", Path(self.directory.name) / "old.sqlite3")
        ):
            pass
        migrated = SqliteWorkspaceStore(
            DatabaseConfig("application", Path(self.directory.name) / "old.sqlite3")
        )
        self.addCleanup(migrated.close)
        self.assertIsNotNone(migrated.database.last_backup)
        record = self.finish(migrated, self.arrange(migrated))
        statements: list[str] = []
        with migrated.database.read() as connection:
            connection.set_trace_callback(statements.append)
        migrated.get(record.workspace_id)
        migrated.run(record.workspace_id, record.status.id)
        self.assertFalse(any("FROM result_blobs" in s for s in statements))
        with migrated.database.read() as connection:
            connection.set_trace_callback(None)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(ValueError):
            SqliteWorkspaceStore(
                DatabaseConfig("simulation", Path(self.directory.name) / "wrong.sqlite3")
            )

    def test_admission_rechecks_preview_after_an_intervening_edit(self) -> None:
        for store in self.stores:
            first = self.finish(store, self.arrange(store))
            preview = store.preview(first.workspace_id)
            workspace = store.get(first.workspace_id)
            store.save_editor(
                workspace.id,
                EditorRequest(
                    expected_revision=workspace.revision,
                    task_spec=workspace.task_spec,
                    definitions=[ScenarioDefinition(name="Changed editor")],
                ),
            )
            with self.assertRaisesRegex(AppError, "Preview is stale"):
                store.register(
                    workspace.id,
                    RunRequest(request_id=uuid4(), preview_digest=preview.digest),
                    preview.scenarios,
                    first.task_set,
                )
            self.assertEqual(len(store.get(workspace.id).runs), 1)

    def test_cached_metrics_describe_the_immutable_retained_payload(self) -> None:
        for store in self.stores:
            first = self.finish(store, self.arrange(store))
            second = self.next_run(store, first)
            incoming: list[CompletedOutcome] = []
            for index, key in enumerate(second.cache_keys):
                copied = store.cached_result(key)
                copied.summary_result.total_delivered_value = 999
                incoming.append(CompletedOutcome(index, Status.SUCCEEDED, copied, cached=True))
            final = store.complete_outcomes(
                second.workspace_id, second.status.id, incoming, terminal_state="completed"
            )
            for outcome in final.status.outcomes:
                self.assertEqual(outcome.delivered_value, 1)
                self.assertEqual(
                    store.result(final, outcome.scenario.id).summary_result.total_delivered_value, 1
                )

    def test_adapters_use_the_same_exact_logical_input_budget(self) -> None:
        from value_stream.app.generation import canonical

        for store in self.stores:
            record = self.arrange(store)
            workspace = store.get(record.workspace_id)
            expected = len(canonical(workspace.model_dump(mode="json", exclude={"runs"})).encode())
            expected += sum(
                len(canonical(r.model_dump(mode="json")).encode()) for r in workspace.runs
            )
            store.settings = replace(store.settings, max_input_bytes=expected + 1)
            definitions = [definition.model_copy(deep=True) for definition in workspace.definitions]
            definitions[0].name += "!"
            store.save_editor(
                workspace.id,
                EditorRequest(
                    expected_revision=workspace.revision,
                    task_spec=workspace.task_spec,
                    definitions=definitions,
                ),
            )
            self.assertEqual(store.get(workspace.id).definitions[0].name, definitions[0].name)
