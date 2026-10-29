# SQLite persistence validation

## Milestone 1 — database foundation

Validated on 2026-10-28 with Python 3.11.11 and SQLite 3.54.0. This milestone implements shared infrastructure only. Application/job adapters, server integration, bundled examples, and browser import/view behavior belong to later milestones.

The baseline application/service/client/integration tests passed before changes: 58 tests and 4 subtests. The final repository run includes 42 new foundation tests:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src/value_stream \
  --cov-report=xml --cov-report=term-missing \
  --cov-report=json:/private/tmp/value-stream-full-coverage.json tests -q
```

Result: **221 tests and 60 subtests passed in 13.26 seconds**. The six warnings concern existing Pydantic enum serialization and pandas deprecations. `coverage.xml` was generated.

| New module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `config.py` | 44 / 44 | 100% |
| `database.py` | 276 / 288 | 95.83% |
| `errors.py` | 15 / 15 | 100% |
| `migrations.py` | 33 / 33 | 100% |
| `payloads.py` | 104 / 104 | 100% |
| Foundation total | 472 / 484 | 97.52% |

The empty package initializer has no executable statements. Whole-package coverage is 94%; every new nonempty module exceeds the required 90%.

The tests demonstrate:

- Lazy configuration, argument/environment precedence, distinct service paths, and restrictive permissions on newly created files/directories.
- Exact staged copies of manifest-verified samples, preserved record IDs, empty initialization only for missing resources, and rejection of invalid bundles without publishing a target.
- Same-process and independent-process ownership contention, plus serialized transactions and closing from another thread.
- Read-only preflight, rejection of wrong-kind/future-version/malformed databases and payloads, and preservation of unexpected unversioned databases, including names resembling SQLite internal tables.
- Verified backups containing committed WAL data, independent rollback-journal backup files, and failure before migration when backup creation/verification fails.
- Complete rollback of multiple schema migrations, their version update, and invalid payload rewrites, retaining the original data and verified backup.
- Process exit through `os._exit(0)` after committing a WAL outcome; reopening reads that committed data rather than ignoring the WAL.
- Payload defaults, sequential upgrades, stable UUIDs, rejected nonfinite numbers/duplicate JSON keys, and safe public diagnostics.

Checks completed without diagnostics:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache uv lock --check
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache uv run python -m black --check \
  src/value_stream/service/persistence tests/unit/service/persistence
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache uv run python -m pylint \
  src/value_stream/service/persistence --persistent=n --score=n
git diff --check
```

No personal databases, generated sample snapshots, or runtime integration changes are included in this milestone. Tests create their databases in temporary directories and close their connections and workers during cleanup.

## Milestone 1 typing follow-up

Standard-mode Pyright initially reproduced 35 errors in the nine Milestone 1 Python files. These included argument-type mismatches at constructor, resource, nullable backup, and raw persisted-value boundaries, plus model-field access through general `BaseModel` results.

All function/method/test-helper signatures now have parameter and return annotations. Constructors explicitly accept their supported string inputs and retain normalized enum/path fields. Persisted payload values are validated from `object` and narrowed with a type guard. Tests narrow optional backups and decoded model types, use typed manifests/options/callbacks, and model invalid callback returns through an intentional test double. No diagnostic suppressions, ignore directives, or casts were added.

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
uv run pyright --project .agent/pyright-persistence.json
```

Result: **0 errors, 0 warnings, 0 informations** across all nine files, using locked Pyright 1.1.414. The configuration matches workspace `standard` mode and additionally requires parameter annotations and generic arguments. Future milestones must expand its checked files and pass this gate without suppressions before completion.

The complete repository suite was rerun after the typing changes with the pytest command in the first section, writing JSON to `/private/tmp/value-stream-typed-coverage.json`: **221 tests and 60 subtests passed in 14.17 seconds**, with the same six existing warnings and `coverage.xml` generated.

| Current module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `config.py` | 45 / 45 | 100% |
| `database.py` | 277 / 289 | 95.85% |
| `errors.py` | 15 / 15 | 100% |
| `migrations.py` | 35 / 35 | 100% |
| `payloads.py` | 104 / 104 | 100% |
| Foundation total | 476 / 488 | 97.54% |

Black, Pylint, `uv lock --check`, and whitespace checks passed after the type changes. The only additional dependency for this follow-up is the development checker and its Node environment helper; runtime dependencies are unchanged.

## Milestone 2 — durable workspace operations

The application adapter now stores editor state, frozen task sets, runs, outcome summaries, and immutable result blobs in application schema version 2. Version-one databases migrate through the verified-backup mechanism. `WorkspaceOperations` shares admission, comparison, and completion rules between the memory and SQLite adapters; SQLite performs normalized row operations and does not maintain a dumped memory mirror.

`get()` and `run()` return detached snapshots. The coordinator uses `patch_run()` and `complete_outcomes()` for accepted job IDs, cancellation, supersession, retry state, outcomes, cursors, reservations, and final comparison pointers. The old `retain_result()` and `finish()` operations were removed. Saved comparisons are retained until explicit deletion; count/byte limits reject additional work without pruning them. Both adapters use the same canonical logical input-byte budget, independent of result blobs and outstanding reservations.

Final validation command:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src/value_stream \
  --cov-report=xml --cov-report=term-missing \
  --cov-report=json:/private/tmp/value-stream-m2-full-coverage.json tests -q
```

