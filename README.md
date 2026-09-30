# Value Stream Simulator
![Build Status](https://github.com/bvett/value-stream-simulator/actions/workflows/ci.yml/badge.svg)


## What Problem is Being Solved?
Organizations that invest in CI/CD automation may still experience customers that are negatively impacted by delivery pace and/or quality, which can lead to chasing metrics such as release frequency and test coverage.  Doing so can be counterproductive without understanding the *value stream* of software delivery.

A proposed feature or change has an associated value, often implicitly derived from an expected customer benefit.  The value begins to depreciate immediately, and continues to depreciate until it is delivered into production.  This _loss_ represents the cost of delay.

Given a set of proposed features, hereafter referred to as _tasks_, value is maximized when the highest-valued tasks are delivered into production in the least amount of time.  While conceptually simple, optimization requires an understanding of the impact technical and organizational factors have on shipping software.

Understanding where delays and disruptions occur and their impact can help organizations prioritize improvements.   

## Getting Started
### Environment
1. Python >= 3.11 is required
2. Clone this repository and cd to its root
```shell
git clone https://github.com/bvett/value-stream-simulator.git
cd value-stream-simulator
```

3. Create and load a virtual environment:
  * Linux/Mac:
```shell
python -m venv .venv
source .venv/bin/activate
```
  * Windows:
```shell
python -m venv venv
venv/Scripts/activate
```
4. Install Dependencies
```shell
pip install -r requirements.txt
```

5. Install project as a local dependency
```shell
pip install -e .
```
### Demo
[examples/demo.py](https://github.com/bvett/value-stream-simulator/blob/main/src/examples/demo.py) runs a sample simulation then presents the results as different plots

```shell
python src/examples/demo.py
```

### Tutorial
[src/examples/tutorial.ipynb](https://github.com/bvett/value-stream-simulator/blob/main/src/examples/tutorial.ipynb) presents a more detailed walkthrough as a Jupyter notebook.

### Simulation service

`SimulationRunner` now sends one batch of models to an HTTP job service. If
`VALUE_STREAM_SERVICE_URL` is unset, it starts a loopback service automatically
and stops it when the runner closes. Use the runner as a context manager when
embedding it in a script:

```python
with SimulationRunner() as runner:
    results = runner.execute(tasks=tasks, models=models, seed=123)
```

To use a separately running service, start it with:

```shell
python -m uvicorn value_stream.service.app:app --host 127.0.0.1 --port 8080 --workers 1
```

Then set `VALUE_STREAM_SERVICE_URL=http://127.0.0.1:8080` or pass that URL to
`SimulationRunner(service_url=...)`. The service provides `GET /health` and an
OpenAPI 3.1 contract at `GET /openapi.json`. Clients in any language can submit
JSON to `POST /v1/simulation-jobs`, poll `GET /v1/simulation-jobs/{job_id}` and
`GET /v1/simulation-jobs/{job_id}/outcomes?after=0`, and request cancellation
with `DELETE /v1/simulation-jobs/{job_id}`. Outcomes carry a zero-based model
index; the Python runner returns successful results in submission order. If a
model fails, the others continue, and `BatchSimulationError` carries both the
successful indexed results and the model-indexed errors.

The demonstration service retains completed jobs in memory for one hour by
default; jobs do not survive a restart. Limits are configurable through
`VALUE_STREAM_` settings such as `VALUE_STREAM_MAX_TASKS`,
`VALUE_STREAM_MAX_MODELS`, `VALUE_STREAM_MAX_MODEL_WORKERS`, and
`VALUE_STREAM_MAX_MODEL_SECONDS`. See
`src/value_stream/service/settings.py` for the full list and defaults. Run one
HTTP server worker while using the in-memory job store.

An optional Docker image runs the standalone service:

```shell
docker build -t value-stream-service .
docker run --rm -p 127.0.0.1:8080:8080 value-stream-service
```

## Browser simulation studio

**Using VS Code?** Open `value-stream.code-workspace` and follow the
[studio workspace guide](docs/studio-workspace.md) for setup, F5 debugging in an
editor browser, hot reload, test tasks, and visual CSS editing.

The browser application creates shared task sets and model sweeps, plots completed
scenarios as they arrive, and retains a baseline plus interactive/pinned comparisons.
It uses React/TypeScript and Plotly in the browser, and FastAPI with the existing
HTTP simulation service. Runtime storage is temporary server memory. Use one
application process; horizontal scaling and persistent storage are future work.

From a source checkout, build the browser assets once using Node 22.12+ (Node 22
or 24) and npm, then start the application:

```shell
npm ci --prefix src/value_stream/app/frontend
npm run build --prefix src/value_stream/app/frontend
python -m value_stream.app
```

Open **http://127.0.0.1:8081**. The command starts and owns a local loopback
simulation service automatically. The packaged wheel includes the built browser
assets and needs no Node installation to run. Building a wheel for the application
requires building those assets first. The existing service-only distribution and
Dockerfile continue to work independently.

Use `--host`, `--port`, or `--service-url` to override startup settings. The service
URL takes precedence over `VALUE_STREAM_SERVICE_URL`; absent both, startup uses
the managed local service. An external service must support the optional
`model_seeds` and `submission_id` request fields. Stopping the application cancels
its jobs and releases its owned local service, without shutting down an external
service. `/health` reports app liveness; `/ready` checks service compatibility.

```shell
docker build -f Dockerfile.app -t value-stream-app .
docker run --rm -p 127.0.0.1:8081:8081 value-stream-app
```

To explore a first comparison, leave team sizes at 2, 4, and 6, set a task count,
and click **Preview sweep**, then **Run 3 scenarios**. Enable **Interactive mode**
and change the deployment interval to add another series. Slider changes commit
on release, and number inputs commit on Enter or blur. The baseline stays fixed;
use the diamond control to pin a completed alternative. Cancel stops the whole
current job, retains completed results, and pauses interactive submissions.
Browser refreshes and reconnects restore the workspace while its server is alive.
A server restart clears it. New task sets start separate comparison contexts.

Value lost is a positive percentage of total initial value, with lower values
better. Zero initial value displays N/A. Mean stage loss weights completed stage
visits equally, including failure/rework visits; it is not an additive breakdown
of overall loss. Resource utilization shows **recorded activity shares**, which
can overlap and do not measure total capacity utilization. Resource backlog
counts waiting **resource requests**, which may contain task batches and exclude
waiting for a deployment interval before requesting resources. Suggestions are
untested proposals. Each scenario is one seeded simulation, not a confidence
interval or causal estimate.

Linear team efficiencies span the bounds at each team size (one developer uses
the midpoint). Normal efficiencies use a bounded normal distribution with midpoint
mean and standard deviation equal to one-sixth of the range. Task, team, and
execution seeds are stored independently. Reordering/subsetting a scenario keeps
its numerical outcomes reproducible for the same engine/generator version;
resource UUIDs are not reproducible. Explicit seeds also fix the previously
unordered support-resource candidate enumeration. Simulation changes may alter
random draw sequences; comparisons do not imply paired statistical samples.

Summary, stage-event, and resource-history CSV downloads include scenario identity,
settings, and seed provenance. Exports use full data even when a plot is reduced
in resolution. The summary includes failed/cancelled rows; event/resource exports
contain available successful results. Raw event loss remains signed, with an
additional positive percentage column. User-provided text beginning with a
spreadsheet formula prefix is escaped in CSV output.

App limits use `VALUE_STREAM_APP_` environment variables from
`src/value_stream/app/settings.py`. Defaults include 1,000 tasks, 100 models/run,
100 resources per pool/team, 32 values per sweep axis, four workspaces, four active
runs globally (one per workspace), 12 pinned comparisons per workspace, 2 MiB
mutation bodies, 16 MiB stored inputs, and 256 MiB retained result payloads.
Execution limits remain enforced by the service (`VALUE_STREAM_` settings).
Payload limits do not represent exact Python memory consumption. Protected
comparisons are never silently evicted; capacity errors explain when to delete
or unpin history. Temporary submission identifiers prevent duplicate retries
until service job expiry/restart. They do not guarantee exactly-once execution
across an undetected service restart during a lost submission response.

The app OpenAPI contract is checked in at `src/value_stream/app/openapi.json`.
Errors use `{code, message, details}`. Validation and limit errors return 422,
large bodies 413, stale edits and conflicting submissions 409, full app capacity
429, missing workspace/results 404, unavailable/incompatible services 503, and
unexpected errors 500. Per-model errors preserve successful plots and exports.
Connection loss preserves results and offers resume after bounded automatic retries.

Frontend development can use `npm run dev --prefix src/value_stream/app/frontend`
with the Python server on 8081. Its dev server proxies application API requests.
Validation commands:

```shell
pytest --cov=src --cov-report=xml tests -s
npm run typecheck --prefix src/value_stream/app/frontend
npm test --prefix src/value_stream/app/frontend -- --run
npm run build --prefix src/value_stream/app/frontend
cd src/value_stream/app/frontend
npx playwright install chromium
npm run test:e2e
```

Playwright starts an isolated production application on port 18081. Set
`VALUE_STREAM_TEST_PYTHON` to an absolute Python executable if not using the root
`.venv`. Generate contracts with the script `python -m value_stream.app.contracts`,
then `npm run generate:api --prefix src/value_stream/app/frontend`; CI checks drift.

## Project Status and Objectives
This project provides a limited feature set that supports correlating delivery cadence and development team size/ability against value & loss.  Near-term objectives include:

* Introducing additional simulation parameters, including:
  * stability, including maturity of monitoring, observability, and runbook automation
  * task-interdependencies
  * developer turnover/onboarding
  * testing effectiveness
  * requirements/priority stability
  * impact of 'mandatory work' 
* Introduce notion of cost and enable value stream to be optimized while minimizing cost
* Enabling simulations to cover additional dimensions, including feedback on factors that introduce the greatest loss

Future objectives:
* Shared storage and horizontal scaling for the web application
* Extensibility
* Data source integration



