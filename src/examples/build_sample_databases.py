"""Explicitly regenerate the README's completed SQLite examples through real workers."""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from value_stream.app.generation import concrete_model
from value_stream.app.schemas import (
    ENGINE_VERSION,
    GENERATOR_VERSION,
    EditorRequest,
    ModelSettings,
    RunRequest,
    ScenarioDefinition,
    TaskSetSpec,
)
from value_stream.app.sqlite_storage import SqliteWorkspaceStore
from value_stream.app.settings import AppSettings
from value_stream.app.storage import CompletedOutcome, RunRecord
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.job_store import SqliteJobStore
from value_stream.service.schemas import JobRequest, ResultData, Status

NAMESPACE = uuid5(
    NAMESPACE_URL, "https://github.com/bvett/value-stream-simulator/samples/readme-v1"
)
STAMP = 1_793_145_600.0


def identity(name: str) -> UUID:
    """Derive a release-stable named identity."""
    return uuid5(NAMESPACE, name)


class SampleStore(SqliteWorkspaceStore):
    """Allow fixed internal IDs only in this offline generator."""

    run_name: str = "readme-baseline"

    def _new_id(self, kind: str) -> UUID:
        """Allocate sample identities without changing public HTTP inputs."""
        return identity(
            {"workspace": "readme-workspace", "task_set": "readme-tasks", "run": self.run_name}[
                kind
            ]
        )


def execute(item: tuple[RunRecord, int]) -> ResultData:
    """Execute one complete frozen model through the production subprocess protocol."""
    record, index = item
    scenario = record.status.outcomes[index].scenario
    request = JobRequest(
        tasks=record.task_set.tasks, models=[scenario.model], model_seeds=[scenario.execution_seed]
    )
    response = subprocess.run(
        [sys.executable, "-m", "value_stream.service.worker"],
        input=json.dumps(
            {
                "model_index": index,
                "request": request.model_dump(mode="json"),
                "max_outcome_bytes": 8 * 1024 * 1024,
            }
        ).encode(),
        capture_output=True,
        timeout=180,
        check=True,
    )
    output = json.loads(response.stdout)
    if "result" not in output:
        raise RuntimeError(f'Sample model {index} failed: {output.get("error")}')
    return ResultData.model_validate(output["result"])


