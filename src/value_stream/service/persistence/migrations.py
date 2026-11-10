"""Explicit, sequential schema migrations for independently versioned stores."""

import sqlite3
from dataclasses import dataclass
from typing import Callable

from .config import DatabaseKind

APPLICATION_IDS: dict[DatabaseKind, int] = {
    DatabaseKind.APPLICATION: 0x56534150,
    DatabaseKind.SIMULATION: 0x56534A42,
}
METADATA_VERSION = 1


@dataclass(frozen=True)
class Migration:
    """A schema version and trusted code that applies its changes."""

    version: int
    apply: Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, init=False)
class DatabaseSchema:
    """A complete migration chain and optional version-aware validation."""

    kind: DatabaseKind
    migrations: tuple[Migration, ...]
    validate: Callable[[sqlite3.Connection, int], None] | None = None

    def __init__(
        self,
        kind: DatabaseKind | str,
        migrations: tuple[Migration, ...],
        validate: Callable[[sqlite3.Connection, int], None] | None = None,
    ) -> None:
        """Normalize ownership and require a contiguous migration chain.

        Args:
            kind: Owning component name or enum value.
            migrations: Complete migration chain starting at version one.
            validate: Optional read-only, version-aware schema validator.

        Raises:
            ValueError: If a chain is empty, incomplete, or out of order.
        """
        object.__setattr__(self, "kind", DatabaseKind(kind))
        if not migrations or [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
            raise ValueError("Schema migrations must be consecutive from version 1.")
        object.__setattr__(self, "migrations", migrations)
        object.__setattr__(self, "validate", validate)

    @property
    def version(self) -> int:
        """Return the current schema version."""
        return self.migrations[-1].version

    def apply(self, connection: sqlite3.Connection, previous_version: int) -> None:
        """Apply the remaining chain inside the caller's transaction.

        Args:
            connection: Connection with an active write transaction.
            previous_version: Previously committed schema version.
        """
        for migration in self.migrations[previous_version:]:
            migration.apply(connection)
        connection.execute(f"PRAGMA user_version = {self.version}")


def initial_schema(kind: DatabaseKind | str) -> DatabaseSchema:
    """Build the metadata foundation; adapters add real domain migrations later.

    Args:
        kind: Component whose database is being created.

    Returns:
        Version-one schema containing the database ownership metadata.
    """
    kind = DatabaseKind(kind)

    def initialize(connection: sqlite3.Connection) -> None:
        """Create metadata in the transaction owned by the database manager."""
        connection.execute(
            "CREATE TABLE store_meta ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "kind TEXT NOT NULL CHECK (kind IN ('application', 'simulation')), "
            "metadata_version INTEGER NOT NULL CHECK (metadata_version > 0))"
        )
        connection.execute(
            "INSERT INTO store_meta VALUES (1, ?, ?)", (kind.value, METADATA_VERSION)
        )
        connection.execute(f"PRAGMA application_id = {APPLICATION_IDS[kind]}")

    return DatabaseSchema(kind, (Migration(1, initialize),))
