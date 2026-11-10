"""Resolve database filesystem paths without touching the filesystem."""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from platformdirs import user_data_path

from .errors import DatabaseError, DatabaseErrorCode


class DatabaseKind(StrEnum):
    """Components that independently own a database."""

    APPLICATION = "application"
    SIMULATION = "simulation"


def _path(value: str | Path) -> Path:
    """Normalize a filesystem path while rejecting SQLite connection URIs.

    Args:
        value: An explicit path or directory.

    Returns:
        An absolute path with existing symlinks resolved.

    Raises:
        DatabaseError: If the input is empty or represents a connection URI.
    """
    text = str(value)
    if not text.strip() or "://" in text or text.startswith("file:") or text == ":memory:":
        raise DatabaseError(DatabaseErrorCode.INVALID, "Specify a database filesystem path.")
    return Path(value).expanduser().resolve()


@dataclass(frozen=True, init=False)
class DatabaseConfig:
    """An owned database path and whether bundled initialization is permitted."""

    kind: DatabaseKind
    path: Path
    use_bundle: bool = False

    def __init__(
        self, kind: DatabaseKind | str, path: str | Path, use_bundle: bool = False
    ) -> None:
        """Accept filesystem inputs and retain their normalized, concrete types.

        Args:
            kind: Owning component name or enum value.
            path: Database filesystem path, normalized once at construction.
            use_bundle: Whether an absent database may copy a bundled sample.
        """
        object.__setattr__(self, "kind", DatabaseKind(kind))
        object.__setattr__(self, "path", _path(path))
        object.__setattr__(self, "use_bundle", use_bundle)

    @property
    def filename(self) -> str:
        """Return the fixed resource filename for this database kind."""
        return f"{self.kind.value}.sqlite3"

    @classmethod
    def resolve(
        cls,
        kind: DatabaseKind | str,
        *,
        database: str | Path | None = None,
        data_dir: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "DatabaseConfig":
        """Choose explicit arguments, environment values, then user defaults.

        Args:
            kind: Component that owns the database.
            database: Explicit database filename; missing files start empty.
            data_dir: Explicit directory for the default database.
            environ: Environment mapping, defaulting to the process environment.

        Returns:
            Configuration that can be opened later without rereading settings.
        """
        kind = DatabaseKind(kind)
        environ = os.environ if environ is None else environ
        variable = (
            "VALUE_STREAM_APP_DATABASE"
            if kind == DatabaseKind.APPLICATION
            else "VALUE_STREAM_SERVICE_DATABASE"
        )
        selected = database if database is not None else environ.get(variable)
        if selected is not None:
            return cls(kind, _path(selected))
        directory = data_dir if data_dir is not None else environ.get("VALUE_STREAM_DATA_DIR")
        if directory is None:
            directory = user_data_path("value-stream", appauthor=False)
        return cls(kind, _path(directory) / f"{kind.value}.sqlite3", use_bundle=True)


def ensure_distinct_databases(application: DatabaseConfig, simulation: DatabaseConfig) -> None:
    """Reject sharing a file between the two service owners.

    Args:
        application: Application-service configuration.
        simulation: Owned simulation-service configuration.

    Raises:
        DatabaseError: If paths, symlinks, or existing hard links identify one file.
    """
    same = application.path == simulation.path
    if application.path.exists() and simulation.path.exists():
        same = same or application.path.samefile(simulation.path)
    if same:
        raise DatabaseError(
            DatabaseErrorCode.KIND_MISMATCH,
            "Application and simulation services require separate database files.",
        )
