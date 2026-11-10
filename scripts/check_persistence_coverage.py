"""Require measured coverage for every persistence/recovery module, including new files."""

import argparse
import ast
import json
from pathlib import Path
from typing import Any

CORE = (
    "app/storage.py",
    "app/sqlite_storage.py",
    "app/sample_import.py",
    "app/examples.py",
    "app/coordinator.py",
    "app/gateway.py",
    "app/server.py",
    "service/job_store.py",
    "service/scheduler.py",
    "client/web/local_service.py",
)


def required_files(root: Path) -> list[Path]:
    """Discover new infrastructure modules automatically and retain all adapter gates."""
    package = root / "src/value_stream"
    files = [package / name for name in CORE]
    files.extend((package / "service/persistence").rglob("*.py"))
    files.append(root / "src/examples/build_sample_databases.py")
    return sorted(
        path
        for path in files
        if any(
            not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            for node in ast.parse(path.read_text()).body
        )
    )


def check(report: dict[str, Any], root: Path, minimum: float = 90) -> list[str]:
    """Report missing/insufficient modules without substituting aggregate coverage.

    Args:
        report: Coverage.py JSON report.
        root: Repository root used to normalize report filenames.
        minimum: Required percentage of executable lines.

    Returns:
        Human-readable failures; an empty list means every module passed.
    """
    measured = {
        Path(name).resolve() if Path(name).is_absolute() else (root / name).resolve(): value
        for name, value in report["files"].items()
    }
    failures: list[str] = []
    for path in required_files(root):
        relative = path.relative_to(root).as_posix()
        value = measured.get(path.resolve())
        if value is None:
            failures.append(f"{relative}: missing coverage")
            continue
        summary = value["summary"]
        if summary["num_statements"] == 0:
            continue
        percent = 100 * summary["covered_lines"] / summary["num_statements"]
        if percent < minimum:
            failures.append(f"{relative}: {percent:.2f}% < {minimum:g}%")
    return failures


def main() -> int:
    """Exit nonzero for any missing or under-covered persistence module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    failures = check(json.loads(args.report.read_text()), Path(__file__).resolve().parents[1])
    print(
        "\n".join(failures)
        if failures
        else "All persistence/recovery modules meet 90% line coverage."
    )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