Result: **250 tests and 82 subtests passed in 17.03 seconds**. Whole-package coverage is **95.51%**, rounded to 96%. `coverage.xml` was generated. The five warnings are existing pandas deprecations in viewer code.

| Milestone 2 production module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `app/storage.py` | 449 / 453 | 99.12% |
| `app/sqlite_storage.py` | 156 / 161 | 96.89% |
| `app/coordinator.py` | 157 / 165 | 95.15% |
| Combined | 762 / 779 | 97.82% |

The foundation modules retain their passing coverage gates. Protocol declaration ellipses are excluded by coverage.py's default handling; no custom coverage exclusions were added.

Evidence includes:

- A common adapter contract suite verifies detached snapshots, cold reopen, request deduplication before admission, stale-preview rejection inside the transaction, exact input-budget parity, result limits, and persistent UTC timestamps.
- Real fault injection after writes to a run proves result insertion, references, cursor allocation, reservations, and the upstream checkpoint roll back together. Replaying a committed page neither duplicates cursors nor consumes the reservation twice. Model completion order can differ from scenario order.
- Malformed, incomplete, unordered, or conflicting pages cannot advance the service cursor. Final failures preserve successes already committed, and late patches cannot revive a terminal run.
- Deleting one comparison preserves results shared by another. Pending cached comparisons protect their promised result references. Cached summaries describe the immutable retained payload, including when a caller supplies a changed copy.
- Full history and lowered limits preserve existing reads and exports. Pin, unpin, baseline restoration, task-set deletion, and explicit workspace deletion retain their revision and ownership checks.
- Controlled lifecycle tests cover retry/resume, immediate resume after a pause, supersession, lost jobs, malformed service responses, unexpected failures, and cancellation while upstream submission is awaiting acceptance.
- The HTTP integration test executes real models, closes the application store, reads the same raw result in a separate Python process, and reopens the API with an offline gateway. Metrics and summary/event/resource CSV exports are unchanged; a matching request still returns the original run without resubmission.

The type-check include list now covers all **16** Python files created or changed through Milestone 2, retaining all Milestone 1 entries. All signatures are annotated, and no type-ignore directives or casts were added. The expanded standard-mode gate reports **0 errors, 0 warnings, 0 informations**:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
uv run pyright --project .agent/pyright-persistence.json
```

Black checks all seven Milestone 2 Python files, and `git diff --check` passes. Error-level Pylint passes:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache uv run python -m pylint \
  src/value_stream/app/storage.py src/value_stream/app/sqlite_storage.py \
  src/value_stream/app/coordinator.py --persistent=n --score=n --errors-only
```

The full non-blocking Pylint run still suggests complexity improvements for the data transfer classes and coordinator. No lint suppression was added.

No startup flags, default database selection, simulation job persistence/recovery, or bundled samples are introduced by this milestone. `create_app(store=SqliteWorkspaceStore(config, settings))` supports explicit injection now; callers close the adapter. Default startup and lifespan ownership are implemented in Milestone 4. All test databases and child processes are temporary and task-owned.

## Milestone 3 — durable simulation jobs and interruption recovery

`service/persistence/job_store.py` adds simulation schema version 2 with jobs, indexed model outcomes, and cascading idempotent submission mappings. JSON versions are independent of schema versions. Read-only preflight validates payloads and relational model identities, outcome cursors, terminal state, and byte counters. `JobOperations` shares transitions across both adapters using detached snapshots; SQLite does not retain a memory mirror. Status polling reads relational counters, and paging decodes only outcomes after the supplied cursor.

