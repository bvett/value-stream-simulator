# SQLite persistence and operation

The application service retains workspaces, inputs, comparisons, and results until
explicit deletion. The simulation service retains execution jobs separately, with
a default terminal-job lifetime of one hour. Both use SQLite by default; memory
adapters remain available for isolated tests. The agreed product requirements are
in [the SQLite specification](specifications/sqlite.md).

## Locations and startup

Each service owns one file: `application.sqlite3` or `simulation.sqlite3`. Resolve
its location in this order:

1. An explicit factory/CLI database filename (`--database`, or the application's
   `--service-database` for its owned local simulation service).
2. `VALUE_STREAM_APP_DATABASE` or `VALUE_STREAM_SERVICE_DATABASE`, respectively.
3. The component filename within an explicit `--data-dir`/factory `data_dir`,
   `VALUE_STREAM_DATA_DIR`, or the platform's user data directory for `value-stream`.

An explicit filename that does not exist creates an empty initialized database.
A default filename starts from an exact verified copy of its bundled snapshot,
preserving all IDs. If no bundle exists, it starts empty. Existing databases are
never replaced by bundled data. Installed resources are read-only templates; all
runtime databases, journals, locks, and backups belong in the writable directory.
Paths are not part of the numeric `/api/v1/config` response.

```bash
python -m value_stream.app --data-dir /path/to/data
python -m value_stream.service --database /path/to/independent-jobs.sqlite3 --port 8080
```

The existing Uvicorn entry point `value_stream.service.app:app` also uses environment
configuration. Run one worker per service. Factories, imports, OpenAPI construction,
and CLI help acquire no databases or worker processes; opening and recovery occur
in FastAPI lifespan. A workspace initialization failure stops startup. An owned
simulation-service failure leaves retained application results available, with
readiness false and an actionable service error.

Each file permits one active owner, enforced by its operating-system lock. Another
owner fails with `DATABASE_IN_USE`. A leftover `.lock` filename does not mean the
file is still owned; do not delete a live owner's lock to bypass this protection.
Application and simulation paths must identify separate files. Local runners share
one reference-counted simulation service only when their resolved database identity
matches. A separate standalone service using the same default file must stop the
other owner, use a different filename, or be selected as an external service URL.
An explicit `--service-database` cannot configure an external service.

## Retention, restart, and recovery

Admission limits reject additional work instead of deleting saved application
history, including unpinned comparisons. Explicit workspace/comparison/task-set
deletion reclaims unreferenced result blobs. Temporary service jobs and their
submission IDs expire together after their terminal UTC timestamp; active jobs
are not pruned to make room. Stored timestamps remain meaningful after restart.

Completed outcomes survive restart. An owned simulation service finalizes queued
or running models with `JOB_INTERRUPTED`, preserving earlier successes and cursor
order; it never automatically reruns them. The application drains these outcomes
and reports `RUN_INTERRUPTED` for missing local work. Graceful local shutdown
requests cancellation, drains available results within five seconds, and preserves
explicit user cancellation intent. A timeout leaves the last committed checkpoint
recoverable rather than claiming uncommitted results.

When `--service-url` or `VALUE_STREAM_SERVICE_URL` selects an external service,
application shutdown stops polling without cancelling its jobs. Startup reconnects
to acknowledged jobs using saved cursors and any prior cancellation request. An
unavailable endpoint retries and eventually pauses, leaving saved data readable;
Resume restarts polling. A missing/expired job reports `SERVICE_JOB_LOST` for
unfinished outcomes. A changed configured service identity reports `SERVICE_CHANGED`
without contacting an endpoint taken from stored data. Local identity is the
resolved database path, not a changing loopback port.

A run without a durably recorded upstream job ID becomes `RUN_INTERRUPTED`; it is
not resubmitted automatically. An external service may retain an accepted but
unacknowledged job until expiry. Submission retries against the simulation service
remain idempotent across service restarts until that job expires.

## Migrations, backups, and failure handling

Schemas and JSON payloads have independent versions. Stable relational columns
hold identities, ownership, counters, states, and cursors; versioned JSON holds
evolving domain data. New optional properties use defaults. Incompatible payload
changes require explicit upgrades before validation. Results and processing cursors
commit atomically through explicit storage operations. There is no pickle loading,
SQL supplied by data, SQLite extension loading, or implicit shared-object saving.

