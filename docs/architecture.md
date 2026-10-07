# Architecture Diagrams

These diagrams describe the current implementation in `src/value_stream/`. The
**application** (`app/`) serves the studio UI and owns workspaces and comparisons.
The **simulation service** (`service/`) accepts bounded jobs and runs each model
in a worker subprocess. The application can start a loopback service in its own
process, or connect to an external one with `VALUE_STREAM_SERVICE_URL`. In both
cases, the boundary between them is HTTP. Both stores are in memory; restarting
either server loses its state.

## System architecture

```mermaid
flowchart LR
    subgraph Browser[Browser]
        UI[React studio]
        Charts[Plotly charts]
        UI --> Charts
    end

    subgraph Application[Application API - app]
        Routes[FastAPI routes]
        Store[InMemoryWorkspaceStore]
        Coordinator[RunCoordinator]
        Gateway[HttpSimulationGateway]
        Views[Metrics, insights, CSV exports]
        Routes --> Store
        Routes --> Coordinator
        Coordinator --> Store
        Coordinator --> Gateway
        Routes --> Views
        Views --> Store
    end

    subgraph Service[Simulation job service - service]
        Jobs[FastAPI job routes]
        JobStore[InMemoryJobStore]
        Scheduler[ModelScheduler]
        Jobs --> JobStore
        Jobs --> Scheduler
        Scheduler --> JobStore
    end

    subgraph Worker[One subprocess per active model]
        Codec[Wire codec]
        Engine[Simulation engine]
        Codec --> Engine
    end

    UI <-->|Workspace and result JSON, CSV| Routes
    Gateway <-->|HTTP job JSON| Jobs
    Scheduler <-->|JSON over stdin and stdout| Codec
```

The frontend calls only the application API. `app/frontend/src/types.ts` wraps
the generated API types; `app/server.py` defines the browser routes. The job
service has its own contract in `service/schemas.py` and `service/app.py`.

## Application: editor to comparison

```mermaid
sequenceDiagram
    actor Contributor as Studio user
    participant UI as React studio
    participant API as Application API
    participant Store as WorkspaceStore
    participant Gen as Scenario generation
    participant Coord as RunCoordinator
    participant Service as Simulation service

    Contributor->>UI: Edit task set, model settings, sweeps
    UI->>API: PUT workspace/editor
    API->>Store: save_editor(EditorRequest)
    Store->>Gen: materialize_tasks and expand_scenarios
    Gen-->>Store: TaskSet and concrete scenarios
    Store-->>API: Preview with digest
    API-->>UI: Preview with digest
    Contributor->>UI: Preview and run scenarios
    UI->>API: POST workspace/preview
    API->>Store: preview(workspace_id)
    Store-->>API: Preview with digest
    API-->>UI: Preview with digest
    UI->>API: POST workspace/runs with preview digest
    API->>Coord: start_run(RunRequest)
    Coord->>Store: register run and find cached results
    Coord-->>API: RunStatus
    API-->>UI: RunStatus
    opt Uncached scenarios
        Coord->>Service: Submit JobRequest with tasks and models
        loop Until terminal job status
            Coord->>Service: Read status and outcome page
            Service-->>Coord: Model results or errors
            Coord->>Store: Retain results and update outcome cursors
        end
    end
    loop While run is active
        UI->>API: GET workspace and result views
        API->>Store: Read status and retained results
        API-->>UI: RunStatus, plots, observations
    end
```

The preview digest guards against running stale editor inputs. A run can reuse
cached scenario results; only uncached models are sent to the service. The
browser polls the workspace, while the coordinator polls service outcomes.

## Application: principal classes

```mermaid
classDiagram
    class WorkspaceStore {
        <<interface>>
        +create() Workspace
        +save_editor() Preview
        +preview() Preview
        +register()
        +retain_result() void
    }
    class InMemoryWorkspaceStore {
        +workspaces
        +runs
        +cache
    }
    class SimulationGateway {
        <<interface>>
        +submit() JobAccepted
        +status() JobStatus
        +outcomes() OutcomePage
        +cancel() JobStatus
    }
    class HttpSimulationGateway
    class RunCoordinator {
        +start_run() RunStatus
        +execute() void
        +cancel_run() RunStatus
    }
    class Workspace {
        +id
        +revision
        +task_sets
        +runs
    }
    class TaskSet {
        +spec
        +tasks
        +content_hash
    }
    class ConcreteScenario {
        +settings
        +model
        +execution_seed
    }
    class RunStatus {
        +state
        +outcomes
        +job_id
    }
    class OutcomeSummary {
        +scenario
        +status
        +cursor
        +cached
    }
    class RunRecord {
        +status
        +task_set
        +results
        +service_indices
    }
    WorkspaceStore <|.. InMemoryWorkspaceStore
    SimulationGateway <|.. HttpSimulationGateway
    RunCoordinator --> WorkspaceStore : reads and updates
    RunCoordinator --> SimulationGateway : submits and polls
    InMemoryWorkspaceStore o-- Workspace : retains
    InMemoryWorkspaceStore o-- RunRecord : retains
    Workspace o-- TaskSet
    Workspace o-- RunStatus
    RunRecord --> RunStatus
    RunRecord --> TaskSet
    RunStatus o-- OutcomeSummary
    OutcomeSummary --> ConcreteScenario
```

`WorkspaceStore` and `SimulationGateway` are Python protocols, so implementations
can be replaced without changing the coordinator. `ConcreteScenario.model` is
the service wire model, built from the editor's `ModelSettings`.

