"""Manifest-derived documentation links, filtered against the user's retained records."""

import json
from importlib import resources
from uuid import UUID

from .errors import AppError
from .schemas import ExampleCatalog, ExampleLink
from .storage import WorkspaceStore


def available_examples(store: WorkspaceStore) -> ExampleCatalog:
    """Expose safe link metadata only while every referenced record remains available."""
    manifest = resources.files("value_stream.service.persistence").joinpath("samples/manifest.json")
    try:
        value = json.loads(manifest.read_text())
    except FileNotFoundError:
        return ExampleCatalog(release="unbundled", examples=[])
    links: list[ExampleLink] = []
    for entry in value["examples"]:
        link = ExampleLink.model_validate({key: entry[key] for key in ("name", "slug", "url")})
        try:
            workspace = store.get(UUID(entry["workspace_id"]))
            runs = [
                next((r for r in workspace.runs if str(r.id) == identity), None)
                for identity in entry["run_ids"]
            ]
            if not runs or any(r is None for r in runs):
                continue
            if len({r.task_set_id for r in runs if r}) != 1:
                continue
            first = runs[0]
            assert first is not None
            scenario_id = entry.get("scenario_id")
            if scenario_id and not any(
                str(o.scenario.id) == scenario_id and o.status == "succeeded"
                for o in first.outcomes
            ):
                continue
        except AppError:
            continue
        links.append(link)
    return ExampleCatalog(release=value["release"], examples=links)
