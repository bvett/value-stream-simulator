# Specification for adding data persistence

## Goals

- Provide data persistence between service starts
- Package a default database for distribution with the application

## Version 1 Requirements

- Use SQLLite unless it is not fit for purpose.
- Source files belong under `src/value_stream/service`.
- Separate databases for API and web services.
- A service connects with its default database unless another database is specified as an argument.
- If the default database cannot be found, an empty database is created.

## Intended use and future scope

Version 1 enables users of the Value Stream Simulator to easily access simulation results referenced in documentation.

## Implementation and design prerequisites

- Write an ExecPlan for this significant feature before coding, following `.agent/PLANS.md` as required by `AGENTS.md`.

- Use SQLLite unless it is not fit for purpose.

- Source files belong under `src/value_stream/service`.

- Code must be extensible to support integration with other database implementations in the future.

- Minimize need for persistence-layer code changes when there are changes to existing data classes.

- Balance the need for stable table structure with support for versioned JSON payloads.

- Follow best practices for versioning and migrating database schema to maintain compatibility with the service.

- Any automatic migration of the database must be fail-safe.

- Frequent changes are expected to happen to the data classes in the future as new properties are introduced. Minimize the potential of breaking changes and maximize backward compatibility with existing databases.

- Solution must follow best practices and be secure by design.

- Include module, class, and method docstrings that follow the Google standard.

- Include tests that achieve a minimum of 90% code coverage.

- For the initial version, it is required to support a single-user running a self-hosted instance.

- Authentication is not required.
