"""Versioned JSON codecs registered by the service that owns each model."""

import copy
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeGuard

from pydantic import BaseModel

from .errors import DatabaseError, DatabaseErrorCode

PAYLOAD_KINDS: tuple[str, ...] = ("workspace", "task_set", "run", "outcome", "job", "result")
Upgrade = Callable[[dict[str, Any]], dict[str, Any]]


def _positive_version(value: object) -> TypeGuard[int]:
    """Accept positive integers without treating JSON booleans as versions."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _reject_constant(value: str) -> None:
    """Reject JavaScript constants that are not valid JSON numbers."""
    raise ValueError("Nonfinite JSON number")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys rather than silently losing stored values."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class EncodedPayload:
    """JSON text paired with its independent payload version."""

    version: int
    text: str


@dataclass(frozen=True)
class PayloadTable:
    """Trusted table/column names used to validate persisted payload rows."""

    table: str
    kind: str
    introduced_in: int = 1
    text_column: str = "payload_json"
    version_column: str = "payload_version"
    nullable: bool = False

    def __post_init__(self) -> None:
        """Ensure only simple application-owned identifiers enter generated SQL."""
        for identifier in (self.table, self.text_column, self.version_column):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
                raise ValueError("Payload table identifiers must be simple SQL names.")
        if not _positive_version(self.introduced_in):
            raise ValueError("Payload tables require a positive schema version.")


@dataclass(frozen=True)
class _Codec:
    """One model's current version and complete sequence of dictionary upgrades."""

    model: type[BaseModel]
    version: int
    upgrades: Mapping[int, Upgrade]


class PayloadRegistry:
    """Validate JSON independently of SQL schema versions and HTTP contracts."""

    def __init__(self) -> None:
        """Create an empty registry; owning adapters register their model types."""
        self._codecs: dict[str, _Codec] = {}
        self._tables: list[PayloadTable] = []

    def register(
        self,
        kind: str,
        model: type[BaseModel],
        *,
        version: int = 1,
        upgrades: Mapping[int, Upgrade] | None = None,
    ) -> None:
        """Register a model without importing application types into shared code.

        Args:
            kind: Stable payload kind, such as one of PAYLOAD_KINDS.
            model: Current Pydantic model used after upgrading stored dictionaries.
            version: Current payload version, independent of database schema.
            upgrades: Functions keyed by source version, each advancing one version.

        Raises:
            ValueError: If registration is duplicate or an upgrade chain is incomplete.
        """
        upgrades = dict(upgrades or {})
        if not kind or kind in self._codecs:
            raise ValueError("Payload kinds must be nonempty and registered once.")
        if not _positive_version(version) or set(upgrades) != set(range(1, version)):
            raise ValueError("Payload upgrades must cover every preceding version.")
        self._codecs[kind] = _Codec(model, version, upgrades)

    def bind(self, table: PayloadTable) -> None:
        """Bind a registered codec to columns that database preflight must validate.

        Args:
            table: Trusted table and payload-column specification.

        Raises:
            ValueError: If the kind is unregistered or columns were already bound.
        """
        if table.kind not in self._codecs:
            raise ValueError("Register a payload kind before binding its table.")
        if any(
            (entry.table, entry.text_column) == (table.table, table.text_column)
            for entry in self._tables
        ):
            raise ValueError("Payload columns must be bound once.")
        self._tables.append(table)

    def _codec(self, kind: str) -> _Codec:
        """Return a known codec or a safe unsupported-payload diagnostic."""
        try:
            return self._codecs[kind]
        except KeyError as exc:
            raise DatabaseError(
                DatabaseErrorCode.PAYLOAD_UNSUPPORTED, "The payload kind is unsupported."
            ) from exc

    def serialize(self, kind: str, value: BaseModel | Mapping[str, Any]) -> EncodedPayload:
        """Validate and serialize current data without nonfinite numbers.

        Args:
            kind: Registered payload kind.
            value: Model or dictionary to persist.

        Returns:
            JSON text paired with the current payload version.

        Raises:
            DatabaseError: If the kind or data cannot be safely persisted.
        """
        codec = self._codec(kind)
        try:
            model = codec.model.model_validate(value)
            text = json.dumps(
                model.model_dump(mode="json"),
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (ValueError, TypeError, RecursionError) as exc:
            raise DatabaseError(
                DatabaseErrorCode.INVALID, "The payload cannot be serialized as valid JSON."
            ) from exc
        return EncodedPayload(codec.version, text)

    def deserialize(self, kind: str, version: object, text: object) -> BaseModel:
        """Upgrade stored dictionaries in memory, then validate the current model.

        Args:
            kind: Registered payload kind.
            version: Untrusted stored value, validated as a positive integer.
            text: Untrusted stored JSON value, validated as text. It is never
                included in diagnostics.

        Returns:
            A current model with stable stored identifiers and defaulted fields.

        Raises:
            DatabaseError: If data is malformed, unsupported, or cannot be upgraded.
        """
        codec = self._codec(kind)
        if not _positive_version(version) or version > codec.version:
            raise DatabaseError(
                DatabaseErrorCode.PAYLOAD_UNSUPPORTED, "The payload version is unsupported."
            )
        try:
            if not isinstance(text, str):
                raise ValueError("Payload must be text")
            value = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_object)
            if not isinstance(value, dict):
                raise ValueError("Payload must be an object")
            for previous in range(version, codec.version):
                value = codec.upgrades[previous](copy.deepcopy(value))
                if not isinstance(value, dict):
                    raise ValueError("An upgrade must return an object")
            # Catch nonfinite values introduced by an upgrade before Pydantic coercion.
            json.dumps(value, allow_nan=False)
            return codec.model.model_validate(value)
        except Exception as exc:
            raise DatabaseError(
                DatabaseErrorCode.INVALID, "The stored payload is invalid or cannot be upgraded."
            ) from exc

    def validate_database(self, connection: sqlite3.Connection, schema_version: int) -> None:
        """Validate bound rows without rewriting historical payloads.

        Args:
            connection: Connection participating in preflight or a migration.
            schema_version: Schema version that determines which tables exist.

        Raises:
            DatabaseError: If a registered table or its stored data is invalid.
        """
        for entry in self._tables:
            if entry.introduced_in > schema_version:
                continue
            exists = connection.execute(
                "SELECT type FROM sqlite_schema WHERE name = ?", (entry.table,)
            ).fetchone()
            if exists is None or exists[0] != "table":
                raise DatabaseError(DatabaseErrorCode.INVALID, "A payload table is missing.")
            rows = connection.execute(
                f'SELECT "{entry.version_column}", "{entry.text_column}" FROM "{entry.table}"'
            )
            for version, text in rows:
                if entry.nullable and version is None and text is None:
                    continue
                self.deserialize(entry.kind, version, text)
