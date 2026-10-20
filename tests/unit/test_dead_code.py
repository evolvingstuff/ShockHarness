"""DEAD001 and DEAD002: functions nothing in production reaches, reported by cluster."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = (
    '[tool.shockharness]\nprofile = "strict"\n'
    'include = ["app/**/*.py", "app/**/*.js", "tests/**/*.py"]\n'
    "\n[tool.shockharness.rules.dead_code]\nenabled = true\n"
)


def write(root: Path, files: dict[str, str], config: str = CONFIG) -> None:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def dead(
    root: Path, files: dict[str, str], config: str = CONFIG, target: str = ""
) -> list[tuple[str, str, str]]:
    """(rule, unit, message) of each DEAD finding, analyzing ``root / target``."""
    write(root, files, config)
    report = analyze_paths([root / target], root, load_config(root, None), OPTIONS)
    return [
        (f.rule_id, f.scope, f.message) for f in report.findings if f.rule_id.startswith("DEAD")
    ]


ENTRY = "from app.render import render\n\n\ndef main():\n    return render()\n\n\nmain()\n"


def test_a_dead_cluster_is_one_finding_at_its_head(tmp_path: Path) -> None:
    render = (
        "def render():\n    return 'page'\n\n\n"
        "def build_tree(notes):\n    return [highlight(n) for n in notes]\n\n\n"
        "def highlight(note):\n    return mark(note)\n\n\n"
        "def mark(text):\n    return text\n"
    )
    found = dead(tmp_path, {"app/main.py": ENTRY, "app/render.py": render})
    assert [(rule, unit) for rule, unit, _ in found] == [("DEAD001", "build_tree")]
    message = found[0][2]
    assert "2 more functions are reachable only through it: highlight, mark" in message


def test_code_only_tests_reach_is_dead002(tmp_path: Path) -> None:
    render = (
        "def render():\n    return 'page'\n\n\n"
        "def build_tree(notes):\n    return [highlight(n) for n in notes]\n\n\n"
        "def highlight(note):\n    return note\n\n\n"
        "def legacy(note):\n    return note\n"
    )
    test = (
        "from app.render import highlight, legacy\n\n\n"
        "def test_highlight():\n    assert highlight('x') == 'x'\n\n\n"
        "def test_legacy():\n    assert legacy('x') == 'x'\n"
    )
    files = {"app/main.py": ENTRY, "app/render.py": render, "tests/test_render.py": test}
    found = {unit: (rule, message) for rule, unit, message in dead(tmp_path, files)}
    assert sorted(found) == ["build_tree", "legacy"]
    assert found["legacy"][0] == "DEAD002"
    assert found["build_tree"][0] == "DEAD001"
    assert "tests still call highlight" in found["build_tree"][1]


@pytest.mark.parametrize(
    "module",
    [
        "@app.route('/x')\ndef handler():\n    return 1\n",
        "__all__ = ['handler']\n\n\ndef handler():\n    return 1\n",
        "HANDLERS = {'x': lambda: None}\n\n\ndef handler():\n    return 1\n\n\n"
        "HANDLERS['y'] = handler\n",
        "import threading\n\n\ndef handler():\n    return 1\n\n\n"
        "threading.Thread(target=handler)\n",
        "class Store:\n    def handler(self):\n        return 1\n\n\ncallback = Store().handler\n",
        "class Store:\n    def handler(self):\n        return 1\n\n\n"
        "found = getattr(Store(), 'handler')\n",
        "from typing import Annotated\n\n\ndef handler():\n    return 1\n\n\n"
        "def route(token: Annotated[str, Depends(handler)]):\n    return token\n\n\n"
        "app.get('/')(route)\n",
        "from html.parser import HTMLParser\n\n\nclass Parser(HTMLParser):\n"
        "    def handle_data(self, data):\n        return data\n",
        "def outer():\n    class Handler(Base):\n        def log_message(self):\n"
        "            return 1\n    return Handler\n\n\nouter()\n",
        "class Thing:\n    def __repr__(self):\n        return 'thing'\n",
        # MetaList's false positives in 0.17.0:
        "class Guard:\n    def check(self, x):\n        return x\n\n\n"
        "def build(x):\n    return Guard(\n        x\n    ).check(x)\n\n\nbuild(1)\n",
        "from http.server import ThreadingHTTPServer\n\n\n"
        "class Bounded(ThreadingHTTPServer):\n    pass\n\n\n"
        "class Proxy(Bounded):\n    def server_bind(self):\n        return 1\n",
        "import sys\n\n\nclass Stream:\n    def isatty(self):\n        return False\n\n\n"
        "_stream: Stream | None = None\n\n\ndef install():\n    global _stream\n"
        "    _stream = Stream()\n    sys.stdout = _stream\n\n\ninstall()\n",
    ],
)
def test_what_reaches_a_function_without_a_call(tmp_path: Path, module: str) -> None:
    assert dead(tmp_path, {"app/main.py": module}) == []


def test_an_entry_point_glob_is_a_root(tmp_path: Path) -> None:
    module = "def _migration_1_to_2():\n    return 1\n"
    config = CONFIG + 'entry_points = ["app/db.py::_migration_*"]\n'
    assert dead(tmp_path, {"app/db.py": module}, config) == []
    assert [u for _, u, _ in dead(tmp_path / "plain", {"app/db.py": module})] == [
        "_migration_1_to_2"
    ]


def test_overrides_live_and_die_together(tmp_path: Path) -> None:
    module = (
        "class Command:\n    def run(self):\n        return self.describe()\n\n"
        "    def describe(self):\n        return 'base'\n\n    def unused(self):\n"
        "        return 1\n\n\n"
        "class Create(Command):\n    def describe(self):\n        return 'create'\n\n"
        "    def unused(self):\n        return 2\n\n\n"
        "Create().run()\n"
    )
    found = dead(tmp_path, {"app/main.py": module})
    # describe is called through self on the base: the override is alive too. The two
    # unused methods are one family, one finding.
    assert len(found) == 1
    assert found[0][1] in ("Command.unused", "Create.unused")
    assert "1 more functions" in found[0][2]


def test_a_reexport_through_all_is_a_use(tmp_path: Path) -> None:
    files = {
        "app/impl.py": "def helper():\n    return 1\n",
        "app/api.py": "from app.impl import helper\n\n__all__ = ['helper']\n",
    }
    assert dead(tmp_path, files) == []


def test_a_partial_run_judges_nothing(tmp_path: Path) -> None:
    files = {"app/main.py": "def unused():\n    return 1\n", "app/other.py": "X = 1\n"}
    assert len(dead(tmp_path, files)) == 1
    assert dead(tmp_path, files, target="app/main.py") == []


def test_off_by_default(tmp_path: Path) -> None:
    config = '[tool.shockharness]\nprofile = "strict"\ninclude = ["app/**/*.py"]\n'
    assert dead(tmp_path, {"app/main.py": "def unused():\n    return 1\n"}, config) == []


def test_javascript(tmp_path: Path) -> None:
    helpers = (
        "export function used() { return 1; }\n"
        "export function unused() { return 2; }\n"
        "function onResize() { return 3; }\n"
        "window.addEventListener('resize', onResize);\n"
    )
    panel = (
        "import { used } from './helpers.js';\n"
        "class Panel {\n"
        "  constructor() { this._h = this._h.bind(this); document.body.onclick = this._h; }\n"
        "  _h() { return used(); }\n"
        "  stale() { return 4; }\n"
        "}\n"
        "new Panel();\n"
    )
    found = dead(tmp_path, {"app/helpers.js": helpers, "app/panel.js": panel})
    assert sorted(unit for _, unit, _ in found) == ["Panel.stale", "unused"]


def test_relaxing_it_is_a_loosening(tmp_path: Path) -> None:
    write(tmp_path, {})
    before = load_config(tmp_path, None).values
    (tmp_path / ".shockharness.toml").write_text(
        CONFIG + 'entry_points = ["app/x.py::*"]\nroles = []\n', encoding="utf-8"
    )
    after = load_config(tmp_path, None)
    messages = [m.message for m in loosenings(before, frozenset(), after.values, after.deviations)]
    assert any("rules.dead_code.entry_points adds 'app/x.py::*'" in m for m in messages)
    assert any("rules.dead_code.roles no longer lists 'production'" in m for m in messages)
    (tmp_path / ".shockharness.toml").write_text(
        CONFIG.replace("enabled = true", "enabled = false"), encoding="utf-8"
    )
    off = load_config(tmp_path, None)
    messages = [m.message for m in loosenings(before, frozenset(), off.values, off.deviations)]
    assert any("rules.dead_code.enabled changed from True to False" in m for m in messages)


def test_a_project_scripts_target_is_a_root(tmp_path: Path) -> None:
    files = {
        "app/main.py": "def cli():\n    return 1\n",
        "pyproject.toml": '[project]\nname = "x"\n\n[project.scripts]\nx = "app.main:cli"\n',
    }
    assert dead(tmp_path, files) == []


def test_an_exported_instance_and_a_reexport_reach_their_functions(tmp_path: Path) -> None:
    files = {
        "app/state.js": (
            "class Store {\n  createScope() { return 1; }\n}\n"
            "export const State = Object.freeze(new Store());\n"
        ),
        "app/use.js": (
            "import { State } from './state.js';\n"
            "export function use() { return State.createScope(); }\nuse();\n"
        ),
        "app/__init__.py": "",
        "app/impl.py": "def helper():\n    return 1\n",
        "app/api.py": "from app.impl import helper\n",
        "app/main.py": (
            "from app.api import helper\n\n\ndef main():\n    return helper()\n\n\nmain()\n"
        ),
    }
    # Inside a function both calls resolve to "path::name" external targets, which is how
    # the graph records an exported instance's method and a re-exported function.
    assert dead(tmp_path, files) == []


def test_a_revision_export_is_judged_against_its_own_files(tmp_path: Path) -> None:
    """``diff`` analyzes an exported revision with the working tree's configuration: the
    whole-project test must discover the export, not the working tree (where a file the
    revision lacks would make every run look partial)."""
    from shockharness.analysis import analyze_files
    from shockharness.discovery import discover

    files = {"app/main.py": "def unused():\n    return 1\n"}
    work, export = tmp_path / "work", tmp_path / "export"
    write(work, {**files, "app/added_later.py": "X = 1\n"})
    write(export, files)
    config = load_config(work, None)
    outcome = analyze_files(discover(export, [export], config).files, config, OPTIONS, None)
    found = [f.rule_id for r in outcome.files for f in r.findings if f.rule_id.startswith("DEAD")]
    assert found == ["DEAD001"]
