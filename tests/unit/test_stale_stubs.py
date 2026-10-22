"""VERIFY005: a test's stub that the code the test calls no longer reaches."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = '[tool.shockharness]\nprofile = "strict"\ninclude = ["app/**/*.py", "tests/**/*.py"]\n'

# The refactor: open_all used to call launch, and now calls start.
APP = (
    "def launch(name):\n    return name\n\n\n"
    "def start(name):\n    return name\n\n\n"
    "def open_all(names):\n    return [start(n) for n in names]\n"
)


def stale(root: Path, test: str, app: str = APP) -> list[tuple[int, str]]:
    files = {
        ".shockharness.toml": CONFIG,
        "app/__init__.py": "",
        "app/switcher.py": app,
        "tests/test_switcher.py": test,
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [(f.span.line, f.message) for f in report.findings if f.rule_id == "VERIFY005"]


def test_a_stub_of_a_function_the_code_no_longer_calls(tmp_path: Path) -> None:
    test = (
        "from app import switcher\n\n\n"
        "def test_open_all(monkeypatch):\n"
        "    monkeypatch.setattr(switcher, 'launch', lambda name: name)\n"
        "    assert switcher.open_all(['a']) == ['a']\n"
    )
    found = stale(tmp_path, test)
    assert [line for line, _ in found] == [5]
    assert "the stub replaces launch (app/switcher.py)" in found[0][1]
    assert "test_open_all calls no longer reaches" in found[0][1]


def test_a_stub_the_code_reaches_is_fine(tmp_path: Path) -> None:
    test = (
        "from app import switcher\n\n\n"
        "def test_open_all(monkeypatch):\n"
        "    monkeypatch.setattr(switcher, 'start', lambda name: name)\n"
        "    assert switcher.open_all(['a']) == ['a']\n"
    )
    assert stale(tmp_path, test) == []


def test_the_dotted_and_patch_forms_through_a_helper_and_a_fixture(tmp_path: Path) -> None:
    test = (
        "import pytest\n"
        "from unittest import mock\n"
        "from app import switcher\n\n\n"
        "@pytest.fixture\n"
        "def stubbed(monkeypatch):\n"
        "    monkeypatch.setattr('app.switcher.launch', lambda name: name)\n\n\n"
        "def _stub_start(monkeypatch):\n"
        "    monkeypatch.setattr(switcher, 'start', lambda name: name)\n"
        "    monkeypatch.setattr(switcher, 'launch', lambda name: name)\n\n\n"
        "def test_with_fixture(stubbed):\n"
        "    assert switcher.open_all(['a']) == ['a']\n\n\n"
        "def test_with_helper(monkeypatch):\n"
        "    _stub_start(monkeypatch)\n"
        "    assert switcher.open_all(['a']) == ['a']\n\n\n"
        "@mock.patch('app.switcher.launch')\n"
        "def test_with_decorator(launch):\n"
        "    assert switcher.open_all(['a']) == ['a']\n"
    )
    # Every stub of launch is stale (the fixture's, the helper's, the decorator's); the
    # helper's stub of start is reached.
    assert [line for line, _ in stale(tmp_path, test)] == [8, 13, 25]


def test_a_patch_of_a_name_the_code_imports_inside_a_function(tmp_path: Path) -> None:
    # MetaList's connect_to_ai: `from M import N` in the function body reads M.N at call
    # time, so a patch of M.N is in effect whenever the function runs (reported by MetaList
    # against 0.21.0: 8 such stubs in 5 tests, all reached). The shape of its route.
    files = {
        ".shockharness.toml": CONFIG,
        "app/__init__.py": "",
        "app/routes/__init__.py": "",
        "app/inference.py": (
            "class Adapter:\n    def __init__(self, key):\n        self.key = key\n"
        ),
        "app/setup.py": (
            "class Guard:\n    def __init__(self, inner):\n        self.inner = inner\n\n\n"
            "def connect(*, key):\n    from app.inference import Adapter\n"
            "    return Guard(inner=Adapter(key))\n"
        ),
        "app/routes/ai.py": (
            "from app.setup import connect\n\n\n"
            "def _require(*, key):\n    try:\n        return connect(key=key)\n"
            "    except KeyError as exc:\n        raise ValueError(key) from exc\n\n\n"
            "def route(*, key):\n    return _require(key=key)\n"
        ),
        "tests/test_route.py": (
            "from app import inference\nfrom app.routes import ai as ai_routes\n\n\n"
            "def test_route(monkeypatch):\n"
            "    monkeypatch.setattr(inference, 'Adapter', lambda key: key)\n"
            "    assert ai_routes.route(key='k').inner == 'k'\n"
        ),
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    report = analyze_paths([tmp_path], tmp_path, load_config(tmp_path, None), OPTIONS)
    assert [f for f in report.findings if f.rule_id == "VERIFY005"] == []


def test_tripwires_are_not_reported(tmp_path: Path) -> None:
    test = (
        "import pytest\n"
        "from unittest import mock\n"
        "from app import switcher\n\n\n"
        "def test_never_launches(monkeypatch):\n"
        "    launched = []\n"
        "    monkeypatch.setattr(switcher, 'launch', lambda name: launched.append(name))\n"
        "    monkeypatch.setattr('app.switcher.launch', lambda name: pytest.fail('launched'))\n"
        "    with mock.patch.object(switcher, 'launch', side_effect=AssertionError('no')):\n"
        "        switcher.open_all(['a'])\n"
        "    assert launched == []\n"
    )
    assert stale(tmp_path, test) == []


def test_partial_runs_and_unresolved_targets_are_not_judged(tmp_path: Path) -> None:
    test = (
        "import os\n"
        "from app import switcher\n\n\n"
        "def test_open_all(monkeypatch):\n"
        "    monkeypatch.setattr(os, 'getcwd', lambda: '/')\n"
        "    monkeypatch.setattr(switcher, 'launch', lambda name: name)\n"
        "    assert switcher.open_all(['a']) == ['a']\n"
    )
    assert [line for line, _ in stale(tmp_path, test)] == [7]
    report = analyze_paths([tmp_path / "tests"], tmp_path, load_config(tmp_path, None), OPTIONS)
    assert [f for f in report.findings if f.rule_id == "VERIFY005"] == []


def test_a_stale_stub_kept_on_purpose_can_be_suppressed(tmp_path: Path) -> None:
    test = (
        "from app import switcher\n\n\n"
        "def test_open_all(monkeypatch):\n"
        "    monkeypatch.setattr(switcher, 'launch', lambda name: name)"
        '  # shockharness: ignore[VERIFY005] reason="reached through getattr"\n'
        "    assert switcher.open_all(['a']) == ['a']\n"
    )
    root = tmp_path
    stale(root, test)
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    found = [f for f in report.findings if f.rule_id == "VERIFY005"]
    assert len(found) == 1 and found[0].suppression is not None
    assert not [f for f in report.findings if f.rule_id == "SUPP001"]
