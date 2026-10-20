"""DUP001 and DUP002: helpers written out in several files, and copies that drifted."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = (
    '[tool.shockharness]\nprofile = "strict"\n'
    'include = ["app/**/*.py", "app/**/*.js", "tests/**/*.py"]\n'
    "\n[tool.shockharness.rules.duplicates]\nenabled = true\nmin_tokens = 10\n"
)

ESCAPE = (
    "function escapeHtml(value) {\n"
    "  if (typeof value !== 'string') {\n"
    "    throw new Error('escapeHtml requires a string');\n"
    "  }\n"
    "  const text = value.replaceAll('&', '&amp;');\n"
    "  return text.replaceAll('<', '&lt;');\n"
    "}\n"
)
# The drifted copy: another name, another local, and an empty string instead of a throw.
DRIFTED = (
    "function _escapeHtml(input) {\n"
    "  if (typeof input !== 'string') {\n"
    "    return '';\n"
    "  }\n"
    "  const out = input.replaceAll('&', '&amp;');\n"
    "  return out.replaceAll('<', '&lt;');\n"
    "}\n"
)
RUNNING = (
    "def _is_running(pid):\n"
    '    """Whether the process exists."""\n'
    "    capture = Capture(boundary='{path}:_is_running:capture')\n"
    "    with capture:\n"
    "        os.kill(pid, 0)\n"
    "    return not capture.caught\n"
)


def found(root: Path, files: dict[str, str], config: str = CONFIG) -> list[tuple[str, str, str]]:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [(f.rule_id, f.path, f.message) for f in report.findings if f.rule_id.startswith("DUP")]


def test_copies_are_one_finding_at_the_first(tmp_path: Path) -> None:
    files = {"app/a.js": ESCAPE, "app/b.js": ESCAPE, "app/c.js": ESCAPE}
    result = found(tmp_path, files)
    assert [(rule, path) for rule, path, _ in result] == [("DUP001", "app/a.js")]
    assert "written out in 3 files" in result[0][2]
    assert "also app/b.js:1, app/c.js:1" in result[0][2]


def test_a_copy_labelling_its_own_file_and_renaming_locals_is_a_copy(tmp_path: Path) -> None:
    files = {
        "app/a.py": RUNNING.format(path="app/a.py"),
        "app/b.py": RUNNING.format(path="app/b.py").replace("pid", "process_id"),
    }
    assert [(rule, path) for rule, path, _ in found(tmp_path, files)] == [("DUP001", "app/a.py")]


def test_drifted_copies_are_dup002_with_their_difference(tmp_path: Path) -> None:
    files = {"app/a.js": ESCAPE, "app/b.js": ESCAPE, "app/c.js": DRIFTED}
    result = {rule: message for rule, _, message in found(tmp_path, files)}
    assert sorted(result) == ["DUP001", "DUP002"]
    assert "escapeHtml exists in 2 versions" in result["DUP002"]
    assert "has `throw new Error('escapeHtml requires a string');`" in result["DUP002"]
    assert "has `return '';`" in result["DUP002"]


def test_what_is_not_reported(tmp_path: Path) -> None:
    # One file, a test file, a tiny function, a different body: no finding.
    files = {
        "app/a.js": ESCAPE + ESCAPE.replace("escapeHtml(", "escapeAgain("),
        "tests/test_a.py": RUNNING.format(path="x"),
        "app/b.py": RUNNING.format(path="x"),
        "app/c.js": "function tiny(a) {\n  const b = a;\n  return b;\n}\n",
        "app/d.js": "function tiny(a) {\n  const b = a;\n  return b;\n}\n",
        "app/e.py": "def other(x):\n    y = x + 1\n    z = y * x\n    return z - y\n",
    }
    assert found(tmp_path, files, CONFIG.replace("min_tokens = 10", "min_tokens = 20")) == []


def test_overrides_and_constructors_are_not_drift(tmp_path: Path) -> None:
    base = "class Command:\n    def run(self):\n        return self.execute()\n"
    undo = (
        "from app.base import Command\n\n\nclass Undo(Command):\n    def execute(self):\n"
        "        state = load()\n        state.undo()\n        save(state)\n"
        "        return 'undone'\n"
    )
    redo = undo.replace("Undo", "Redo").replace("undo", "redo")
    files = {"app/base.py": base, "app/undo.py": undo, "app/redo.py": redo}
    assert [r for r, _, _ in found(tmp_path, files)] == []


def test_off_by_default_and_a_partial_run(tmp_path: Path) -> None:
    files = {"app/a.js": ESCAPE, "app/b.js": ESCAPE}
    off = '[tool.shockharness]\nprofile = "strict"\ninclude = ["app/**/*.js"]\n'
    assert found(tmp_path / "off", files, off) == []
    root = tmp_path / "partial"
    found(root, files)
    report = analyze_paths([root / "app/a.js"], root, load_config(root, None), OPTIONS)
    assert [f for f in report.findings if f.rule_id.startswith("DUP")] == []


def test_relaxing_it_is_a_loosening(tmp_path: Path) -> None:
    (tmp_path / ".shockharness.toml").write_text(CONFIG, encoding="utf-8")
    before = load_config(tmp_path, None).values
    (tmp_path / ".shockharness.toml").write_text(
        CONFIG.replace("min_tokens = 10", "min_tokens = 40") + "similarity = 0.95\nroles = []\n",
        encoding="utf-8",
    )
    after = load_config(tmp_path, None)
    messages = [m.message for m in loosenings(before, frozenset(), after.values, after.deviations)]
    assert any("rules.duplicates.min_tokens raised from 10 to 40" in m for m in messages)
    assert any("rules.duplicates.similarity raised from 0.85 to 0.95" in m for m in messages)
    assert any("rules.duplicates.roles no longer lists 'production'" in m for m in messages)


def test_versions_over_different_annotated_types_are_parallel_not_drift(tmp_path: Path) -> None:
    body = (
        "    text = ' '.join(render(node).split())\n"
        "    if len(text) > LIMIT:\n"
        "        return text[:LIMIT] + '...'\n"
        "    return text\n"
    )
    typed = {
        "app/py_side.py": "def excerpt(node: ast.AST) -> str:\n" + body,
        "app/js_side.py": "def excerpt(node: Node) -> str:\n" + body.replace("+ '...'", ""),
        "app/same_a.py": "def tag(node: Node) -> str:\n" + body.replace("LIMIT", "WIDTH"),
        "app/same_b.py": "def tag(node: Node) -> str:\n"
        + body.replace("LIMIT", "WIDTH").replace("+ '...'", ""),
    }
    result = found(tmp_path, typed)
    # Same types and alike: drift. Different types: parallel implementations, nothing.
    assert [(rule, path) for rule, path, _ in result] == [("DUP002", "app/same_a.py")]
    # Identical bodies over different types are not one copy group either.
    copies = {
        "app/a.py": "def excerpt(node: ast.AST) -> str:\n" + body,
        "app/b.py": "def excerpt(node: Node) -> str:\n" + body,
    }
    assert found(tmp_path / "copies", copies) == []