The adapter constructor acquires ownership and completes recovery before TTL pruning or scheduler construction. Recovery preserves committed successes/errors, appends `JOB_INTERRUPTED` failures in unfinished model-index order, and never launches workers. Terminal timestamps are UTC epoch values in both adapters. Service shutdown closes scheduling, commits interruptions, terminates and joins workers outside database transactions, and then closes the injected store. User-cancelled jobs remain cancelled.

Final validation:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src/value_stream --cov-report=xml \
  --cov-report=json:/private/tmp/value-stream-m3-full-coverage.json tests -q
```

Result: **265 tests and 94 subtests passed in 18.55 seconds**, with five existing pandas warnings. Package line coverage is **96.29%**. `coverage.xml` was generated.

| Milestone 3 production module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `service/job_store.py` | 162 / 163 | 99.39% |
| `service/persistence/job_store.py` | 176 / 181 | 97.24% |
| `service/scheduler.py` | 132 / 135 | 97.78% |
| `service/app.py` | 115 / 126 | 91.27% |

All prior persistence/recovery modules continue to exceed their 90% gates. No custom coverage exclusions were added.

The new tests in `tests/unit/service/test_sqlite_job_store.py` and `test_scheduler.py` provide these checks:

- Both adapters handle ordered paging, detached responses, duplicate completions, cancellation preserving successes, concurrent completions and cancellation races, indexed failures, capacity, and matching/conflicting submission retries.
- A child process commits one successful result and one error, starts another model, then exits with `os._exit(23)` without closing SQLite. The next owner reads the identical successful result and original error, appends exactly two interruption failures, and preserves the same page after another reopen. Worker launch is patched to fail throughout recovery, proving no resubmission.
- Restart tests retain an out-of-order completed result, finalize queued and running models, and preserve submission mappings at full capacity. Patched UTC timestamps prove TTL starts when recovery makes the job terminal; later expiry cascades the mapping and permits a new submission with that ID.
- Faults injected after actual SQL writes prove counters, byte usage, outcomes, and cursors roll back together. A failed startup recovery leaves the prior cursor intact and releases ownership so the next owner can recover once.
- A real version-one database migrates with a verified backup. Inconsistent relational counters/state and unsupported future payload versions stop opening without replacing the file.
- Real model subprocesses complete through the HTTP API with either store. A reopened SQLite-backed service returns the identical page and resolves a submission retry without invoking the scheduler. A separate shutdown case stops an active real worker, retains earlier success, and releases ownership only after the worker has joined.
- Worker regressions cover timeout/kill escalation, launch failure, nonzero exit, oversized output, malformed output, incorrect model indexes, queue skipping, and closed scheduler rejection. Invalid worker results are cleared before recording a `WORKER_FAILED` outcome.

The expanded gate checks **23 Python files**, with complete function signatures and no ignores or casts:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
uv run pyright --project .agent/pyright-persistence.json
```

Result: **0 errors, 0 warnings, 0 informations**. Black checks all seven changed/new Python files; error-level Pylint on the four production modules and `git diff --check` pass.

Default factory/database selection, lazy lifespan startup, and application reconnection remain Milestone 4. This milestone supports explicit `create_app(store=SqliteJobStore(config, settings))`; service lifespan closes the injected store. Direct scheduler callers close their store after joining through `scheduler.close()`. All test databases and processes are temporary and task-owned.

## Milestone 4 — default SQLite lifecycle and application recovery

Both service factories now open their default SQLite adapter during FastAPI lifespan. Construction, imports, OpenAPI generation, and CLI help acquire no databases, locks, schedulers, or workers. Injected stores bypass path resolution and participate in recovery and cleanup. Application flags are `--database`, `--data-dir`, and `--service-database`; the standalone `python -m value_stream.service` supports `--database`, `--data-dir`, `--host`, and `--port`. Environment equivalents remain separate from the numeric application limits.

The local-service singleton records its resolved database identity, preserves reference counting, and rejects a different requested database while owned. Its constructor creates no database. Startup failures propagate an actionable diagnostic without leaking an unhandled Uvicorn thread exit. A failed owned service leaves retained application data available with readiness false; a failed application database stops startup. Nested cleanup closes stores even if gateway or scheduler initialization/shutdown fails.

