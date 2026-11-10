"""Database configuration precedence, path identity, and lazy resolution tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from value_stream.service.persistence.config import (
    DatabaseConfig,
    DatabaseKind,
    ensure_distinct_databases,
)
from value_stream.service.persistence.errors import DatabaseError


class TestDatabaseConfig(unittest.TestCase):
    def test_arguments_override_component_environment_and_default_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "VALUE_STREAM_APP_DATABASE": str(root / "environment-app.sqlite3"),
                "VALUE_STREAM_SERVICE_DATABASE": str(root / "environment-job.sqlite3"),
                "VALUE_STREAM_DATA_DIR": str(root / "environment-data"),
            }
            app = DatabaseConfig.resolve(
                "application", database=root / "explicit.sqlite3", environ=environment
            )
            service = DatabaseConfig.resolve("simulation", environ=environment)
            self.assertEqual(app.path, root.resolve() / "explicit.sqlite3")
            self.assertFalse(app.use_bundle)
            self.assertEqual(service.path.name, "environment-job.sqlite3")
            self.assertFalse(service.use_bundle)
            environment.pop("VALUE_STREAM_APP_DATABASE")
            app = DatabaseConfig.resolve(
                "application", data_dir=root / "explicit-data", environ=environment
            )
            self.assertEqual(app.path.parent.name, "explicit-data")
            self.assertTrue(app.use_bundle)
            app = DatabaseConfig.resolve("application", environ=environment)
            self.assertEqual(app.path.parent.name, "environment-data")
            self.assertEqual(list(root.iterdir()), [])

    def test_user_directory_and_process_environment_are_resolved_without_io(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-created"
            with patch(
                "value_stream.service.persistence.config.user_data_path", return_value=root
            ) as lookup:
                config = DatabaseConfig.resolve("application", environ={})
                lookup.assert_called_once_with("value-stream", appauthor=False)
            self.assertEqual(config.filename, "application.sqlite3")
            self.assertFalse(root.exists())
            with patch.dict(os.environ, {"VALUE_STREAM_DATA_DIR": str(root)}, clear=True):
                self.assertEqual(
                    DatabaseConfig.resolve("simulation").filename, "simulation.sqlite3"
                )

    def test_relative_home_and_symlink_paths_are_normalized(self) -> None:
        self.assertEqual(
            DatabaseConfig("application", Path("relative.sqlite3")).path,
            Path.cwd() / "relative.sqlite3",
        )
        self.assertEqual(
            DatabaseConfig.resolve("application", database="~/example.sqlite3", environ={}).path,
            Path.home().resolve() / "example.sqlite3",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.sqlite3"
            target.touch()
            link = root / "alias.sqlite3"
            link.symlink_to(target)
            app = DatabaseConfig("application", target)
            service = DatabaseConfig("simulation", link)
            with self.assertRaises(DatabaseError):
                ensure_distinct_databases(app, service)
            link.unlink()
            os.link(target, link)
            with self.assertRaises(DatabaseError):
                ensure_distinct_databases(app, DatabaseConfig("simulation", link))
            ensure_distinct_databases(app, DatabaseConfig("simulation", root / "another.sqlite3"))

    def test_connection_uris_and_empty_paths_are_rejected(self) -> None:
        for value in ("", " ", "sqlite:///db.sqlite3", "file:db.sqlite3", ":memory:"):
            with self.subTest(value=value), self.assertRaises(DatabaseError):
                DatabaseConfig.resolve(DatabaseKind.APPLICATION, database=value, environ={})
