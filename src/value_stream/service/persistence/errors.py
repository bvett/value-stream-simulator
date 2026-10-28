"""Safe diagnostics for database startup and maintenance failures."""

from enum import StrEnum


class DatabaseErrorCode(StrEnum):
    """Stable error codes for callers and operator diagnostics."""

    IN_USE = "DATABASE_IN_USE"
    KIND_MISMATCH = "DATABASE_KIND_MISMATCH"
    VERSION_UNSUPPORTED = "DATABASE_VERSION_UNSUPPORTED"
    PAYLOAD_UNSUPPORTED = "DATABASE_PAYLOAD_UNSUPPORTED"
    INVALID = "DATABASE_INVALID"
    PERMISSION = "DATABASE_PERMISSION"
    BACKUP_FAILED = "DATABASE_BACKUP_FAILED"
    MIGRATION_FAILED = "DATABASE_MIGRATION_FAILED"


class DatabaseError(RuntimeError):
    """A database failure described without including stored payloads."""

    def __init__(self, code: DatabaseErrorCode, message: str) -> None:
        """Initialize an error with a stable code and safe diagnostic.

        Args:
            code: Machine-readable failure category.
            message: Operator-facing explanation without stored data.
        """
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
