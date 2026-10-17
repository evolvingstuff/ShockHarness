"""DEF005 and an entry point's exit status inside a declared boundary (decision 37)."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.rules.defaults import module_names, script_functions

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
HEADER = (
    "import sys\n\nEXIT_OK = 0\nEXIT_UNREADABLE = 2\nNOTHING = 0\n\n\n"
    "class InputError(Exception):\n    pass\n\n\n"
    "def read(path: str) -> str:\n    raise InputError(path)\n"
)


def handler(name: str, returned: str) -> str:
    return (
        f"\n\ndef {name}() -> int:\n    try:\n        read('x')\n"
        "    except InputError as exc:\n        print(exc, file=sys.stderr)\n"
        f"        return {returned}\n    return EXIT_OK\n"
    )


BOUNDARY = """[tool.shockharness]

[[tool.shockharness.rules.exceptions.boundaries]]
path = "app/cli.py"
language = "python"
exception = "app.cli.InputError"
reason = "process edge: unreadable input exits 2"
"""


def def005_functions(root: Path, code: str, config: str, pyproject: str) -> list[str]:
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "cli.py").write_text(code, encoding="utf-8")
    (root / ".shockharness.toml").write_text(config, encoding="utf-8")
    if pyproject != "":
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [f.scope for f in report.findings if f.rule_id == "DEF005"]


def test_main_and_main_guard_callees_may_return_a_named_exit_status(empty_root: Path) -> None:
    code = (
        HEADER
        + handler("main", "EXIT_UNREADABLE")
        + handler("cli", "EXIT_UNREADABLE")
        + handler("helper", "EXIT_UNREADABLE")  # not an entry point: reported
        + handler("zero", "NOTHING")  # a zero is no failure status: reported
        + "\n\nif __name__ == '__main__':\n    sys.exit(cli())\n"
    )
    assert def005_functions(empty_root, code, BOUNDARY, "") == ["helper", "zero"]


def test_project_scripts_name_entry_points(empty_root: Path) -> None:
    code = HEADER + handler("run", "EXIT_UNREADABLE")
    assert def005_functions(empty_root, code, BOUNDARY, "") == ["run"]
    scripts = '[project]\nname = "x"\nversion = "0"\n\n[project.scripts]\nx = "app.cli:run"\n'
    assert def005_functions(empty_root, code, BOUNDARY, scripts) == []


def test_without_a_boundary_the_handler_is_still_a_default(empty_root: Path) -> None:
    code = HEADER + handler("main", "EXIT_UNREADABLE")
    assert def005_functions(empty_root, code, "[tool.shockharness]\n", "") == ["main"]


def test_module_names_follow_the_src_layout() -> None:
    assert module_names("src/pkg/cli.py") == frozenset({"src.pkg.cli", "pkg.cli"})
    assert module_names("pkg/__init__.py") == frozenset({"pkg"})
    assert script_functions(["pkg.cli:main", "other:run"], "src/pkg/cli.py") == {"main"}
