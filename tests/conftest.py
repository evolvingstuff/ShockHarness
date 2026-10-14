"""Shared fixtures. Tests never need network, git, or an LLM."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PYTHON_EXECUTABLE = sys.executable


@pytest.fixture
def empty_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def strict_config(empty_root: Path) -> EffectiveConfig:
    """Bundled strict defaults: a root with no configuration files."""
    return load_config(empty_root, None)


@pytest.fixture
def make_config(empty_root: Path) -> Callable[[str], EffectiveConfig]:
    """Write ``.shockharness.toml`` with ``body`` under ``[tool.shockharness]`` and load it."""

    def build(body: str) -> EffectiveConfig:
        (empty_root / ".shockharness.toml").write_text(
            "[tool.shockharness]\n" + body, encoding="utf-8"
        )
        return load_config(empty_root, None)

    return build


@pytest.fixture
def analyze(strict_config: EffectiveConfig) -> Callable[[str, str], FileResult]:
    def run(text: str, language: str) -> FileResult:
        return analyze_text(
            "<test>", language, text, strict_config, AnalysisOptions(inline_suppressions=True)
        )

    return run


def exceptions_config_toml(section: dict[str, object]) -> str:
    """Render golden-fixture ``rules.exceptions`` settings as a ``.shockharness.toml`` body.

    Supports exactly the shapes the corpus uses: booleans, strings, and a list of
    boundary tables with string values.
    """
    lines = ["[tool.shockharness.rules.exceptions]"]
    for key, value in section.items():
        if key == "boundaries":
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        else:
            lines.append(f"{key} = {json.dumps(value)}")
    boundaries = section["boundaries"] if "boundaries" in section else []
    assert isinstance(boundaries, list)
    for boundary in boundaries:
        lines.append("[[tool.shockharness.rules.exceptions.boundaries]]")
        for key, value in boundary.items():
            lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def fixture_config(name: str, expected: dict[str, object], root: Path) -> EffectiveConfig:
    """The configuration a golden fixture is analyzed under: strict, plus its own settings."""
    body = ""
    if "exceptions" in expected:
        section = expected["exceptions"]
        assert isinstance(section, dict)
        body = exceptions_config_toml(section)
    (root / ".shockharness.toml").write_text("[tool.shockharness]\n" + body, encoding="utf-8")
    return load_config(root, None)


def finding_tuples(result: FileResult) -> list[tuple[str, int, int]]:
    return [(f.rule_id, f.span.line, f.span.column) for f in result.findings]


def language_for_fixture(name: str) -> str:
    if name.endswith(".py"):
        return "python"
    return "javascript"
