"""EXC005: a declared catch boundary that no catch in its files uses."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
READER = (
    "def read(path: str) -> bytes:\n"
    "    try:\n"
    "        data = open(path, 'rb')\n"
    "    except OSError as exc:\n"
    "        raise RuntimeError(path) from exc\n"
    "    return data.read()\n"
)
CONFIG = """[tool.shockharness]

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/reader.py"
language = "python"
exceptions = ["OSError", "ValueError"]
reason = "reading the input"

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/cli.py"
language = "python"
exception = "OSError"
reason = "declared ahead of the code"

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/later.py"
language = "python"
exception = "OSError"
reason = "the file does not exist yet"

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/**"
language = "python"
exception = "OSError"
reason = "a glob: used by reader.py"
"""


def project(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "reader.py").write_text(READER, encoding="utf-8")
    (root / "src" / "cli.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / ".shockharness.toml").write_text(CONFIG, encoding="utf-8")


def exc005(root: Path, paths: list[Path]) -> list[tuple[int, str, str]]:
    config = load_config(root, None)
    report = analyze_paths(paths, root, config, OPTIONS)
    return [
        (f.span.line, f.severity, f.message.split(" approves catching ")[1].split(",")[0])
        for f in report.findings
        if f.rule_id == "EXC005"
    ]


def test_an_exception_no_covered_catch_catches_is_reported(empty_root: Path) -> None:
    project(empty_root)
    assert exc005(empty_root, [empty_root]) == [
        (4, "warning", "ValueError in src/reader.py (python)"),
        (10, "warning", "OSError in src/cli.py (python)"),
    ]


def test_a_partial_run_judges_only_boundaries_whose_files_were_all_analyzed(
    empty_root: Path,
) -> None:
    project(empty_root)
    # reader.py alone: its own boundary is judged; cli.py's and the glob's are not.
    assert exc005(empty_root, [empty_root / "src" / "reader.py"]) == [
        (4, "warning", "ValueError in src/reader.py (python)")
    ]


def test_the_family_switch_turns_it_off(empty_root: Path) -> None:
    project(empty_root)
    config = empty_root / ".shockharness.toml"
    text = config.read_text(encoding="utf-8")
    off = "[tool.shockharness]\n\n[tool.shockharness.rules.exceptions]\nenabled = false\n"
    config.write_text(text.replace("[tool.shockharness]\n", off, 1), encoding="utf-8")
    assert exc005(empty_root, [empty_root]) == []