Runs persist upstream kind and identity before submission. Matching external jobs recover by polling their saved job ID/cursor, without constructing a new request or submitting again. Changed identities receive `SERVICE_CHANGED`; missing durable acknowledgements receive `RUN_INTERRUPTED`; expired jobs receive `SERVICE_JOB_LOST` for unfinished outcomes. External application shutdown detaches polling without cancellation. Local shutdown drains committed outcomes and marks interrupted work failed, preserving explicit user cancellation. A five-second timeout retains the last checkpoint for the next startup.

Final Python validation:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src/value_stream --cov-report=xml \
  --cov-report=json:/private/tmp/value-stream-m4-full-coverage.json tests -q
```

Result: **283 tests and 94 subtests passed in 22.95 seconds**, with five existing pandas warnings. Whole-package line coverage is **97.03%**; `coverage.xml` was generated.

| Milestone 4 production module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `app/coordinator.py` | 199 / 205 | 97.07% |
| `app/gateway.py` | 95 / 95 | 100% |
| `app/server.py` | 184 / 202 | 91.09% |
| `app/exports.py` | 41 / 42 | 97.62% |
| `app/__main__.py` | 17 / 18 | 94.44% |
| `service/app.py` | 136 / 147 | 92.52% |
| `service/__main__.py` | 13 / 14 | 92.86% |
| `client/web/local_service.py` | 76 / 83 | 91.57% |
| `service/job_store.py` | 166 / 167 | 99.40% |
| `service/persistence/job_store.py` | 169 / 173 | 97.69% |

Prior persistence/recovery modules retain their gates. No custom coverage exclusions or diagnostic suppressions were added. The expanded Pyright configuration checks **33 files** with **0 errors, 0 warnings, 0 informations**; an AST check confirms all function signatures are annotated. Black checks all 16 affected Python files, error-level Pylint passes for all ten production modules, and whitespace checks pass.

`tests/integration/test_startup_recovery.py` adds 18 tests covering these behaviors:

- A real external HTTP job is acknowledged before application shutdown. Worker execution is gated until the application has stopped, then completes while it is down. A fresh application owner restores both outcomes with cursors 1 and 2, one saved run, and usable exports. Scheduler spies reject any resubmission or shutdown cancellation.
- A partially completed external job preserves its first saved outcome and cursor across application-store close/reopen; later completions appear once, without reordering or duplicate checkpoints.
- Owned-local startup opens a partially completed simulation database, retains the committed success, drains all three outcomes, and maps remaining work to `RUN_INTERRUPTED`. Worker launch is patched to fail during this recovery, proving no execution is restarted.
- Unknown acknowledgement, changed endpoint, expired job, disconnected/paused polling, saved cancellation, shutdown while awaiting acceptance, local successful-page draining, unavailable service, and shutdown timeout retain the required state. Timeout tests verify the five-second budget and no falsely advanced cursor.
- Temporary explicit/default paths, repeated lifespans, injected stores with invalid ignored database environment values, CLI forwarding, separate files, singleton identity, second-owner rejection, corrupt initialization, failed scheduler initialization, and failed gateway close preserve resource ownership and cleanup.
- Subprocess checks import both services, construct OpenAPI, and invoke both CLI help commands while prohibiting thread/executor/worker startup. The selected data directory remains absent.

Frontend validation from `src/value_stream/app/frontend`:

```bash
npm run build
npm run typecheck
npm run test -- --run
npm run test:e2e
```

The build and type checks pass, **all 3 Vitest tests pass**, and **all 3 Playwright cases pass in 39.8 seconds**: real simulations/cache/exports/refresh/charts/accessibility, invalid-input contracts, and incremental results with cancellation. Chromium launch was blocked by macOS Mach-port permissions inside the sandbox; the authorized run outside it passes. The browser server now uses `tests/browser_server.py` with temporary database configuration, graceful SIGTERM, and cleanup after Uvicorn replays that signal. Pytest's autouse fixture likewise isolates default database resolution from all developer data. HTTP contract snapshots remain unchanged.

`docs/studio-workspace.md` now documents persistent locations, flags, service ownership, external reconnection, and unacknowledged external jobs surviving until service expiry. Sample generation/import, exact documentation views, packaging/distribution, and final CI/documentation work remain Milestones 5 and 6.

A repeat browser run exposed a 100-scenario cancellation timeout caused by SQL transitions decoding all previously retained results. The fix keeps `last_cursor` separate from pending outcome objects, reads only relational state/counters for transitions, and appends only new outcome JSON. A unit regression guard prohibits historical payload deserialization during completion, cancellation, and interruption. The final browser run passes the unchanged stress test; no schema/wire change or increased test timeout was needed. A post-run directory check confirms no `value-stream-browser-*` temporary directories remain. The UI retention label now says workspaces are saved until deleted.

## Milestone 5 — completed examples, explicit import, and exact views

The release `readme-v1` contains a 44,957,696-byte application snapshot and a 45,056-byte empty simulation snapshot. The application has one fixed workspace, one 500-task set, and two completed nine-scenario runs. All eighteen model executions ran through actual worker subprocesses with explicit model seeds; no numerical result was invented. The generator and frozen `src/examples/sample_spec.json` retain full explicit inputs, while the manifest records model/task settings, seeds, namespace, and engine/generator provenance. Resource UUID metadata need not reproduce byte-for-byte.

Verified SHA-256 hashes:

| Snapshot | SHA-256 |
| --- | --- |
| `application.sqlite3` | `8ed01093085fd8245d7d5b10c5b4f301b0d02b9796e6e47d2b935c647f4be238` |
| `simulation.sqlite3` | `6053186c2e3102f42e41ce534e6ffe34e917238a9b12238941fa53b7e8021fcc` |

The snapshots are checkpointed in DELETE journal mode, pass integrity/foreign-key checks, and have no required sidecars. The builder refuses existing output files. It removes orphan SHM files only from its private, closed, successfully checkpointed output. No user database was used to generate these files.

Stable identities verified through import and browser restoration:

- Workspace: `9e9c2f69-a5fd-5849-9f63-0469d1a5d465`.
- Baseline: `4d84ad6d-7702-51c4-ab3a-514d9da20832`.
- Efficiency comparison: `a94806f2-de2d-519d-82d3-105cdef32a19`.
- Small-team detail: `37e637a5-0fe7-528a-95b1-9faba07d22ac`.
- Large-team detail: `a193bc90-db6a-52e0-8bc7-2c1e8e0a2157`.

The manifest has nine views covering both comparisons, deployment intervals, and both detail extremes across stage loss, utilization, and backlog. `GET /api/v1/examples` exposes only release/name/slug/relative URL, filtering references that users delete. The UI links to the README baseline, and README sections link to the exact manifest views. Explicit URLs preserve comparison order, the owning run/scenario pair, chart tab, and unrelated parameters through polling, refresh, and back/forward. Historical task-set views leave editor state unchanged and disable incompatible actions. Export defaults to the URL-selected comparison.

`python -m value_stream.app.sample_import --database PATH [--source PATH]` is the offline import interface. Source kind/schema/payloads, checksum for the default bundle, relationships, bounds, IDs, cursors, and result/scenario models are validated before target creation. Supported payloads and byte counters are normalized in memory. Imports add complete missing workspace aggregates in one transaction, preserve existing records, treat identical content as unchanged, and skip whole conflicting aggregates. Shared result keys require matching content and provenance. Source files remain unchanged. CLI statuses are 0 for success/no-op, 2 for conflicts, and 1 for failure. An intentional SQL failure after insertion proves rollback; malformed sources do not create a target.

Final Python command:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src --cov-report=xml \
  --cov-report=json:/private/tmp/value-stream-m5-final-coverage.json tests -q
```

