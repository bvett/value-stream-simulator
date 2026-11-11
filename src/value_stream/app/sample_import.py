"""Offline, atomic, non-replacing import of complete sample workspace aggregates."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any
from uuid import UUID

from filelock import FileLock

from value_stream.service.persistence.config import DatabaseConfig, DatabaseKind
from value_stream.service.persistence.database import SqliteDatabase
from .generation import canonical, fingerprint
from .schemas import TERMINAL, TaskSet, Workspace, RunStatus, OutcomeSummary
from value_stream.service.schemas import ResultData
from .settings import AppSettings
from .sqlite_storage import (
    RunPayload,
    SqliteWorkspaceStore,
    WorkspacePayload,
    workspace_payloads,
    workspace_schema,
)

TABLES = ("workspaces", "task_sets", "result_blobs", "runs", "run_outcomes")
COLUMNS = {
    "workspaces": "id revision input_bytes created_at updated_at payload_version payload_json",
    "task_sets": "id workspace_id spec_hash content_hash generator_version byte_count payload_version payload_json",
    "result_blobs": "result_key byte_count engine_version generator_version payload_version payload_json",
    "runs": "id workspace_id task_set_id request_id request_hash state created_at updated_at input_bytes result_bytes reservation service_cursor last_cursor job_id upstream_kind upstream_identity payload_version payload_json",
    "run_outcomes": "run_id scenario_index scenario_id cursor status result_key payload_version payload_json",
}
KINDS = dict(zip(TABLES, ("workspace", "task_set", "result", "run", "outcome")))
Row = dict[str, Any]


@dataclass
class ImportReport:
    """Workspace-level decisions; conflicts never replace an existing aggregate."""

    imported: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)


@dataclass
class SampleData:
    """Validated current-format rows grouped by complete workspace ownership."""

    rows: dict[str, list[Row]]

    def aggregate(self, workspace_id: str) -> dict[str, list[Row]]:
        """Select editor, tasks, runs, outcomes, and every referenced immutable result."""
        workspace = [r for r in self.rows["workspaces"] if r["id"] == workspace_id]
        runs = [r for r in self.rows["runs"] if r["workspace_id"] == workspace_id]
        run_ids = {r["id"] for r in runs}
        outcomes = [r for r in self.rows["run_outcomes"] if r["run_id"] in run_ids]
        keys = {r["result_key"] for r in outcomes if r["result_key"] is not None}
        return dict(
            workspaces=workspace,
            task_sets=[r for r in self.rows["task_sets"] if r["workspace_id"] == workspace_id],
            runs=runs,
            run_outcomes=outcomes,
            result_blobs=[r for r in self.rows["result_blobs"] if r["result_key"] in keys],
        )


def read_rows(connection: sqlite3.Connection) -> SampleData:
    """Normalize supported payload versions without rewriting the source database."""
    registry = workspace_payloads()
    result: dict[str, list[Row]] = {}
    for table in TABLES:
        cursor = connection.execute(
            f'SELECT {",".join(COLUMNS[table].split())} FROM {table} ORDER BY 1,2'
        )
        names = [column[0] for column in cursor.description]
        rows: list[Row] = []
        for values in cursor:
            row = dict(zip(names, values))
            model = registry.deserialize(KINDS[table], row["payload_version"], row["payload_json"])
            encoded = registry.serialize(KINDS[table], model)
            row.update(payload_version=encoded.version, payload_json=encoded.text)
            if table in ("task_sets", "result_blobs"):
                row["byte_count"] = len(encoded.text.encode())
            rows.append(row)
        result[table] = rows
    data = SampleData(result)
    sizes = {row["result_key"]: row["byte_count"] for row in result["result_blobs"]}
    for workspace in result["workspaces"]:
        aggregate = data.aggregate(workspace["id"])
        model = Workspace.model_validate_json(workspace["payload_json"])
        model.task_sets = [
            TaskSet.model_validate_json(row["payload_json"]) for row in aggregate["task_sets"]
        ]
        workspace["input_bytes"] = len(
            canonical(model.model_dump(mode="json", exclude={"runs"})).encode()
        )
        for run in aggregate["runs"]:
            payload = RunPayload.model_validate_json(run["payload_json"])
            outcomes = [row for row in aggregate["run_outcomes"] if row["run_id"] == run["id"]]
            status = RunStatus.model_validate(
                {
                    **payload.status.model_dump(),
                    "outcomes": [json.loads(row["payload_json"]) for row in outcomes],
                }
            )
            run["input_bytes"] = len(canonical(status.model_dump(mode="json")).encode())
            run["result_bytes"] = sum(sizes.get(row["result_key"], 0) for row in outcomes)
    return data


def validate(data: SampleData, settings: AppSettings) -> None:
    """Reject partial, active, oversized, or inconsistently referenced sample aggregates."""
    if len(data.rows["workspaces"]) > settings.max_workspaces:
        raise ValueError("Sample workspace limit exceeded")
    total = sum(len(r["payload_json"].encode()) for rows in data.rows.values() for r in rows)
    if total > settings.max_input_bytes + settings.max_result_bytes:
        raise ValueError("Sample payload size exceeds configured limits")
    blobs = {row["result_key"]: row for row in data.rows["result_blobs"]}
    for row in data.rows["workspaces"]:
        workspace = WorkspacePayload.model_validate_json(row["payload_json"])
        if str(workspace.id) != row["id"] or workspace.revision != row["revision"]:
            raise ValueError("Workspace identity or revision mismatch")
        aggregate = data.aggregate(row["id"])
        tasks = {
            r["id"]: TaskSet.model_validate_json(r["payload_json"]) for r in aggregate["task_sets"]
        }
        if workspace.current_task_set and str(workspace.current_task_set) not in tasks:
            raise ValueError("Current task set is missing")
        runs = {r["id"]: r for r in aggregate["runs"]}
        for pointer in (workspace.baseline_id, workspace.latest_id):
            if pointer and str(pointer) not in runs:
                raise ValueError("Comparison pointer is missing")
        if len(runs) > settings.max_retained_runs or len(tasks) > settings.max_task_sets:
            raise ValueError("Sample history exceeds configured limits")
        for task_id, task in tasks.items():
            if (
                str(task.id) != task_id
                or len(task.tasks) > settings.max_tasks
                or task.content_hash
                != next(r["content_hash"] for r in aggregate["task_sets"] if r["id"] == task_id)
            ):
                raise ValueError("Invalid frozen task set")
        for run in runs.values():
            payload = RunPayload.model_validate_json(run["payload_json"])
            status = payload.status
            if (
                run["task_set_id"] not in tasks
                or str(status.id) != run["id"]
                or str(status.task_set_id) != run["task_set_id"]
                or status.state != run["state"]
                or status.state not in TERMINAL
                or run["reservation"] != 0
                or status.job_id is not None
                or run["job_id"] is not None
                or str(payload.request.request_id) != run["request_id"]
                or payload.request_hash != run["request_hash"]
                or payload.upstream_identity is not None
                or fingerprint(payload.request.model_dump(mode="json")) != run["request_hash"]
            ):
                raise ValueError("Sample contains active work or inconsistent run metadata")
            outcomes = [r for r in aggregate["run_outcomes"] if r["run_id"] == run["id"]]
            if (
                [r["scenario_index"] for r in outcomes] != list(range(len(payload.cache_keys)))
                or len(outcomes) > settings.max_models
                or sorted(r["cursor"] for r in outcomes) != list(range(1, len(outcomes) + 1))
            ):
                raise ValueError("Incomplete sample outcomes")
            if run["last_cursor"] != len(outcomes) or status.last_cursor != len(outcomes):
                raise ValueError("Run completion cursor mismatch")
            for outcome in outcomes:
                value = json.loads(outcome["payload_json"])
                if (
                    value["scenario"]["id"] != outcome["scenario_id"]
                    or value["cursor"] != outcome["cursor"]
                    or value["status"] != outcome["status"]
                    or not outcome["cursor"]
                ):
                    raise ValueError("Outcome identity mismatch")
                if (
                    outcome["status"] == "succeeded"
                    and outcome["result_key"] != payload.cache_keys[outcome["scenario_index"]]
                ):
                    raise ValueError("Outcome result reference mismatch")
                if outcome["status"] == "succeeded":
                    blob = blobs.get(outcome["result_key"])
                    if blob is None:
                        raise ValueError("Referenced result is missing")
                    model = ResultData.model_validate_json(blob["payload_json"])
                    summary = OutcomeSummary.model_validate_json(outcome["payload_json"])
                    if model.model_index != 0 or model.model != summary.scenario.model:
                        raise ValueError("Result model differs from its scenario")
    for row in data.rows["result_blobs"]:
        if row["byte_count"] < 0 or row["byte_count"] > settings.max_model_bytes:
            raise ValueError("Sample result exceeds configured limits")


def import_samples(
    target: DatabaseConfig, source: Path | None = None, *, settings: AppSettings | None = None
) -> ImportReport:
    """Validate a read-only source before opening the destination, then import atomically.

    Args:
        target: Application database location; absent files start empty.
        source: Compatible closed sample database, defaulting to the bundled release.
        settings: Capacity and source-size bounds.

    Returns:
        Imported, identical, and conflicting workspace identifiers.
    """
    settings = settings or AppSettings()
    if target.kind != DatabaseKind.APPLICATION:
        raise ValueError("Sample import requires an application database")
    with ExitStack() as stack:
        bundled = source is None
        if source is None:
            source = stack.enter_context(
                resources.as_file(
                    resources.files("value_stream.service.persistence").joinpath(
                        "samples/application.sqlite3"
                    )
                )
            )
        source = source.resolve()
        if bundled:
            manifest = json.loads(
                resources.files("value_stream.service.persistence")
                .joinpath("samples/manifest.json")
                .read_text()
            )
            if type(manifest.get("format_version")) is not int or manifest["format_version"] != 1:
                raise ValueError("Unsupported sample manifest version")
            with source.open("rb") as reader:
                digest = hashlib.file_digest(reader, "sha256").hexdigest()
            if digest != manifest["databases"]["application"]["sha256"]:
                raise ValueError("Bundled sample checksum mismatch")
        if source == target.path or (
            source.exists() and target.path.exists() and source.samefile(target.path)
        ):
            raise ValueError("Source and destination must be different files")
        if source.stat().st_size > settings.max_input_bytes + settings.max_result_bytes:
            raise ValueError("Sample database exceeds configured limits")
        if not bundled:
            stack.enter_context(FileLock(str(source) + ".lock", timeout=0))
        sidecars = any(
            Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
        )
        connection = sqlite3.connect(
            source.as_uri() + "?mode=ro" + ("" if sidecars else "&immutable=1"), uri=True
        )
        stack.callback(connection.close)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        manager = SqliteDatabase(
            DatabaseConfig("application", source),
            schema=workspace_schema(),
            payloads=workspace_payloads(),
        )
        version = manager._validate(connection)
        if version < 1:
            raise ValueError("Source is not an initialized application database")
        data = read_rows(connection) if version >= 2 else SampleData({t: [] for t in TABLES})
        validate(data, settings)
        # Bundle initialization would bypass conflict/admission reporting; import always starts empty.
        store = SqliteWorkspaceStore(DatabaseConfig("application", target.path), settings)
        stack.callback(store.close)
        report = ImportReport()
        with store.database.transaction() as destination:
            existing = read_rows(destination)
            pending: list[dict[str, list[Row]]] = []
            for workspace in data.rows["workspaces"]:
                identity = workspace["id"]
                incoming = data.aggregate(identity)
                current = existing.aggregate(identity)
                if current["workspaces"]:
                    (
                        report.unchanged
                        if canonical(incoming) == canonical(current)
                        else report.conflicting
                    ).append(identity)
                    continue
                conflict = False
                for table in TABLES:
                    if table == "run_outcomes":
                        continue
                    key = "result_key" if table == "result_blobs" else "id"
                    current_rows = {r[key]: r for r in existing.rows[table]}
                    for row in incoming[table]:
                        if row[key] in current_rows and (
                            table != "result_blobs" or row != current_rows[row[key]]
                        ):
                            conflict = True
                if conflict:
                    report.conflicting.append(identity)
                else:
                    pending.append(incoming)
                    report.imported.append(identity)
            for aggregate in pending:
                for table in TABLES:
                    for row in aggregate[table]:
                        if (
                            table == "result_blobs"
                            and destination.execute(
                                "SELECT 1 FROM result_blobs WHERE result_key=?",
                                (row["result_key"],),
                            ).fetchone()
                        ):
                            continue
                        columns = ",".join(row)
                        destination.execute(
                            f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in row)})',
                            tuple(row.values()),
                        )
            if pending and (
                destination.execute("SELECT count(*) FROM workspaces").fetchone()[0]
                > settings.max_workspaces
            ):
                raise ValueError("Destination workspace limit exceeded")
            inputs = (
                destination.execute(
                    "SELECT coalesce(sum(input_bytes),0) FROM workspaces"
                ).fetchone()[0]
                + destination.execute("SELECT coalesce(sum(input_bytes),0) FROM runs").fetchone()[0]
            )
            size = destination.execute(
                "SELECT coalesce(sum(byte_count),0) FROM result_blobs"
            ).fetchone()[0]
            if pending and (inputs > settings.max_input_bytes or size > settings.max_result_bytes):
                raise ValueError("Destination byte budget exceeded")
        return report


def main() -> int:
    """Print explicit import decisions and return 0, 2 for conflicts, or 1 for failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    try:
        report = import_samples(
            DatabaseConfig.resolve("application", database=args.database, data_dir=args.data_dir),
            args.source,
        )
        print(json.dumps(report.__dict__, sort_keys=True))
        return 2 if report.conflicting else 0
    except Exception as exc:
        print(f"Sample import failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
