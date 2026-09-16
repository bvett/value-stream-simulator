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
* Web service/UI to offer more dynamic 'what-if' analysis
* Extensibility
* Data source integration




