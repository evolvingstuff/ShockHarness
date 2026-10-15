"""Shared fixtures. Tests never need network, git, or an LLM."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, FileResult, analyze_text
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
            "<test>",
            language,
            text,
            strict_config,
            AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED),
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
    boundaries: list[dict[str, str]] = []
    if "boundaries" in section:
        listed = section["boundaries"]
        assert isinstance(listed, list)
        boundaries = listed
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


def without_cache_block(rendered_json: str) -> str:
    """A JSON report with ``coverage.cache`` removed: the one block that legitimately
    differs between a cold and a warm run over the same tree (docs/configuration.md,
    Cache). Determinism comparisons use this; everything else must be byte-identical."""
    data = json.loads(rendered_json)
    del data["coverage"]["cache"]
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def without_cache_line(rendered_text: str) -> str:
    """Text output without the ``  cache: ...`` trailer line (cold and warm runs differ there)."""
    return "".join(
        line for line in rendered_text.splitlines(keepends=True) if not line.startswith("  cache: ")
    )


def finding_tuples(result: FileResult) -> list[tuple[str, int, int]]:
    return [(f.rule_id, f.span.line, f.span.column) for f in result.findings]


def language_for_fixture(name: str) -> str:
    if name.endswith(".py"):
        return "python"
    return "javascript"


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity; tests never touch the user's git config."""
    completed = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")


def commit_all(repo: Path, message: str, date: str, author_email: str) -> str:
    """Stage everything and commit with fixed author and committer dates; return the hash."""
    git(repo, "add", "-A")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_COMMITTER_NAME": "Test",
    }
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", message],
        cwd=repo,
        env=env,
        capture_output=True,
        check=True,
    )
    return git(repo, "rev-parse", "HEAD").strip()
