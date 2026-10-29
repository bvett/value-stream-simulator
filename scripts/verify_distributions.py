"""Validate frozen bundle contents and the actual wheel/sdist without rerunning models."""

import argparse
import hashlib
import json
import sqlite3
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

from value_stream.app.sample_import import read_rows, validate
from value_stream.app.settings import AppSettings
from value_stream.app.sqlite_storage import workspace_payloads, workspace_schema
from value_stream.service.persistence.config import DatabaseConfig
from value_stream.service.persistence.database import SqliteDatabase
from value_stream.service.persistence.job_store import job_payloads, job_schema

BUNDLE = "value_stream/service/persistence/samples/"
FILES = ("application.sqlite3", "simulation.sqlite3", "manifest.json")
NAMESPACE = uuid5(
    NAMESPACE_URL, "https://github.com/bvett/value-stream-simulator/samples/readme-v1"
)


def bundle(directory: Path) -> dict[str, Any]:
    """Check integrity, fixed IDs, frozen inputs/provenance, and every view reference."""
    manifest = json.loads((directory / "manifest.json").read_text())
    if type(manifest["format_version"]) is not int or manifest["format_version"] != 1:
        raise ValueError("Unsupported bundle manifest")
    frozen = manifest["regeneration"]
    if frozen["namespace"] != str(NAMESPACE):
        raise ValueError("Unexpected sample namespace")
    for kind in ("application", "simulation"):
        path = directory / f"{kind}.sqlite3"
        if manifest["databases"][kind]["filename"] != path.name:
            raise ValueError("Unexpected sample filename")
        with path.open("rb") as reader:
            if (
                hashlib.file_digest(reader, "sha256").hexdigest()
                != manifest["databases"][kind]["sha256"]
            ):
                raise ValueError("Sample checksum mismatch")
        if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("Distributed snapshots cannot depend on sidecars")
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
            manager = SqliteDatabase(
                DatabaseConfig(kind, path),
                schema=workspace_schema() if kind == "application" else job_schema(),
                payloads=workspace_payloads() if kind == "application" else job_payloads(),
            )
            manager._validate(connection)
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("Bundle must use DELETE journal mode")
            if kind == "simulation":
                if connection.execute("SELECT count(*) FROM jobs").fetchone()[0]:
                    raise ValueError("Simulation sample must be empty")
                continue
            data = read_rows(connection)
            validate(data, AppSettings())
            workspace_id = str(uuid5(NAMESPACE, "readme-workspace"))
            baseline_id = str(uuid5(NAMESPACE, "readme-baseline"))
            comparison_id = str(uuid5(NAMESPACE, "readme-efficiency-11"))
            if len(data.rows["workspaces"]) != 1 or len(data.rows["task_sets"]) != 1:
                raise ValueError("Expected one example workspace and task set")
            workspace = json.loads(data.rows["workspaces"][0]["payload_json"])
            tasks = json.loads(data.rows["task_sets"][0]["payload_json"])
            if (
                workspace["id"] != workspace_id
                or workspace["baseline_id"] != baseline_id
                or workspace["latest_id"] != comparison_id
                or tasks["id"] != str(uuid5(NAMESPACE, "readme-tasks"))
                or tasks["spec"] != frozen["task_spec"]
                or workspace["definitions"] != [frozen["definition"]]
            ):
                raise ValueError("Frozen input identities or specs differ from manifest")
            runs = {row["id"]: row for row in data.rows["runs"]}
            if set(runs) != {baseline_id, comparison_id}:
                raise ValueError("Expected baseline and efficiency comparison")
            for run_id, row in runs.items():
                outcomes = [r for r in data.rows["run_outcomes"] if r["run_id"] == run_id]
                if row["state"] != "completed" or len(outcomes) != 9:
                    raise ValueError("Expected nine completed outcomes per run")
                for outcome in outcomes:
                    if outcome["status"] != "succeeded":
                        raise ValueError("Sample execution did not succeed")
                    settings = json.loads(outcome["payload_json"])["scenario"]["settings"]
                    if settings["efficiency_max"] != (
                        11
                        if run_id == comparison_id
                        else frozen["definition"]["settings"]["efficiency_max"]
                    ):
                        raise ValueError("Unexpected comparison model inputs")
            for row in data.rows["result_blobs"]:
                if (
                    row["engine_version"] != frozen["engine_version"]
                    or row["generator_version"] != frozen["generator_version"]
                ):
                    raise ValueError("Result provenance differs from manifest")
            slugs: set[str] = set()
            tabs: set[str] = set()
            for example in manifest["examples"]:
                url = urlsplit(example["url"])
                query = parse_qs(url.query)
                if (
                    url.scheme
                    or url.netloc
                    or url.path != "/"
                    or example["slug"] in slugs
                    or query.get("workspace") != [workspace_id]
                    or query.get("run") != example["run_ids"]
                    or not example["run_ids"]
                ):
                    raise ValueError("Invalid example URL or identities")
                slugs.add(example["slug"])
                if any(identity not in runs for identity in example["run_ids"]):
                    raise ValueError("Example run is missing")
                if example["scenario_id"]:
                    detail = f"{example['run_ids'][0]}/{example['scenario_id']}"
                    if query.get("scenario") != [detail] or not any(
                        r["run_id"] == example["run_ids"][0]
                        and r["scenario_id"] == example["scenario_id"]
                        for r in data.rows["run_outcomes"]
                    ):
                        raise ValueError("Example detail is missing")
                tab = query.get("tab", [])
                if len(tab) != 1:
                    raise ValueError("Example needs an exact chart tab")
                tabs.add(tab[0])
            if tabs != {
                "team-size",
                "deployment-interval",
                "stage-loss",
                "resource-utilization",
                "resource-backlog",
            }:
                raise ValueError("Manifest must cover all five chart tabs")
        finally:
            connection.close()
    return manifest


