"""Payload compatibility and safe validation without changing HTTP model rules."""

import json
import sqlite3
import unittest
from typing import Any, NoReturn, NotRequired, TypedDict
from unittest.mock import Mock
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from value_stream.service.persistence.errors import DatabaseError, DatabaseErrorCode
from value_stream.service.persistence.payloads import (
    PAYLOAD_KINDS,
    PayloadRegistry,
    PayloadTable,
    Upgrade,
)


class ExampleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    count: int = 5


class NumericRecord(BaseModel):
    value: float


class PayloadTableOptions(TypedDict):
    table: str
    introduced_in: NotRequired[int]


class TestPayloadRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = PayloadRegistry()
        self.registry.register("workspace", ExampleRecord)
        self.identity = uuid4()

    def test_all_planned_kinds_begin_at_version_one(self) -> None:
        registry = PayloadRegistry()
        for kind in PAYLOAD_KINDS:
            registry.register(kind, ExampleRecord)
            payload = registry.serialize(kind, ExampleRecord(id=self.identity, name="Example"))
            self.assertEqual(payload.version, 1)
            loaded = registry.deserialize(kind, payload.version, payload.text)
            assert isinstance(loaded, ExampleRecord)
            self.assertEqual(loaded.id, self.identity)

    def test_new_optional_fields_load_defaults_and_preserve_ids(self) -> None:
        original = json.dumps({"id": str(self.identity), "name": "Older example"})
        loaded = self.registry.deserialize("workspace", 1, original)
        assert isinstance(loaded, ExampleRecord)
        self.assertEqual(loaded.count, 5)
        self.assertEqual(loaded.id, self.identity)
        self.assertEqual(json.loads(original), {"id": str(self.identity), "name": "Older example"})

    def test_renamed_and_removed_fields_use_explicit_sequential_upgrades(self) -> None:
        def rename(value: dict[str, Any]) -> dict[str, Any]:
            value["name"] = value.pop("title")
            return value

        def remove(value: dict[str, Any]) -> dict[str, Any]:
            value.pop("obsolete")
            return value

        registry = PayloadRegistry()
        registry.register("run", ExampleRecord, version=3, upgrades={1: rename, 2: remove})
        original = json.dumps({"id": str(self.identity), "title": "Old", "obsolete": True})
        result = registry.deserialize("run", 1, original)
        assert isinstance(result, ExampleRecord)
        self.assertEqual(result.id, self.identity)
        self.assertEqual(result.name, "Old")
        self.assertEqual(registry.serialize("run", result).version, 3)
        self.assertIn("obsolete", original)

    def test_malformed_unknown_and_incompatible_data_are_safe_errors(self) -> None:
        invalid = (
            "not JSON secret-value",
            '"secret-value"',
            "[]",
            '{"name":"first","name":"secret-value"}',
            '{"value":NaN}',
            '{"value":Infinity}',
            '{"value":1e999}',
            '{"id":"invalid","name":"secret-value"}',
            json.dumps({"id": str(self.identity), "name": "secret-value", "extra": True}),
            None,
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(DatabaseError) as error:
                self.registry.deserialize("workspace", 1, value)
            self.assertEqual(error.exception.code, DatabaseErrorCode.INVALID)
            self.assertNotIn("secret-value", str(error.exception))
        for version in (0, 2, -1, True, "1", None):
            with self.subTest(version=version), self.assertRaises(DatabaseError) as error:
                self.registry.deserialize("workspace", version, "{}")
            self.assertEqual(error.exception.code, DatabaseErrorCode.PAYLOAD_UNSUPPORTED)
        with self.assertRaises(DatabaseError) as error:
            self.registry.serialize("unknown", {})
        self.assertEqual(error.exception.code, DatabaseErrorCode.PAYLOAD_UNSUPPORTED)

    def test_serialization_rejects_invalid_models_and_nonfinite_values(self) -> None:
        with self.assertRaises(DatabaseError):
            self.registry.serialize("workspace", {"name": "secret-value"})
        self.registry.register("result", NumericRecord)
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(DatabaseError):
                self.registry.serialize("result", {"value": value})

    def test_bad_upgrade_results_and_exceptions_are_wrapped(self) -> None:
        def fail(value: dict[str, Any]) -> NoReturn:
            raise RuntimeError("secret-value")

        def nonfinite(value: dict[str, Any]) -> dict[str, Any]:
            return {"value": float("nan")}

        # A test double deliberately violates the callback's return contract.
        # Production upgrade functions must return dictionaries statically.
        invalid_return = Mock(return_value=[])
        upgrades: tuple[Upgrade, ...] = (invalid_return, nonfinite, fail)
        for upgrade in upgrades:
            registry = PayloadRegistry()
            registry.register("result", NumericRecord, version=2, upgrades={1: upgrade})
            with self.subTest(upgrade=upgrade), self.assertRaises(DatabaseError) as error:
                registry.deserialize("result", 1, '{"value":1}')
            self.assertNotIn("secret-value", str(error.exception))

    def test_registration_and_binding_reject_configuration_errors(self) -> None:
        def identity(value: dict[str, Any]) -> dict[str, Any]:
            return value

        cases: tuple[tuple[int, dict[int, Upgrade]], ...] = (
            (0, {}),
            (True, {}),
            (2, {}),
            (1, {1: identity}),
        )
        for version, upgrades in cases:
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.registry.register("new", ExampleRecord, version=version, upgrades=upgrades)
        for kind in ("", "workspace"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.registry.register(kind, ExampleRecord)
        with self.assertRaises(ValueError):
            self.registry.bind(PayloadTable("records", "unknown"))
        options: tuple[PayloadTableOptions, ...] = (
            {"table": 'records"; DROP TABLE other'},
            {"table": "records", "introduced_in": 0},
        )
        for kwargs in options:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PayloadTable(kind="workspace", **kwargs)
        self.registry.bind(PayloadTable("records", "workspace"))
        with self.assertRaises(ValueError):
            self.registry.bind(PayloadTable("records", "workspace"))

    def test_bound_database_rows_are_validated_without_rewriting(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        self.registry.bind(PayloadTable("records", "workspace", introduced_in=2, nullable=True))
        self.registry.validate_database(connection, 1)
        with self.assertRaises(DatabaseError):
            self.registry.validate_database(connection, 2)
        connection.execute("CREATE TABLE records (payload_version INTEGER, payload_json TEXT)")
        original = json.dumps({"id": str(self.identity), "name": "Historical"})
        connection.executemany("INSERT INTO records VALUES (?, ?)", [(1, original), (None, None)])
        self.registry.validate_database(connection, 2)
        self.assertEqual(
            connection.execute("SELECT payload_json FROM records").fetchone()[0], original
        )
        connection.execute("INSERT INTO records VALUES (1, NULL)")
        with self.assertRaises(DatabaseError):
            self.registry.validate_database(connection, 2)

    def test_a_view_cannot_spoof_a_payload_table(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute(
            "CREATE VIEW records AS SELECT 1 AS payload_version, '{}' AS payload_json"
        )
        self.registry.bind(PayloadTable("records", "workspace"))
        with self.assertRaises(DatabaseError):
            self.registry.validate_database(connection, 1)
