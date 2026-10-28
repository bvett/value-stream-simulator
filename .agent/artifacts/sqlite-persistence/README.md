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