Result: **293 tests and 101 subtests pass in 41.69 seconds**. `coverage.xml` is generated. Five existing pandas deprecation warnings remain. Library coverage is **4462/4600 lines, 97.00%**; the command also measures the sample builder under `src/examples`.

| Milestone 5 persistence module | Covered executable lines | Coverage |
| --- | ---: | ---: |
| `src/examples/build_sample_databases.py` | 110 / 115 | 95.65% |
| `app/sample_import.py` | 203 / 209 | 97.13% |
| `app/examples.py` | 29 / 31 | 93.55% |
| `app/storage.py` | 451 / 455 | 99.12% |
| `app/server.py` | 187 / 206 | 90.78% |

All prior persistence/recovery gates remain passing. The standard-mode Pyright gate covers **39 files** and reports **0 errors, 0 warnings, 0 informations**. An AST check confirms complete function signatures. No type-ignore directives, casts, or coverage exclusions were added. Black checks all eight affected Python files; error-level Pylint and whitespace checks pass. Application OpenAPI and generated TypeScript were regenerated; existing contract tests pass.

Frontend validation passes `npm run build` and **15 Vitest tests** across editor, parser, and app-selection cases. Browser validation from `src/value_stream/app/frontend`:

```bash
VALUE_STREAM_TEST_PORT=18181 VALUE_STREAM_RESTART_TEST_PORT=18182 npm run test:e2e
```

