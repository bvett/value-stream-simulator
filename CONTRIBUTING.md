Thank you for taking an interest in this project.  It provides developer-centric information about the project, including:
* [Development Practices](#development-practices): Workspace setup, testing, coding and documentation styles.
* [Technical Details](#technical-details): Architecture diagrams, configuration, and other details on the project internals.

# Development Practices

## Setting up a Workspace

1. Install prerequisites:
* Python >= 3.11: 
  * [MacOS](https://docs.python.org/3/using/mac.html#)
  * [Windows](https://www.python.org/downloads/windows/)
  * [Linux](https://docs.python.org/3/using/unix.html)

* [Node 22 or 24](https://nodejs.org/en/download)

* [uv](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer)

2. Clone this repository and cd to its root
```shell
git clone https://github.com/bvett/value-stream-simulator.git
cd value-stream-simulator
```

3. Create and load a virtual environment:
  * Linux/Mac:
```shell
uv venv .venv
source .venv/bin/activate
```
  * Windows:
```shell
uv venv .venv
.venv\Scripts\activate
```
4. Install Dependencies for Development
```shell
uv sync --locked --all-extras --dev
uv pip install -e .
```

5. Install Front-End Components
```shell
npm ci --prefix src/value_stream/app/frontend
npm run build --prefix src/value_stream/app/frontend
```

6. Start the application
```shell
python -m value_stream.app
```

### Visual Studio Code
Open `value-stream.code-workspace` and follow the [studio workspace guide](docs/studio-workspace.md) for setup, F5 debugging in an editor browser, hot reload, test tasks, and visual CSS editing.

## Conventions
### Code Formatting
* This project uses [Black](https://black.readthedocs.io/en/stable/the_black_code_style/index.html) on Python source files
* Maximum line length : 100

### Docstrings
Python method docstrings follow the [Google Style Guide](https://google.github.io/styleguide/pyguide.html#383-functions-and-methods)

### Branching and Commits
* Use [Git Branch Naming Convention and Commit Messages Best Practices](https://github.com/gauravjainse/git-best-practices) as a general guideline.  
* Key points:
  * Feature branches should be branched off of _main_ and be prefixed with "feature/" 
  * Squash commits before opening a pull request.
  * Commit messages should be declarative and have a prefix that denotes the type of commit.
  * Avoid mixing non-functional and functional changes. Minor exceptions are allowed when it doesn't affect clarity for a code review, for example, removing unused imports.

### Updating OpenAPI Contracts

When the data model changes, the following tests will fail if either detect drift between the models and respective OpenAPI specifications.

* [OpenAPI Spec for App Service](./src/value_stream/app/openapi.json) : [test_contract_snapshot](./tests/integration/test_app_roundtrip.py)
* [OpenAPI Spec for API Service](./src/value_stream/service/openapi.json) : [test_reviewed_openapi_matches_application](./tests/unit/service/test_contract_alignment.py)

To update, run these commands from the workspace root and commit any changes with the updated models:

```shell
uv run python -m value_stream.app.contracts
npm run generate:api --prefix src/value_stream/app/frontend
```

## Testing
Unless otherwise noted, execute commands from the workspace root.

### Python

Pytest is configured in [pyproject.toml](pyproject.toml) to generate coverage reports by default.  View the report using _coverage_:

```shell
uv run pytest
coverage report
```

## Node  Tests
Ensure you've built the front-end:

```shell
npm ci --prefix src/value_stream/app/frontend
npm run typecheck --prefix src/value_stream/app/frontend
npm run build --prefix src/value_stream/app/frontend
npm test --prefix src/value_stream/app/frontend -- --run
```
### End-to-End
Configure and run Playwright tests:
```shell
cd src/value_stream/app/frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

Playwright starts an isolated production application on port 18081. Set
`VALUE_STREAM_TEST_PYTHON` to an absolute Python executable if not using the root
`.venv`. 

## Deployment / Execution
Refer to the Installation section in [README.md](README.md) for steps on starting the application.

```shell
python -m value_stream.app
```
Open **http://127.0.0.1:8081**. The command starts and owns a local loopback simulation service automatically. The packaged wheel includes the built browser assets and needs no Node installation to run. Building a wheel for the application requires building those assets first. The existing service-only distribution and Dockerfile continue to work independently.

Use `--host`, `--port`, or `--service-url` to override startup settings. 

The service URL takes precedence over `VALUE_STREAM_SERVICE_URL`; absent both, startup uses the managed local service. An external service must support the optional `model_seeds` and `submission_id` request fields. Stopping the application cancels its jobs and releases its owned local service, without shutting down an external service. `/health` reports app liveness; `/ready` checks service compatibility.

Frontend development can use `npm run dev --prefix src/value_stream/app/frontend` with the Python server on 8081. Its dev server proxies application API requests.

### Docker

An optional Docker image runs the standalone service:
```shell
docker build -t value-stream-service .
docker run --rm -p 127.0.0.1:8080:8080 value-stream-service
```

# Technical Details


## Architecture Diagrams
Contributors can use the [architecture diagrams](docs/architecture.md) to trace
the studio application, simulation service, and simulation engine.

## API Service
`SimulationRunner` sends one batch of models to an HTTP job service. If `VALUE_STREAM_SERVICE_URL` is unset, it starts a loopback service automatically and stops it when the runner closes. Use the runner as a context manager when embedding it in a script:

```python
with SimulationRunner() as runner:
    results = runner.execute(tasks=tasks, models=models, seed=123)
```

To use a separately running service, start it with:

```shell
python -m uvicorn value_stream.service.app:app --host 127.0.0.1 --port 8080 --workers 1
```

Then set `VALUE_STREAM_SERVICE_URL=http://127.0.0.1:8080` or pass that URL to `SimulationRunner(service_url=...)`. The service provides `GET /health` and an OpenAPI 3.1 contract at `GET /openapi.json`. Clients in any language can submit JSON to `POST /v1/simulation-jobs`, poll `GET /v1/simulation-jobs/{job_id}` and `GET /v1/simulation-jobs/{job_id}/outcomes?after=0`, and request cancellation with `DELETE /v1/simulation-jobs/{job_id}`. 

Outcomes carry a zero-based model index; the Python runner returns successful results in submission order. If a model fails, the others continue, and `BatchSimulationError` carries both the successful indexed results and the model-indexed errors.

The demonstration service retains completed jobs in memory for one hour by default; jobs do not survive a restart. Limits are configurable through `VALUE_STREAM_` settings such as `VALUE_STREAM_MAX_TASKS`,
`VALUE_STREAM_MAX_MODELS`, `VALUE_STREAM_MAX_MODEL_WORKERS`, and `VALUE_STREAM_MAX_MODEL_SECONDS`. 

See`src/value_stream/service/settings.py` for the full list and defaults. Run one HTTP server worker while using the in-memory job store.


## App Service / Simulation Studio frontend
* Uses React/TypeScript and Plotly in the browser, and FastAPI with the existing HTTP simulation service.

* Runtime storage is temporary server memory. Use one application process; horizontal scaling and persistent storage are future work.

* The browser application creates shared task sets and model sweeps, plots completed scenarios as they arrive, and retains a baseline plus interactive/pinned comparisons.

* Linear team efficiencies span the bounds at each team size (one developer uses the midpoint). Normal efficiencies use a bounded normal distribution with midpoint mean and standard deviation equal to one-sixth of the range. 

* The app OpenAPI contract is checked in at `src/value_stream/app/openapi.json`.
* Errors use `{code, message, details}`. 
  * Validation and limit errors return 422
  * Large bodies 413
  * Stale edits and conflicting submissions 409
  * Full app capacity 429
  * Missing workspace/results 404
  * Unavailable/incompatible services 503
  * Unexpected errors 500. 
* Per-model errors preserve successful plots and exports.
* Connection loss preserves results and offers resume after bounded automatic retries.


App limits use `VALUE_STREAM_APP_` environment variables from `src/value_stream/app/settings.py`. 
* Defaults include:
  * 1,000 tasks
  * 500 models/run
  * 100 resources per pool/team
  * 32 values per sweep axis
  * 4 workspaces
  * 4 active runs globally (one per workspace)
  * 12 pinned comparisons per workspace
  * 2 MiB mutation bodies
  * 16 MiB stored inputs
  * 256 MiB retained result payloads

* Execution limits remain enforced by the service (`VALUE_STREAM_` settings). Payload limits do not represent exact Python memory consumption. 

* Protected comparisons are never silently evicted; capacity errors explain when to delete or unpin history. 

* Temporary submission identifiers prevent duplicate retries until service job expiry/restart. They do not guarantee exactly-once execution across an undetected service restart during a lost submission response.

* Task, team, and execution seeds are stored independently. 

* Reordering/subsetting a scenario keeps its numerical outcomes reproducible for the same engine/generator version; resource UUIDs are not reproducible. 