def snapshot(path: Path) -> None:
    """Checkpoint a closed snapshot, remove free pages, and verify no journal dependency."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("VACUUM")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("Invalid generated database")
    finally:
        connection.close()
    wal = Path(str(path) + "-wal")
    if (wal.exists() and wal.stat().st_size) or Path(str(path) + "-journal").exists():
        raise RuntimeError("Generated snapshot still requires a sidecar")
    # This SQLite build can retain orphan SHM files even after DELETE-mode close.
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    Path(str(path) + ".lock").unlink(missing_ok=True)


def build(output_dir: Path, *, task_count: int | None = None) -> dict[str, Any]:
    """Build real completed examples, refusing to replace any existing output.

    Args:
        output_dir: New release staging directory.
        task_count: Internal small-fixture override for routine validation.

    Returns:
        The published manifest, including full explicit regeneration inputs.
    """
    names = ("application.sqlite3", "simulation.sqlite3", "manifest.json")
    if any((output_dir / name).exists() for name in names):
        raise FileExistsError("Refusing to overwrite sample output")
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(Path(__file__).with_name("sample_spec.json").read_text())
    tasks = TaskSetSpec.model_validate(frozen["task_spec"])
    if task_count is not None:
        tasks.count = task_count
    definition = ScenarioDefinition(
        id=identity("readme-definition"),
        name="README delivery model",
        settings=ModelSettings.model_validate(frozen["settings"]),
        sweeps=frozen["sweeps"],
        team_seed=frozen["team_seed"],
        execution_seed=frozen["execution_seed"],
    )
    store = SampleStore(
        DatabaseConfig("application", output_dir / names[0]),
        AppSettings(min_interactive_seconds=0.000001),
    )
    try:
        workspace = store.create()
        preview = store.save_editor(
            workspace.id,
            EditorRequest(expected_revision=0, task_spec=tasks, definitions=[definition]),
        )
        task_set = store.get(workspace.id).task_sets[0]
        baseline, _ = store.register(
            workspace.id,
            RunRequest(
                request_id=identity("readme-baseline-request"),
                preview_digest=preview.digest,
                name="README baseline",
            ),
            preview.scenarios,
            task_set,
        )
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(execute, [(baseline, i) for i in range(9)]))
        store.complete_outcomes(
            workspace.id,
            baseline.status.id,
            [CompletedOutcome(i, Status.SUCCEEDED, r) for i, r in enumerate(results)],
            terminal_state="completed",
        )
        scenarios = [s.model_copy(deep=True) for s in preview.scenarios]
        for scenario in scenarios:
            scenario.settings.efficiency_max = 11
            scenario.model = concrete_model(scenario.settings, scenario.team_seed)
            scenario.revision += 1
            scenario.name += " → efficiency_max=11"
        store.run_name = "readme-efficiency-11"
        comparison, _ = store.register(
            workspace.id,
            RunRequest(
                request_id=identity("readme-efficiency-11-request"),
                preview_digest=preview.digest,
                name="README efficiency 11",
                intent="interactive",
                source_run_id=baseline.status.id,
                property="efficiency_max",
                value=11,
            ),
            scenarios,
            task_set,
        )
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(execute, [(comparison, i) for i in range(9)]))
        store.complete_outcomes(
            workspace.id,
            comparison.status.id,
            [CompletedOutcome(i, Status.SUCCEEDED, r) for i, r in enumerate(results)],
            terminal_state="completed",
        )
        with store.database.transaction() as connection:
            connection.execute("UPDATE workspaces SET created_at=?,updated_at=?", (STAMP, STAMP))
            connection.execute("UPDATE runs SET created_at=?,updated_at=?", (STAMP, STAMP))
        if store.active_records():
            raise RuntimeError("Samples contain unfinished work")
    finally:
        store.close()
    jobs = SqliteJobStore(DatabaseConfig("simulation", output_dir / names[1]))
    jobs.close()
    for name in names[:2]:
        snapshot(output_dir / name)
    examples: list[dict[str, Any]] = []

    def link(
        slug: str, name: str, runs: list[UUID], tab: str, scenario: UUID | None = None
    ) -> None:
        """Record stable manifest identities alongside their exact relative URL."""
        from urllib.parse import urlencode

        pairs = [("workspace", str(workspace.id))] + [("run", str(run)) for run in runs]
        if scenario is not None:
            pairs.append(("scenario", f"{runs[0]}/{scenario}"))
        pairs.append(("tab", tab))
        examples.append(
            dict(
                slug=slug,
                name=name,
                workspace_id=str(workspace.id),
                run_ids=[str(run) for run in runs],
                scenario_id=str(scenario) if scenario else None,
                url="/?" + urlencode(pairs),
            )
        )

    link("baseline", "README baseline", [baseline.status.id], "team-size")
    link(
        "efficiency-11",
        "Efficiency 11 comparison",
        [baseline.status.id, comparison.status.id],
        "team-size",
    )
    link(
        "baseline-interval",
        "README deployment intervals",
        [baseline.status.id],
        "deployment-interval",
    )
    for team, interval, slug in ((1, 0, "small-team"), (25, 10, "large-team")):
        scenario = next(
            s
            for s in preview.scenarios
            if s.settings.team_size == team and s.settings.deployment_cadence == interval
        )
        link(
            slug,
            f"Team {team}, interval {interval}",
            [baseline.status.id],
            "stage-loss",
            scenario.id,
        )
        for tab in ("resource-utilization", "resource-backlog"):
            link(
                slug + "-" + tab,
                f"Team {team}, interval {interval}: {tab}",
                [baseline.status.id],
                tab,
                scenario.id,
            )
    manifest = dict(
        format_version=1,
        release="readme-v1",
        databases={
            kind: dict(
                filename=name, sha256=hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
            )
            for kind, name in zip(("application", "simulation"), names[:2])
        },
        examples=examples,
        regeneration=dict(
            task_spec=tasks.model_dump(mode="json"),
            definition=definition.model_dump(mode="json"),
            comparison=dict(efficiency_max=11),
            engine_version=ENGINE_VERSION,
            generator_version=GENERATOR_VERSION,
            namespace=str(NAMESPACE),
        ),
    )
    (output_dir / names[2]).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    """Build release artifacts explicitly; generation is never part of startup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    build(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
