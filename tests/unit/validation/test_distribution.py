"""Release gates must detect missing code, corrupt samples, and incomplete archives."""

import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from examples.build_sample_databases import build
from scripts.check_persistence_coverage import CORE, check, main, required_files
from scripts.verify_distributions import BUNDLE, FILES, archives, bundle
from scripts.verify_installed import fingerprint, read_only
from value_stream.app.storage import RunRecord
from value_stream.service.schemas import MetadataData, ResultData, SummaryData


def result(item: tuple[RunRecord, int]) -> ResultData:
    """Use small valid results so release gate unit tests never regenerate README work."""
    record, index = item
    return ResultData(
        model_index=index,
        model=record.status.outcomes[index].scenario.model,
        summary_result=SummaryData(completion_time=2, total_delivered_value=1, loss=0),
        metadata=MetadataData(event_metadata=[], resource_metadata=[]),
    )


class TestReleaseValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def coverage_root(self) -> Path:
        root = self.root / "repository"
        for name in (
            *CORE,
            "service/persistence/new_module.py",
            "service/persistence/nested/adapter.py",
        ):
            path = root / "src/value_stream" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("import sqlite3\n")
        (root / "src/examples").mkdir()
        (root / "src/examples/build_sample_databases.py").write_text("import json\n")
        (root / "src/value_stream/service/persistence/__init__.py").write_text(
            '"""Empty module."""\n'
        )
        return root

    def test_gate_requires_each_module_and_discovers_future_nested_code(self) -> None:
        root = self.coverage_root()
        files = required_files(root)
        self.assertTrue(any(p.name == "adapter.py" for p in files))
        self.assertFalse(any(p.name == "__init__.py" for p in files))
        report = {
            "files": {
                str(path.relative_to(root)): {"summary": {"covered_lines": 9, "num_statements": 10}}
                for path in files
            }
        }
        self.assertFalse(check(report, root))
        first = str(files[0].relative_to(root))
        report["files"][first]["summary"]["covered_lines"] = 8
        self.assertIn("80.00%", check(report, root)[0])
        del report["files"][first]
        self.assertIn("missing coverage", check(report, root)[0])
        report["files"][first] = {"summary": {"covered_lines": 0, "num_statements": 0}}
        self.assertFalse(check(report, root))
        path = self.root / "coverage.json"
        path.write_text(json.dumps(report))
        with (
            patch("sys.argv", ["gate", str(path)]),
            patch("scripts.check_persistence_coverage.required_files", return_value=files),
            patch("scripts.check_persistence_coverage.check", return_value=[]),
        ):
            self.assertEqual(main(), 0)
        with (
            patch("sys.argv", ["gate", str(path)]),
            patch("scripts.check_persistence_coverage.check", return_value=["missing"]),
        ):
            self.assertEqual(main(), 1)

    def sample(self) -> Path:
        directory = self.root / "samples"
        with patch("examples.build_sample_databases.execute", side_effect=result):
            build(directory, task_count=2)
        return directory

    def test_bundle_and_real_archive_layouts(self) -> None:
        directory = self.sample()
        self.assertEqual(bundle(directory)["release"], "readme-v1")
        wheel = self.root / "test.whl"
        sdist = self.root / "test.tar.gz"
        with zipfile.ZipFile(wheel, "w") as archive:
            for name in FILES:
                archive.write(directory / name, BUNDLE + name)
            archive.writestr("value_stream/app/static/index.html", "index")
            archive.writestr("value_stream/app/static/assets/test.js", "code")
        with tarfile.open(sdist, "w:gz") as archive:
            for name in FILES:
                archive.add(directory / name, "release/src/" + BUNDLE + name)
        self.assertEqual(archives(wheel, sdist)["wheel"]["examples"], 9)
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("value_stream/app/frontend/source.ts", "leak")
        with self.assertRaisesRegex(ValueError, "leaked"):
            archives(wheel, sdist)
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("value_stream/__init__.py", "")
        with self.assertRaisesRegex(ValueError, "assets"):
            archives(wheel, sdist)

    def test_corrupt_or_incomplete_bundle_is_rejected(self) -> None:
        directory = self.sample()
        manifest = directory / "manifest.json"
        original = manifest.read_text()
        for field, value in [("format_version", True), ("format_version", 2)]:
            data = json.loads(original)
            data[field] = value
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "manifest"):
                bundle(directory)
        data = json.loads(original)
        data["regeneration"]["namespace"] = "wrong"
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "namespace"):
            bundle(directory)
        manifest.write_text(original)
        sidecar = directory / "application.sqlite3-wal"
        sidecar.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "sidecars"):
            bundle(directory)
        sidecar.unlink()
        with (directory / "application.sqlite3").open("ab") as writer:
            writer.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            bundle(directory)

    def test_installed_readonly_permissions_restore_even_on_failure(self) -> None:
        site = self.root / "site"
        site.mkdir()
        source = site / "code.py"
        source.write_text("code")
        original = source.stat().st_mode
        before = fingerprint(site)
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with read_only(site):
                self.assertFalse(source.stat().st_mode & 0o222)
                self.assertFalse(site.stat().st_mode & 0o222)
                raise RuntimeError("test failure")
        self.assertEqual(source.stat().st_mode, original)
        self.assertEqual(fingerprint(site), before)
        source.write_text("changed")
        self.assertNotEqual(fingerprint(site), before)
