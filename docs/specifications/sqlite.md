# Specification for adding data persistence

## Goals

- Preserve application-service and simulation-service data across restarts.
- Distribute default databases containing the examples needed to explore simulation results referenced in documentation.

## Version 1 Requirements

- Use SQLite with separate databases for the application service and simulation service.
- Support a single user running a self-hosted instance. Authentication is not required.

### Default databases

- Each service connects to its default database unless another database is specified as an argument.
- Store writable default databases in the user data directory.
- When a writable default database does not exist, initialize it from an exact copy of the corresponding bundled database, preserving all stored identifiers. If no bundled default exists, create an empty database with the required schema.
- Preserve existing writable databases on subsequent launches; do not overwrite them with bundled defaults.

### Retention and restart behavior

- Retain workspaces, inputs, comparisons, and their results until the user explicitly deletes them. Manage temporary caches and simulation-service jobs using separate retention policies that do not remove saved application-service data.
- Preserve completed outcomes across restarts, including outcomes from unfinished simulations.
- Finalize local work interrupted by simulation-service shutdown or restart rather than automatically rerunning unfinished models.
- When the application service restarts, reconnect to jobs that are still running in an external simulation service.

### Documentation examples

- Bundle the current README examples with their inputs and completed results.
- Support documentation URLs that restore the specified workspace, comparison, scenario, and chart tab.
- Preserve example identifiers when copying databases, importing examples, or migrating data so documentation links continue to identify the same records.
- Allow users to edit or delete bundled examples in the writable database. Document that these actions can change the results shown by documentation links or make those links unavailable.
- Provide an explicit sample import command for adding missing examples to an existing database. Preserve existing records and report identifier conflicts rather than replacing records. Do not automatically import new examples into existing databases at startup.

## Intended use and future scope

Version 1 enables users of the Value Stream Simulator to easily access simulation results referenced in documentation.

Keep storage extensible so other database implementations can be integrated in the future. Minimize persistence-layer changes as data classes evolve, while maximizing backward compatibility with existing databases.

## Implementation and design prerequisites

- Write an ExecPlan for this significant feature before coding, following `.agent/PLANS.md` as required by `AGENTS.md`.

- Place shared database infrastructure and the simulation-service job adapter under `src/value_stream/service`. Place the application-service workspace adapter and frontend integration under `src/value_stream/app`.

- Follow best practices and be secure by design.

- Include module, class, and method docstrings that follow the Google standard.

### Migration safety

- Create and verify a database backup before migration.
- Apply database migrations transactionally and stop service startup if migration fails. Preserve the existing data and provide a clear error so recovery can be performed from the verified backup when necessary.
- Report unsupported newer database versions, corruption, and permission failures clearly. Do not replace an existing database with an empty database or bundled default when opening or migration fails.

### Schema and payload versioning

- Version database schemas and JSON payloads separately, with explicit upgrade paths for each.
- Use stable relational columns for identifiers, relationships, revisions, and searchable state, with versioned JSON payloads for evolving model details.
- Support new optional properties through defaults when loading older payloads. Provide explicit payload upgrades for incompatible changes such as renamed or removed properties.

### Durable writes

- Make coordinator updates explicit through storage operations so changes are durably written rather than relying on direct mutation of stored objects.
- Persist outcomes and their processing cursors atomically so a restart cannot advance a cursor without retaining the corresponding outcomes.
- Use persisted timestamps that remain meaningful across machine restarts.

### Validation and acceptance

- Require at least 90% code coverage for new persistence and recovery code.
- Include tests for restart durability, retention of completed outcomes from interrupted work, and reconnection to an external simulation service.
- Test migration failures, backup verification, unsupported newer versions, corruption, and permission failures without replacing existing databases.
- Test backward-compatible payload loading, defaults for new optional properties, and explicit upgrades for incompatible payload changes.
- Test default database initialization, preservation of identifiers and existing databases, and explicit sample imports with identifier conflicts.
- Verify that documentation links opened in a fresh browser session restore the expected workspace, comparison, scenario, and chart tab using the bundled results.
