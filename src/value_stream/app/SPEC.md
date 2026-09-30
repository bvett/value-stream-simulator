# Simulation web application specification

The implementation design and validation milestones are to be documented in `.agent/SIMULATION_APP_EXECPLAN.md`, maintained according to `.agent/PLANS.md`. This specification records the agreed behavior; the ExecPlan resolves version 1 implementation choices.

## Goals
- Create a standalone web application that provides a user interface to the API offered by `value_stream.service`.
- Provide insight on how model properties affect the loss of value for a delivered set of tasks.
- Identify the source(s) of loss within a simulation.
- Provide suggestions for reducing loss.

## Version 1 requirements

- Application source files belong under `src/value_stream/app`.

### Collect User Input

Create a set of tasks, given: task count, story points, initial value, and depreciation rate. Story points and initial value may be specified as constants or bounded uniform ranges. Initial value defaults to 1, and depreciation rate defaults to 0.005 (0.5% per simulation time unit). Use explicit time-unit labels. There is no separate complexity property; task effort is represented by `Task.story_points`.

Create one or more models.  Models may differ:
  - In the size and properties of developer teams, QA Tester pools, toolchain pools
  - In the properties of deployment cadence, support interval, support task story points
  - Developers within a team may differ in efficiency. Collect team size, minimum efficiency, maximum efficiency, and a linear or bounded normal distribution. Linear means evenly spaced values between the bounds; a one-person linear team uses the midpoint. Developer teams may differ between models.
  - For V1, QA testers are specified as a pooled resource.  Pool size and properties may differ between models.
  - For V1, the toolchain will be specified as a pooled resource with user-specified deployment duration and failure rate.

A job is a request to execute a simulation for every model, applying each to the same task set.  A task set may be reused across jobs and must remain consistent within a job.

Support both individually configured models and parameter sweeps across multiple properties. A sweep generates all combinations of selected values. Sweeps are the primary model-creation workflow; show the model count and validate limits before execution. Support duplicating and editing model definitions without repetitive entry.

Give every scenario a stable identity and a human-readable name. Freeze generated task sets and developer teams, and retain generation and execution seeds so reordering, repeating, or selectively rerunning scenarios does not change their numerical outcomes. Provide an explicit task-regeneration action.

Utilize best practices in UI design to guide the user and avoid repetitive data entry.

### Execute Simulation
- A set of tasks and one or more models are submitted to the web service for execution as a job.
- Provide progress updates and update plots as individual models finish. Streaming intermediate results from inside a running model is not required.
- Cancellation stops the whole job and preserves already completed results. Individual model failures do not prevent other models from completing.

### Plot Results

- Render results using plots similar to those implemented in `src/value_stream/client/views/metadata_viewer.py` and `result_viewer.py`, including:
  - Loss vs. Cadence
  - Loss vs. Team Size
  - Mean Stage Loss
  - Resource Utilization
  - Resource Backlog (the existing Resource Capacity view)

- Plots are updated in realtime as results are returned by the simulation while it is executed.
- Support switching between plots via labeled, keyboard-accessible tabs.
- Support pan, zoom, and reset zoom, with consistent scenario colors and accessible alternatives to plot-only information.
- Display value lost as a positive percentage, with lower values better. Overall value lost is `100 * (initial value - delivered value) / initial value`; show N/A when total initial value is zero. Explain the separate meaning of mean stage loss instead of presenting it as an additive breakdown of overall loss. Resource metric labels must accurately describe the telemetry available.
- For V1, preserve the resource metrics used by the current viewers. Explain that resource utilization shows recorded activity shares, not a precise measure of total capacity utilization, and that backlog counts resource requests, which can contain task batches. Expanded simulation telemetry is deferred.

- Support an interactive mode after a job is executed. Retain the baseline and add the latest interactive comparison, with a Pin comparison action to retain additional comparisons. For example, a team-size sweep produces one series at a fixed cadence; changing cadence produces another series using the same task set and the same teams for each size. This provides an alternative to sweeping cadence in advance. Commit slider changes on release, replace unfinished interactive work when superseded, reuse unchanged results, and keep prior plots visible while updating. Baseline and pinned comparisons remain immutable.

- Errors are handled gracefully.  When possible, continue if there is an error while executing the simulation, presenting the user with relevant details.

- Support separate CSV exports for model summaries, stage events, and resource history, with scenario identities and relevant configuration/seed provenance.
- Provide explainable, rule-based observations and suggestions for reducing loss, with an explicit action to test a suggested change. Distinguish observed evidence from an untested hypothesis. Automatic optimization and machine learning are deferred.

### Other Requirements

- Put storage behind a replaceable interface, using an in-memory implementation for V1. Application life means the life of the server: browser refreshes retain task sets, model definitions, and retained comparisons. Document configurable retention limits; state need not survive server shutdown.
- Include unit and integration tests
- Handle invalid input, execution failures, and connection failures with a documented error contract.
- Provide an option to package and run the application as a Docker image, and support local standalone startup from the command line.
- Add configurable protections against excessive resource use, including admission and execution limits. Select initial defaults during design and document their errors in the API contract.
- Provide single startup of web application and simulation service, with UI and application API on one browser origin. Also permit an explicitly configured simulation service endpoint.
- User interface design must be clean, modern, and self-describing.



## Intended use and future scope

Version 1 is for individuals demonstrating the value-stream project and runs as a single server instance. Horizontal scaling, shared multi-user deployment, authentication, policy extensibility, service discovery, persistent results, and machine-learning optimization are later phases. Keep storage, job coordination, and simulation execution separable, with stable identifiers, to allow future shared storage and distributed workers. V1 does not implement distributed infrastructure or claim multi-instance support.

## Implementation design prerequisites

- Write an ExecPlan for this significant feature before coding, following `.agent/PLANS.md` as required by `AGENTS.md`.
