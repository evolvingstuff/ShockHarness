"""ROLE001 (spec 21.1 decision 24): is code classified as a test really a test?"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.cli import main
from shockharness.config import EffectiveConfig
from shockharness.report import Report
from shockharness.rules import registry
from tests.conftest import commit_all, init_repo

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def analyze(root: Path, config: EffectiveConfig) -> Report:
    return analyze_paths([root], root, config, OPTIONS)


def rows(report: Report) -> list[tuple[str, int, str]]:
    return [(f.path, f.span.line, f.severity) for f in report.findings if f.rule_id == "ROLE001"]


def project(root: Path) -> None:
    write(root, "src/app/__init__.py", "")
    write(
        root,
        "src/app/payments.py",
        "from tests.helpers import charge\nfrom tests.billing import bill\n\n\n"
        "def pay(order):\n    return charge(bill(order))\n",
    )
    write(root, "tests/__init__.py", "")
    write(root, "tests/helpers.py", "def charge(order):\n    return order\n")
    write(root, "tests/billing.py", "def bill(order):\n    return order\n")
    write(
        root,
        "tests/test_billing.py",
        "from tests.billing import bill\n\n\ndef test_bill():\n    assert bill(ONE) == ONE\n",
    )
    write(root, "tests/conftest.py", "import pytest\n")


def test_production_imports_of_test_files_and_empty_tests(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    project(empty_root)
    report = analyze(empty_root, make_config('include = ["src/**/*.py", "tests/**/*.py"]\n'))
    assert rows(report) == [
        ("src/app/payments.py", 1, "warning"),  # tests/helpers.py: a support file, still shipped
        ("src/app/payments.py", 2, "warning"),
        ("tests/billing.py", 1, "review"),  # no test case, not a support file
    ]
    first = next(f for f in report.findings if f.rule_id == "ROLE001")
    assert first.message.startswith(
        "production code imports tests/helpers.py, classified as a test file by 'tests/**'"
    )
    assert registry.category_of(first.rule_id) == "policy_integrity"


def test_singular_fixture_and_support_modules_are_support_files(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    # MetaList: one shared fixture record (singular), and support modules.
    write(empty_root, "tests/unit/snapshot_note_fixture.py", "NOTE = {}\n")
    write(empty_root, "tests/db_support.py", "def connect():\n    return None\n")
    write(empty_root, "tests/support/clock.py", "def now():\n    return None\n")
    write(empty_root, "tests/unit/notes.py", "def note():\n    return None\n")
    report = analyze(empty_root, make_config('include = ["tests/**/*.py"]\n'))
    assert rows(report) == [("tests/unit/notes.py", 1, "review")]


def test_support_files_and_severities_are_configurable(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    project(empty_root)
    config = make_config(
        'include = ["src/**/*.py", "tests/**/*.py"]\n'
        "[tool.shockharness.rules.role_integrity]\n"
        'severity = "error"\nempty_test_severity = "warning"\n'
        'support_files = ["**/conftest.py", "**/__init__.py", "**/*helper*", "tests/billing.py"]\n'
    )
    assert rows(analyze(empty_root, config)) == [
        ("src/app/payments.py", 1, "error"),
        ("src/app/payments.py", 2, "error"),
    ]
    assert any("support_files also permits 'tests/billing.py'" in d for d in config.deviations)
    off = make_config(
        'include = ["src/**/*.py", "tests/**/*.py"]\n'
        "[tool.shockharness.rules.role_integrity]\nenabled = false\n"
    )
    assert rows(analyze(empty_root, off)) == []


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(args)
    return code, capsys.readouterr().out


def test_diff_reports_files_newly_classified_as_tests(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, "src/app/core.py", "def core(value):\n    return value\n")
    write(empty_root, "src/app/extra.py", "def extra(value):\n    return value\n")
    write(empty_root, "src/app/kept.py", "def kept(value):\n    return value\n")
    base = commit_all(empty_root, "base", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    # Re-globbing: extra.py becomes a test by a new file_roles glob; renaming: core.py moves
    # under tests/ (and is no longer a production file).
    write(
        empty_root,
        ".shockharness.toml",
        '[tool.shockharness.file_roles]\ntest = ["tests/**", "src/app/extra.py"]\n',
    )
    (empty_root / "tests").mkdir()
    (empty_root / "src/app/core.py").rename(empty_root / "tests/core.py")
    commit_all(empty_root, "shield", "2026-01-02T12:00:00+00:00", "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root), "--format", "json"]
    code, out = run(["diff", *revision], capsys)
    assert code == 0
    data = json.loads(out)
    shielded = sorted(
        (f["path"], f["message"].split(" by ")[1])
        for f in data["findings"]
        if f["rule_id"] == "VERIFY003" and "now classified as a test" in f["message"]
    )
    assert shielded == [
        ("src/app/extra.py", "'src/app/extra.py': the production rules no longer apply to it"),
        (
            "tests/core.py",
            "'tests/**' (moved from src/app/core.py): the production rules no longer apply to it",
        ),
    ]