All **13 Playwright cases pass in 2.2 minutes**, including nine manifest URLs opened in fresh contexts, nonempty Plotly traces, exact detail/tab selection, exports, reload, and every URL reopened after a real server stop/start against the same separate data directory. No link submits a simulation. Historical editing remains disabled without changing the current saved task set; invalid/deleted IDs show unavailable views, and deleted examples disappear from discovery. The existing simulation/cancellation browser cases also pass.

A final focused run of the efficiency/small-team cases passes **2 cases in 16.5 seconds** after checking reversed legend ordering, preservation of a scoped scenario when another comparison is added, clearing it when its owning run is removed, and the URL-selected export. Browser runs use authorized execution outside the sandbox because macOS blocks Chromium startup inside it. Ports 18181/18182 avoid an unrelated server already using the default test port; no unrelated process was stopped. Post-run checks find no browser/restart temporary directories or owned servers.

Visually reviewed screenshots with actual plot data: [efficiency comparison](efficiency-11.png) and [small-team detail](small-team.png). README plot images were not replaced. Sample packaging declarations, installed-wheel/container checks, final operational documentation, and CI gates remain Milestone 6.

## Milestone 6 — distributions, installed packages, volumes, and CI

All six milestones are complete. Both Hatchling targets explicitly include the two
published snapshots, their manifest, and compiled UI assets, while excluding frontend
source. Compiled assets in the sdist allow a wheel rebuild without Node. Runtime
SQLite files, journals, locks, backups, and staging files are ignored; exact exceptions
keep the two published snapshots tracked. Container build contexts exclude runtime
data and host-built UI assets. Both images default `VALUE_STREAM_DATA_DIR=/data`,
declare that volume, and keep one worker per service.

`docs/persistence.md` is the operator guide for path precedence, bundled/empty startup,
ownership, retention, migrations/backups, restoration, import conflicts, mutable links,
external recovery limits, and volume commands. README, studio documentation,
architecture, and both component specifications now agree with the durable behavior;
single-user scope, authentication deferral, extensibility, and ExecPlan requirements
remain intact.

Final regression command:

```bash
UV_CACHE_DIR=/private/tmp/value-stream-uv-cache \
MPLCONFIGDIR=/private/tmp/value-stream-mpl \
uv run pytest -o addopts='' --cov=src --cov-report=xml \
  --cov-report=json:/private/tmp/value-stream-m6-coverage.json tests -q
uv run python scripts/check_persistence_coverage.py /private/tmp/value-stream-m6-coverage.json
uv run pyright --project .agent/pyright-persistence.json
```

Result: **297 tests and 101 subtests pass in 46.96 seconds**, with five existing pandas
warnings. `coverage.xml` is generated. Library coverage is **4463/4600 lines, 97.02%**.
All **17** gated modules pass the 90% requirement; percentages range from **90.78% to
100%**. Infrastructure discovery is recursive and automatically includes executable
new modules; missing report entries fail. New gate tests cover exact/below-threshold
coverage, missing modules, nested additions, corrupt samples, incomplete archives,
and read-only cleanup. No coverage exclusions were added.

Pyright checks **45 files**, with **0 errors, 0 warnings, 0 informations**. An AST check
confirms complete signatures. Black, error-level Pylint, `uv lock --check`, regenerated
OpenAPI/TypeScript equality, and `git diff --check` pass. No type suppressions were
introduced. The existing frontend unit/URL and fresh-browser/restart tests remain in
the frontend CI job; no frontend logic changed in this milestone.

### Actual archive inventory

```bash
uv build --sdist --wheel --out-dir /private/tmp/value-stream-m6-dist
uv run python scripts/verify_distributions.py \
  --wheel /private/tmp/value-stream-m6-dist/value_stream-0.1.25-py3-none-any.whl \
  --sdist /private/tmp/value-stream-m6-dist/value_stream-0.1.25.tar.gz
```