def archives(wheel: Path, sdist: Path) -> dict[str, Any]:
    """Inspect both real archives and validate their extracted sample bytes.

    Args:
        wheel: Built installed-package archive, including compiled UI assets.
        sdist: Built source archive, excluding frontend source/dependencies.

    Returns:
        Verified release and inventory information suitable for CI evidence.
    """
    report: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="value-stream-distribution-") as temporary:
        for kind, path in (("wheel", wheel), ("sdist", sdist)):
            destination = Path(temporary) / kind
            destination.mkdir()
            if kind == "wheel":
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    if "value_stream/app/static/index.html" not in names or not any(
                        name.startswith("value_stream/app/static/assets/") for name in names
                    ):
                        raise ValueError("Wheel is missing compiled frontend assets")
                    contents = {name: archive.read(BUNDLE + name) for name in FILES}
            else:
                with tarfile.open(path) as archive:
                    members = {
                        "/".join(member.name.split("/")[1:]): member
                        for member in archive.getmembers()
                    }
                    names = list(members)
                    contents = {}
                    for name in FILES:
                        reader = archive.extractfile(members["src/" + BUNDLE + name])
                        if reader is None:
                            raise ValueError("Missing sample archive member")
                        with reader:
                            contents[name] = reader.read()
            if any("/frontend/" in name or "/node_modules/" in name for name in names):
                raise ValueError("Frontend source/dependencies leaked into distribution")
            for name, content in contents.items():
                (destination / name).write_bytes(content)
            manifest = bundle(destination)
            report[kind] = {
                "release": manifest["release"],
                "samples": list(contents),
                "examples": len(manifest["examples"]),
            }
    return report


def main() -> None:
    """Verify repository samples alone, or include both distribution archives."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    args = parser.parse_args()
    if args.wheel is not None and args.sdist is not None:
        print(json.dumps(archives(args.wheel, args.sdist), sort_keys=True))
    elif args.wheel is None and args.sdist is None:
        manifest = bundle(Path(__file__).resolve().parents[1] / "src" / BUNDLE)
        print(f"Verified {manifest['release']}: {len(manifest['examples'])} exact views.")
    else:
        parser.error("Provide both --wheel and --sdist")


if __name__ == "__main__":
    main()