Before a schema migration, the manager creates a verified SQLite backup beside the
original (`<database>.<unique suffix>.backup`). It verifies integrity, relationships,
versions, and row counts, then migrates transactionally. A migration failure rolls
back and stops startup, retaining the backup. Unsupported newer schemas/payloads,
corruption, permission failures, and ownership failures report errors without
replacing the file. New directories/files use restrictive permissions where supported;
existing user permissions are preserved.

Backups remain until explicitly removed and consume disk space. For a live backup,
use the owning adapter's `database.backup()` API. Do not copy only the main file
of a live WAL database. To restore, stop every owner, preserve the current main file
and its WAL/SHM files together for diagnosis, verify the chosen backup, then copy
that backup to the configured path. Never restore over a running owner. A failed
migration can be retried after fixing its cause; compatible current data is not
rewritten merely to open it.

## Bundled examples and explicit import

[README examples](../README.md#completed-readme-examples) include completed results
and exact workspace/comparison/scenario/chart links. Browser storage is unnecessary.
Historical views do not change current editor inputs. Examples can be edited or
deleted; doing so can change or break documentation links. Available examples are
listed by `GET /api/v1/examples`. Stored historical results retain their original
engine and generator provenance.

Stop the application owner before offline import:

```bash
python -m value_stream.app.sample_import --database /path/to/application.sqlite3
```

Omit `--database` for the normal path defaults; `--data-dir DIR` and `--source PATH`
are supported. Import validates the source read-only before destination creation,
then adds missing complete workspace aggregates in one transaction, preserving IDs
and existing records. Identical aggregates are unchanged. A conflicting existing ID
skips that entire workspace and reports the conflict; it never partially merges
results into edited inputs. Exit codes are 0 for success/no-op, 2 for conflicts,
and 1 for operational/validation failure. Explicitly delete a conflicting example
workspace first if you want to restore its original contents.

Release preparation alone runs `src/examples/build_sample_databases.py`; installation
and startup never regenerate models. The manifest freezes inputs, seeds, IDs, and
provenance and hashes both closed snapshots. Routine tests use small builder fixtures
and validate the checked-in full bundle without re-executing all README models.

## Containers and persistent volumes

Both images default `VALUE_STREAM_DATA_DIR` to `/data`. Mount a named volume or
writable host directory there and preserve it when replacing the container:

```bash
docker build -t value-stream-app -f Dockerfile.app .
docker volume create value-stream-app-data
docker run --rm -p 127.0.0.1:8081:8081 -v value-stream-app-data:/data value-stream-app

docker build -t value-stream-service -f Dockerfile .
docker volume create value-stream-service-data
docker run --rm -p 127.0.0.1:8080:8080 -v value-stream-service-data:/data value-stream-service
```

The application image owns its local simulation service unless given an external
URL. Separate independent images should use separate volumes. Recreating either
container with its same volume retains data; removing the volume explicitly deletes
it. The simulation-only image uses its empty simulation sample, imports no application
code during service startup, and requires no Node runtime or sample generation.

V1 remains a single-user, single-owner design. Authentication, horizontal scaling,
shared multi-user policy, and distributed-worker deployment remain future extensions.
Persistence adds no unused authentication flow or multi-instance support.

## Release acceptance

Run the normal pytest suite with a JSON coverage report, then enforce the per-file
gate. Missing modules fail the gate; a high overall percentage cannot hide an
untested adapter. New infrastructure modules under `service/persistence` are
included automatically. The checked-in type configuration retains all prior files.

```bash
uv run pytest -o addopts='' --cov=src --cov-report=xml --cov-report=json:coverage.json tests
uv run python scripts/check_persistence_coverage.py coverage.json
uv run pyright --project .agent/pyright-persistence.json
uv run python scripts/verify_distributions.py
```

Build the frontend before building distributions. The wheel and sdist include both
snapshots, their manifest, and compiled UI assets; frontend source is excluded.
Compiled assets in the sdist allow a wheel to be rebuilt without Node. Use the
actual artifact filenames for these acceptance tools:

```bash
uv run python scripts/verify_distributions.py --wheel WHEEL --sdist SDIST
uv run python scripts/verify_installed.py WHEEL
uv run python scripts/verify_containers.py --application-image APP_IMAGE --service-image SERVICE_IMAGE
```

The installed-wheel check runs outside the checkout with read-only package files,
checks import/help behavior, and compares saved identifiers and exports across
cold lifespans. The container check executes small real simulations, replaces both
containers with their original named volumes, compares persisted hashes, verifies
submission retry identity, and removes only its task-owned containers/volumes.
CI runs these checks along with frontend unit and fresh-browser/restart tests.
