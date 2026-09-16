# Simulation service specification

The implementation design and validation milestones are in `.agent/SIMULATION_SERVICE_EXECPLAN.md`, maintained according to `.agent/PLANS.md`. This specification records the agreed behavior; the ExecPlan resolves version 1 implementation choices.

## Goals

- Create an HTTP service that executes `value_stream.simulation.Simulation` and returns its results.
- Create a Python HTTP client under `src/value_stream/client/web`.
- Update `value_stream.client.SimulationRunner` to use the client for remote execution and to support a local service instance when no service URL is supplied.
- Keep the service contract suitable for a later web application that accepts simulation inputs and renders results. The web application is outside version 1.

## Version 1 requirements

- Service source files belong under `src/value_stream/service`.
- Define the HTTP API using OpenAPI 3.1. Specify request, response, and error schemas rather than passing arbitrary Python objects across the wire.
- Keep the public API language-neutral: ordinary HTTP requests and JSON bodies must be usable by a later browser client or another language without importing Python package classes. Python `SimulationResult` reconstruction is specific to the version 1 Python client.
- Accept a batch of models with a shared set of tasks in one request. Preserve the association between each submitted model and its result, and return results in a form that the Python client can reconstruct as the existing `SimulationResult` types. Existing `ResultViewer` and `MetadataViewer` behavior must continue to work, including summary, task-event, and resource metadata.
- Use `DefaultSimulationPolicy` in version 1. Supporting other policies is a future extension.
- Allow a caller above `SimulationRunner` to supply a service URL; support an environment override. Service discovery is deferred.
- If neither the caller nor the environment supplies a service URL, `SimulationRunner` starts and uses a local HTTP service bound to loopback. Reuse one local instance across runner objects in the same Python process, and stop it when the last owning runner closes. `SimulationRunner` does not call `Simulation` directly.
- Submit the shared tasks and batch of models through a job API. Submission returns a job identifier promptly; clients can obtain status and each model's result as it completes through separate API calls. Define job expiration and cancellation behavior in the API contract.
- Allow concurrent execution of models in a batch. Label each result with its submitted model index so the Python client can return the final `list[SimulationResult]` in submission order, regardless of completion order.
- If one model fails, continue executing the others. Report the failed model's index and a structured error alongside successful results. A job reaches a terminal state after every model has either succeeded or failed.
- After a partially failed job reaches its terminal state, `SimulationRunner.execute` raises a dedicated batch error that carries successful `SimulationResult` objects in submission order and model-indexed errors. A fully successful job retains the existing `list[SimulationResult]` return type. The client must not silently omit failed models or put error objects in a list consumed by the existing viewers.
- Accept an optional seed with each job. Derive an independent, repeatable random stream for each submitted model from the job seed and model index, so scheduling and completion order do not change seeded simulation outcomes. The seed governs randomness during simulation; task/model factory randomness before submission is outside its scope.
- Include unit and integration tests, including a service/client round trip and compatibility checks for the existing viewers.
- Handle invalid input, execution failures, and client connection failures with a documented error contract.
- Provide an option to package and run the service as a Docker image.
- Keep simulation state isolated per model. Put job state behind a replaceable storage interface so a later multi-instance deployment can use shared storage. Version 1 may store jobs in memory; results need not survive service restarts.
- Add configurable protections against excessive resource use, including admission and execution limits. Select initial defaults during design and document their errors in the API contract.

## Intended use and future scope

Version 1 is for individuals demonstrating the value-stream project. A shared, multi-user deployment, authentication, policy extensibility, service discovery, persistent results, and a browser web application are later phases. The version 1 design should leave room for these capabilities; it does not need to expose unused authentication or multi-user behavior.

## Implementation design prerequisites

- Write an ExecPlan for this significant feature before coding, following `.agent/PLANS.md` as required by `AGENTS.md`.
- Select a worker strategy that keeps model execution and random state isolated without blocking HTTP request handling. Verify that seeded results do not depend on concurrent scheduling. Document concurrency limits and cancellation semantics.
- Define OpenAPI 3.1 schemas for tasks, models, resource pools, summary results, task events, resource metadata, job status, and errors. Preserve fields and types needed by current viewers; account for enums and UUIDs. Decide whether the Python client reuses submitted model objects in reconstructed results or creates equivalent objects.
- Define job-state retention and expiry, behavior when a job ID is unknown or expired, and what happens to running jobs when the in-memory service stops. Expose per-model progress and errors without losing successful results.
- Choose configurable defaults for task count, model count, concurrency, run duration, and request/response size. Reject excess load with documented errors.
- Establish a round-trip test that passes reconstructed results through `ResultViewer` and `MetadataViewer`, and test local service startup and shutdown as well as remote connection failures.
- Add a CI contract-alignment check that detects new simulation input fields omitted from the wire schemas or codecs. Review the generated OpenAPI contract when the server schema changes, and test the HTTP contract without the Python client.