| Artifact | Measured size | Verified contents |
| --- | ---: | --- |
| `value_stream-0.1.25-py3-none-any.whl` | 3,553,994 bytes | Both snapshots, manifest, compiled index/assets; no frontend source |
| `value_stream-0.1.25.tar.gz` | 8,399,307 bytes | Both snapshots, manifest, compiled assets; no frontend source |

Both archives verify release `readme-v1`, all **9** views, sample checksums/integrity,
frozen IDs/specs, result provenance, and referenced rows. This validation never runs
README models. A separate `uv build SDIST --wheel --out-dir
/private/tmp/value-stream-m6-sdist-wheel` succeeds, and the resulting wheel passes the
same archive validation. Sample hashes remain the exact values recorded in Milestone 5.

### Installed read-only wheel

```bash
uv run python scripts/verify_installed.py \
  /private/tmp/value-stream-m6-dist/value_stream-0.1.25-py3-none-any.whl
```

The actual wheel was installed with `uv pip --no-deps --target` into a task-owned
location outside the checkout. Installed files and directories were made read-only,
then restored for cleanup. Import/help/schema construction left the selected data
directory absent. Cold application lifespans copied the default snapshots into writable
data, retained a newly created workspace, and returned identical result CSV bytes.
A `Popen` guard prohibited model execution. The installed tree's full content
fingerprint stayed unchanged. A separate service-only process rejected application
imports, opened only its empty simulation database, and passed health/schema checks.

Measured identities and hash:

- Bundled workspace: `9e9c2f69-a5fd-5849-9f63-0469d1a5d465`.
- Bundled run: `4d84ad6d-7702-51c4-ab3a-514d9da20832`.
- New persisted user-test workspace: `3e4dba96-5d79-4d93-b8cd-56574c63cf8d`.
- Identical summary CSV SHA-256 before/after restart:
  `299de0554aefb5939acbdd7653184d89731abb34bc6d0c6f05911061cc1f1dd3`.

### Real container recreation

The user made a Docker daemon available after the initial check found none. Both
images built successfully. Docker Buildx needed an authorized run outside the sandbox
to write its metadata; no automatic-approval rejection remains.

```bash
docker build -t value-stream-service:codex-m6 -f Dockerfile .
docker build -t value-stream-application:codex-m6 -f Dockerfile.app .
uv run python scripts/verify_containers.py \
  --application-image value-stream-application:codex-m6 \
  --service-image value-stream-service:codex-m6
```

Image IDs:

- Application: `sha256:3a11ce3f3f009bd9a74ab1a9ff0859ceeff03ed316041666b885dfcc869dfa58`.
- Simulation service: `sha256:e4f43d5777f9acd0cf58e64b06fa76da9e1771a0a057d378596ac63bb36edad3`.

Each check starts with a unique named volume, executes an actual small simulation,
stops/removes the first container, and creates a replacement using that same volume.
A new application workspace/run and a service job survive; their output hashes match
exactly. Repeating the service submission returns its original job ID. The service
image has no Node executable and imports no application at service startup.

| Persisted item | Actual identifier/hash |
| --- | --- |
| New application workspace | `95266866-3655-4123-bd33-ca64750a8432` |
| New application run | `91cca97c-5b6f-4a31-b9bd-e6c9dc82daa8` |
| Application CSV SHA-256 | `23103ae94c95a85e1a7d620d3660844510e358e8d6a4a3171184064f52f80d2c` |
| Service job and retry target | `7cf7f5b5-91fc-4024-9f65-a6720d6578ce` |
| Service outcomes SHA-256 | `061a2e111f31469ade229e64a5bf3effd50f10b1b422cdd47c1ef07066db32e9` |

Finally-block cleanup and explicit Docker inventory checks confirm no task-owned
containers or volumes remain. No unrelated Docker resources or user databases were
removed. The two tagged images and build outputs remain reviewable artifacts.

CI now repeats per-file coverage, scoped types, frozen bundle validation, import/help
no-I/O behavior, real archive inventory, read-only installed-wheel restart, and real
container recreation. Coverage artifacts have distinct matrix names and are retained
on failures. GitHub's Python-version matrix was configured, not executed locally;
local Python checks used 3.11 and both Linux containers used 3.11. The full six-milestone
objective has no remaining implementation or acceptance work.