## Simulation service: job execution

```mermaid
sequenceDiagram
    participant App as Application gateway
    participant API as Service API
    participant Store as JobStorage
    participant Scheduler as ModelScheduler
    participant Worker as Worker subprocess

    App->>API: POST /v1/simulation-jobs
    API->>Store: reserve(models, submission_id, fingerprint)
    Store-->>API: Job ID
    API->>Scheduler: submit(job_id, request)
    API-->>App: 202 JobAccepted
    loop Each model within job and worker limits
        Scheduler->>Store: start_model(job_id, index)
        Scheduler->>Worker: Launch with one model and shared tasks
        Worker->>Worker: Decode, simulate, encode
        Worker-->>Scheduler: ResultData or ModelError
        Scheduler->>Store: finish_model(job_id, index, outcome)
    end
    loop While waiting for completion
        App->>API: GET job status and outcomes?after=cursor
        API->>Store: status() and page()
        Store-->>App: Status and ordered outcome page
    end
```

The scheduler limits active jobs and model workers, queues excess accepted jobs,
and applies a per-model timeout. Submission IDs make retries idempotent when the
payload matches. The outcome cursor lets clients request only newer results.

## Simulation service: principal classes

```mermaid
classDiagram
    class JobStorage {
        <<interface>>
        +reserve()
        +status() JobStatus
        +page() OutcomePage
        +start_model() bool
        +finish_model() void
        +cancel() void
    }
    class InMemoryJobStore {
        +jobs
        +submissions
    }
    class ModelScheduler {
        +submit() void
        +cancel() void
    }
    class JobRequest {
        +tasks
        +models
        +model_seeds
        +submission_id
    }
    class JobStatus {
        +job_id
        +status
    }
    class OutcomePage {
        +outcomes
        +next_cursor
    }
    class OutcomeData {
        +model_index
        +status
        +result
        +error
    }
    class ResultData {
        +model_index
        +summary_result
        +metadata
    }
    JobStorage <|.. InMemoryJobStore
    ModelScheduler --> JobStorage : records outcomes
    ModelScheduler ..> JobRequest : schedules models
    JobStorage ..> JobStatus : reports
    JobStorage ..> OutcomePage : reports
    OutcomePage o-- OutcomeData
    OutcomeData --> ResultData : optional success
```

`service/worker.py` is the subprocess entry point. `service/codec.py` translates
wire models to simulation objects and translates completed results back to wire
data. Each worker receives one model, even when a job requests many models.

## Simulation engine: principal classes

```mermaid
classDiagram
    class Simulation {
        +execute(model, tasks, policy) SimulationResult
    }
    class Model {
        +developer_team
        +qa_testers
        +toolchain_pool
        +deployment_cadence
        +support_interval
    }
    class SimulationPolicy {
        <<abstract>>
        +task_priority()
        +support_assignment_strategy()
    }
    class DefaultSimulationPolicy
    class SDLCWorkflow {
        +start()
    }
    class SupportWorkflow {
        +start()
    }
    class ResourceOperator {
        +start()
        +stop()
    }
    class PoolManager {
        +request()
        +release()
    }
    class TaskStore
    class Task {
        +initial_value
        +story_points
        +depreciation_rate
        +history
    }
    class TaskHistory {
        +events
        +delivered_value
    }
    class TaskEvent {
        +event
        +status
        +loss
        +duration
    }
    class Resource {
        <<abstract>>
        +operate()
    }
    class Developer
    class QATester
    class Toolchain
    class ResourcePool
    class SimulationResult {
        +summary_result
        +metadata
    }
    SimulationPolicy <|-- DefaultSimulationPolicy
    Resource <|-- Developer
    Resource <|-- QATester
    Resource <|-- Toolchain
    Simulation --> Model : executes
    Simulation --> SDLCWorkflow : starts
    Simulation --> SupportWorkflow : starts optionally
    Simulation --> SimulationPolicy : uses
    Simulation --> SimulationResult : produces
    Model o-- Developer
    Model o-- ResourcePool : QA or toolchain
    SDLCWorkflow --> ResourceOperator : starts three
    SDLCWorkflow --> TaskStore : moves tasks
    ResourceOperator --> PoolManager : allocates resources
    PoolManager --> Resource : selects
    Task *-- TaskHistory
    TaskHistory o-- TaskEvent
```

`Simulation.execute()` creates a fresh SimPy environment for a model. Its
workflow creates development, QA, and deployment operators, then waits for all
original development tasks to reach delivery. Support work can interrupt
developers without increasing that delivery target.

## Task flow inside one simulation

```mermaid
flowchart LR
    Pending[Pending development] --> Dev[Developer]
    Dev -->|Development task| Developed[Awaiting QA]
    Developed --> QA[QA tester]
    QA -->|Pass| QAComplete[Awaiting deployment]
    QA -->|Fail and rework| Pending
    QAComplete --> Deploy[Toolchain at deployment window]
    Deploy -->|Success| Delivered[Delivered]
    Deploy -->|Failure and retry| QAComplete
    Support[Generated support task] --> Pending
    Dev -->|Support task| SupportDone[Support complete]
```

The queued boxes correspond to `TaskStore` instances in `SDLCWorkflow`. The
three work boxes are `ResourceOperator` stages using `Developer`, `QATester`,
and `Toolchain`. Task events and resource tracking feed summary, stage loss,
utilization, and backlog views after the simulation completes.
