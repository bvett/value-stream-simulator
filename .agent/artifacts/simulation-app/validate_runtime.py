import csv, io, json, sys, time, uuid, re
from pathlib import Path
import httpx
import psutil

url, label, *pid = sys.argv[1:]
client = httpx.Client(base_url=url, timeout=30, trust_env=False)
for _ in range(100):
    try:
        if client.get("/ready").status_code == 200:
            break
    except httpx.ConnectError:
        pass
    time.sleep(0.1)
assert client.get("/health").status_code == 200
html = client.get("/")
assert html.status_code == 200 and html.headers["cache-control"] == "no-cache"
for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.text):
    response = client.get(asset)
    assert (
        response.status_code == 200 and "immutable" in response.headers["cache-control"]
    )
assert client.get("/api/v1/missing").status_code == 404
w = client.post("/api/v1/workspaces").json()
p = "/api/v1/workspaces/" + w["id"]
w["task_spec"]["count"] = 3
w["definitions"][0]["sweeps"] = {
    "team_size": list(range(1, 11)),
    "deployment_cadence": list(range(10)),
}
extra = dict(w["definitions"][0], id=str(uuid.uuid4()), sweeps={})
rejected = client.put(
    p + "/editor",
    json={
        "expected_revision": 0,
        "task_spec": w["task_spec"],
        "definitions": w["definitions"] + [extra],
    },
)
assert (
    rejected.status_code == 422 and rejected.json()["code"] == "LIMIT_EXCEEDED"
), rejected.text
preview = client.put(
    p + "/editor",
    json={
        "expected_revision": 0,
        "task_spec": w["task_spec"],
        "definitions": w["definitions"],
    },
).json()
assert preview["count"] == 100, preview
started = time.monotonic()
r = client.post(
    p + "/runs",
    json={"request_id": str(uuid.uuid4()), "preview_digest": preview["digest"]},
)
assert r.status_code == 202, r.text
run_path = p + "/runs/" + r.json()["id"]
peak = 0
latencies = []
progress = []
while time.monotonic() - started < 90:
    tick = time.monotonic()
    run = client.get(run_path).json()
    latencies.append(time.monotonic() - tick)
    progress.append(sum(o["status"] == "succeeded" for o in run["outcomes"]))
    if pid:
        parent = psutil.Process(int(pid[0]))
        total = 0
        for process in [parent] + parent.children(recursive=True):
            try:
                total += process.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        peak = max(peak, total)
    if run["state"] in ("completed", "failed", "completed_with_errors"):
        break
    time.sleep(0.05)
assert run["state"] == "completed", run
assert progress[-1] == 100
elapsed = time.monotonic() - started
csv_sizes = {}
for kind in ("summary", "events", "resources"):
    response = client.get(run_path + "/exports/" + kind)
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows
    if kind == "summary":
        assert len(rows) == 100
    csv_sizes[kind] = len(response.content)
result = {
    "runtime": label,
    "models": 100,
    "tasks": 3,
    "duration_seconds": round(elapsed, 3),
    "peak_process_tree_rss_bytes": peak or None,
    "max_status_request_seconds": round(max(latencies), 4),
    "partial_result_counts": sorted(set(progress)),
    "status_bytes": len(json.dumps(run)),
    "csv_bytes": csv_sizes,
    "reject_101_status": rejected.status_code,
    "ui_assets": True,
}
if label == "docker":
    w["task_spec"]["count"] = 1000
    preview = client.put(
        p + "/editor",
        json={
            "expected_revision": 1,
            "task_spec": w["task_spec"],
            "definitions": w["definitions"],
        },
    ).json()
    r = client.post(
        p + "/runs",
        json={"request_id": str(uuid.uuid4()), "preview_digest": preview["digest"]},
    )
    assert r.status_code == 202, r.text
    cancel_path = p + "/runs/" + r.json()["id"]
    for _ in range(300):
        run = client.get(cancel_path).json()
        if any(o["status"] == "succeeded" for o in run["outcomes"]):
            break
        time.sleep(0.05)
    assert run["state"] not in ("completed", "failed"), run
    client.delete(cancel_path)
    for _ in range(200):
        run = client.get(cancel_path).json()
        if run["state"] == "cancelled":
            break
        time.sleep(0.05)
    assert run["state"] == "cancelled", run
    result["cancelled_models"] = sum(
        o["status"] == "cancelled" for o in run["outcomes"]
    )
    result["retained_successes_after_cancel"] = sum(
        o["status"] == "succeeded" for o in run["outcomes"]
    )
    assert (
        result["cancelled_models"] > 0 and result["retained_successes_after_cancel"] > 0
    )
    assert client.get(cancel_path + "/exports/summary").status_code == 200
Path(".agent/artifacts/simulation-app/" + label + "-validation.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result, indent=2))
