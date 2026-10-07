"""Streaming CSV exports from immutable scenario snapshots."""

from typing import Generator, Literal

import csv
import io
from .generation import canonical
from .schemas import ENGINE_VERSION, GENERATOR_VERSION
from .storage import RunRecord, WorkspaceStore


def safe_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_csv(
    store: WorkspaceStore,
    record: RunRecord,
    kind: Literal["summary", "events", "resources"],
) -> Generator[str, None, None]:
    """Export a simulation result as CSV.

    Args:
        store (WorkspaceStore): Store containing the run results.
        record (RunRecord): Run record to export.
        kind (Literal["summary", "events", "resources"]): Data section to export.

    Yields:
        str: One CSV row at a time.
    """
    common = [
        "scenario_id",
        "scenario_name",
        "scenario_revision",
        "task_set_id",
        "task_set_hash",
        "run_id",
        "comparison_name",
        "execution_seed",
        "task_generation_seed",
        "team_generation_seed",
        "generator_version",
        "engine_version",
        "status",
        "settings",
        "team_efficiencies",
    ]
    fields = {
        "summary": [
            "error_code",
            "error_message",
            "completion_time",
            "initial_value",
            "delivered_value",
            "value_lost_percent",
        ],
        "events": [
            "event",
            "event_type",
            "time",
            "status",
            "loss",
            "task_type",
            "is_rework",
            "duration",
            "resource_id",
            "stage_loss_percent",
        ],
        "resources": [
            "time",
            "state",
            "waiting",
            "allocated",
            "active",
            "success_t",
            "failure_t",
            "interruption_t",
            "waiting_t",
            "idle_t",
        ],
    }[kind]
    # Event status is distinct from the scenario's terminal status.
    headers = ["scenario_status" if x == "status" else x for x in common] + fields
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    yield output.getvalue()
    for outcome in record.status.outcomes:
        s = outcome.scenario
        base = [
            str(s.id),
            safe_text(s.name),
            s.revision,
            str(record.task_set.id),
            record.task_set.content_hash,
            str(record.status.id),
            safe_text(record.status.name),
            s.execution_seed,
            record.task_set.spec.seed,
            s.team_seed,
            GENERATOR_VERSION,
            ENGINE_VERSION,
            outcome.status,
            canonical(s.settings.model_dump()),
            canonical([d.efficiency for d in s.model.developer_team]),
        ]
        if kind == "summary":
            rows = [
                [
                    outcome.error.code if outcome.error else "",
                    safe_text(outcome.error.message) if outcome.error else "",
                    outcome.completion_time,
                    sum(t.initial_value for t in record.task_set.tasks),
                    outcome.delivered_value,
                    outcome.loss_percent,
                ]
            ]
        elif outcome.status == "succeeded":
            result = store.result(record, s.id)
            data = (
                result.metadata.event_metadata
                if kind == "events"
                else result.metadata.resource_metadata
            )

            def event_rows():
                for item in data:
                    values = item.model_dump(mode="json")
                    if kind == "events":
                        values["stage_loss_percent"] = -100 * item.loss
                    yield [values.get(f) for f in fields]

            rows = event_rows()
        else:
            rows = []
        for row in rows:
            output.seek(0)
            output.truncate(0)
            writer.writerow(base + row)
            yield output.getvalue()
