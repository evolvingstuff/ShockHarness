"""TYPE002 (spec 21.1 decision 33): Python annotations that no configured checker verifies."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = '[tool.shockharness]\nprofile = "strict"\ninclude = ["src/**/*.py", "tests/**/*.py"]\n'


def annotated(count: int) -> str:
    return "".join(f"def f{n}(x: int) -> int:\n    return x\n\n\n" for n in range(count))


def plain(count: int) -> str:
    return "".join(f"def g{n}(x):\n    return x\n\n\n" for n in range(count))


def type002(root: Path, files: dict[str, str]) -> list[tuple[str, int, str]]:
    for name, text in {".shockharness.toml": CONFIG, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [(f.path, f.span.line, f.message) for f in report.findings if f.rule_id == "TYPE002"]


def test_an_annotated_project_without_a_checker_is_reported_once(tmp_path: Path) -> None:
    found = type002(tmp_path, {"src/a.py": annotated(12) + plain(2), "src/b.py": annotated(12)})
    assert [(path, line) for path, line, _ in found] == [("src/a.py", 1)]
    assert found[0][2].startswith("24 of 26 functions carry type annotations, and no Python")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pyproject.toml", "[tool.mypy]\nstrict = true\n"),
        ("pyproject.toml", "[tool.pyright]\n"),
        ("mypy.ini", "[mypy]\n"),
        ("pyrightconfig.json", "{}\n"),
        ("setup.cfg", "[mypy]\nstrict = True\n"),
    ],
)
def test_a_configured_checker_silences_it(tmp_path: Path, name: str, text: str) -> None:
    assert type002(tmp_path, {"src/a.py": annotated(30), name: text}) == []


def test_a_pyproject_without_a_checker_table_does_not(tmp_path: Path) -> None:
    files = {"src/a.py": annotated(30), "pyproject.toml": "[tool.ruff]\nline-length = 100\n"}
    assert len(type002(tmp_path, files)) == 1


def test_thresholds_and_roles(tmp_path: Path) -> None:
    assert type002(tmp_path / "few", {"src/a.py": annotated(19)}) == []  # under 20
    assert type002(tmp_path / "share", {"src/a.py": annotated(20) + plain(21)}) == []
    # Annotated tests do not count: the rule applies to production code.
    files = {"src/a.py": annotated(5), "tests/test_a.py": annotated(30)}
    assert type002(tmp_path / "tests", files) == []


def test_relaxing_it_is_a_loosening(tmp_path: Path) -> None:
    before = load_config(tmp_path, None).values
    (tmp_path / ".shockharness.toml").write_text(
        CONFIG + "\n[tool.shockharness.rules.types]\nannotated_share = 0.9\n"
        'type002_severity = "review"\nmin_annotated_functions = 50\n',
        encoding="utf-8",
    )
    after = load_config(tmp_path, None)
    messages = [
        item.message for item in loosenings(before, frozenset(), after.values, after.deviations)
    ]
    assert any("rules.types.annotated_share raised from 0.5 to 0.9" in m for m in messages)
    assert any("min_annotated_functions raised from 20 to 50" in m for m in messages)
