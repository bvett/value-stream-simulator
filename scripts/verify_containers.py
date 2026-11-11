"""Recreate task-owned application/service containers against the same named volumes."""

import argparse
import hashlib
import json
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def docker(*arguments: str, check: bool = True) -> str:
    """Execute Docker without a shell and retain actionable daemon/build diagnostics."""
    return subprocess.run(
        ["docker", *arguments], check=check, capture_output=True, text=True
    ).stdout.strip()


def request(base: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Read a local container endpoint with bounded network waits."""
    payload = json.dumps(body).encode() if body is not None else None
    with urlopen(
        Request(base + path, data=payload, headers={"Content-Type": "application/json"}), timeout=10
    ) as response:
        content = response.read()
        return (
            json.loads(content)
            if response.headers.get_content_type() == "application/json"
            else content
        )


def start(image: str, name: str, volume: str, port: int) -> str:
    """Start one fresh container and wait for its default volume-backed lifespan."""
    docker(
        "run",
        "--rm",
        "-d",
        "--name",
        name,
        "-p",
        f"127.0.0.1::{port}",
        "-v",
        volume + ":/data",
        image,
    )
    base = "http://" + docker("port", name, str(port) + "/tcp").splitlines()[0]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            request(base, "/health")
            return base
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("Container startup failed: " + docker("logs", name, check=False))


def terminal(base: str, path: str, field: str) -> dict[str, Any]:
    """Wait for an actual small simulation rather than trusting a prebundled result."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        value = request(base, path)
        if value[field] in ("completed", "completed_with_errors", "failed", "cancelled"):
            if value[field] != "completed":
                raise AssertionError(value)
            return value
        time.sleep(0.1)
    raise TimeoutError("Container simulation did not finish")


def verify(application_image: str, service_image: str) -> dict[str, str]:
    """Validate persistence after real container replacement and clean up owned resources."""
    token = "value-stream-check-" + uuid4().hex[:12]
    names: list[str] = []
    volumes: list[str] = []
    report: dict[str, str] = {}
    try:
        for kind, image, port in (
            ("application", application_image, 8081),
            ("simulation", service_image, 8080),
        ):
            volume = token + "-" + kind
            docker("volume", "create", volume)
            volumes.append(volume)
            name = volume + "-first"
            names.append(name)
            base = start(image, name, volume, port)
            body: dict[str, Any] = {}
            if kind == "application":
                workspace = request(base, "/api/v1/workspaces", {})
                owner = workspace["id"]
                path = "/api/v1/workspaces/" + owner
                spec = workspace["task_spec"]
                spec["count"] = 2
                definitions = workspace["definitions"]
                definitions[0]["sweeps"] = {"team_size": [1], "deployment_cadence": [0]}
                payload = json.dumps(
                    dict(expected_revision=0, task_spec=spec, definitions=definitions)
                ).encode()
                with urlopen(
                    Request(
                        base + path + "/editor",
                        data=payload,
                        method="PUT",
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=10,
                ) as response:
                    preview = json.load(response)
                run = request(
                    base,
                    path + "/runs",
                    dict(request_id=str(uuid4()), preview_digest=preview["digest"]),
                )
                saved_path = path + "/runs/" + run["id"]
                terminal(base, saved_path, "state")
                saved_path += "/exports/summary"
                before = request(base, saved_path)
                report["workspace_id"] = owner
                report["run_id"] = run["id"]
            else:
                submission = str(uuid4())
                body = dict(
                    submission_id=submission,
                    model_seeds=[42],
                    tasks=[dict(initial_value=1, story_points=1)],
                    models=[
                        dict(
                            developer_team=[dict(name="Dev", efficiency=1)],
                            deployment_cadence=0,
                            qa_testers=dict(kind="pool", limit=1),
                            toolchain_pool=dict(kind="pool", limit=1, deployment_duration=0.1),
                        )
                    ],
                )
                accepted = request(base, "/v1/simulation-jobs", body)
                job_path = "/v1/simulation-jobs/" + accepted["job_id"]
                terminal(base, job_path, "status")
                saved_path = job_path + "/outcomes"
                before = json.dumps(request(base, saved_path), sort_keys=True).encode()
                report["job_id"] = accepted["job_id"]
                # This container must neither depend on Node nor import the application.
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "import sys,shutil; from value_stream.service.app import create_app; "
                    "assert shutil.which('node') is None; "
                    "assert not any(n.startswith('value_stream.app') for n in sys.modules)",
                )
            docker("stop", "--time", "20", name)
            name = volume + "-second"
            names.append(name)
            base = start(image, name, volume, port)
            if kind == "application":
                after = request(base, saved_path)
            else:
                after = json.dumps(request(base, saved_path), sort_keys=True).encode()
                if request(base, "/v1/simulation-jobs", body)["job_id"] != report["job_id"]:
                    raise AssertionError("Submission retry created work after container restart")
            if before != after:
                raise AssertionError(kind + " data changed after container recreation")
            report[kind + "_sha256"] = hashlib.sha256(after).hexdigest()
            docker("stop", "--time", "20", name)
        return report
    finally:
        for name in reversed(names):
            docker("rm", "-f", name, check=False)
        for volume in reversed(volumes):
            docker("volume", "rm", volume)


def main() -> None:
    """Run against explicitly built images, never against unrelated containers or volumes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-image", required=True)
    parser.add_argument("--service-image", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.application_image, args.service_image), sort_keys=True))


if __name__ == "__main__":
    main()
