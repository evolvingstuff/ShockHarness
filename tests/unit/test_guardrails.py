"""H3 guardrails: EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001."""

from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
H3 = ("EXC004", "STUB001", "STUB002", "ASSERT001", "ASSERT002", "BOOL001", "STATE001", "IMPORT001")


def run(config: EffectiveConfig, path: str, text: str) -> FileResult:
    language = "python" if path.endswith(".py") else "javascript"
    return analyze_text(path, language, text, config, OPTIONS)


def rows(result: FileResult) -> list[tuple[str, int, str]]:
    return [(f.rule_id, f.span.line, f.severity) for f in result.findings if f.rule_id in H3]


# -- EXC004 ------------------------------------------------------------------------------


def test_exc004_python_exits_from_finally(strict_config: EffectiveConfig) -> None:
    text = (
        "def a(f):\n"
        "    try:\n        return f()\n    finally:\n        return NONE\n\n\n"  # 5
        "def b(fs):\n"
        "    for f in fs:\n"
        "        try:\n            f()\n        finally:\n            break\n\n\n"  # 13
        "def c(fs, gs):\n"
        "    try:\n        run(fs)\n    finally:\n"
        "        for g in gs:\n            continue\n"  # loop of its own: fine
        "        def inner():\n            return g\n"  # nested scope: fine
        "        while gs:\n            break\n        else:\n            pass\n"
    )
    assert rows(run(strict_config, "a.py", text)) == [
        ("EXC004", 5, "warning"),
        ("EXC004", 13, "warning"),
    ]


def test_exc004_python_break_in_a_loop_else_leaves_the_block(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "for item in items:\n"
        "    try:\n        use(item)\n    finally:\n"
        "        for other in items:\n            pass\n        else:\n            break\n"
    )
    assert rows(run(strict_config, "a.py", text)) == [("EXC004", 8, "warning")]


def test_exc004_javascript_exits_and_labels(strict_config: EffectiveConfig) -> None:
    text = (
        "export function f(g) {\n"
        "  try { g(); } finally { return 1; }\n"  # 2
        "}\n"
        "outer: for (const x of xs) {\n"
        "  try { g(x); } finally {\n"
        "    break outer;\n"  # 6
        "    for (;;) { break; }\n"
        "    switch (x) { case 1: break; }\n"
        "    inner: for (;;) { continue inner; }\n"
        "    const h = () => { return 2; };\n"
        "  }\n"
        "}\n"
    )
    assert rows(run(strict_config, "a.js", text)) == [
        ("EXC004", 2, "warning"),
        ("EXC004", 6, "warning"),
    ]


def test_exc004_applies_to_every_role_and_follows_the_exceptions_switch(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    text = (
        "try:\n    f()\nfinally:\n    pass\n"
        "while x:\n    try:\n        f()\n    finally:\n        continue\n"
    )
    on = make_config("")
    assert rows(run(on, "tests/test_a.py", text)) == [("EXC004", 9, "warning")]
    off = make_config("[tool.shockharness.rules.exceptions]\nenabled = false\n")
    assert rows(run(off, "tests/test_a.py", text)) == []


# -- STUB001 -----------------------------------------------------------------------------


def test_stub001_python_placeholders_and_abstract_api(strict_config: EffectiveConfig) -> None:
    text = (
        "from abc import ABC, abstractmethod\n"
        "from typing import Protocol, overload\n\n\n"
        "def todo():\n    raise NotImplementedError\n\n\n"  # 6
        "def called():\n    raise NotImplementedError('later')\n\n\n"  # 10
        "def wrong():\n    raise NotImplemented\n\n\n"  # 14
        "def empty():\n    '''Docs.'''\n    pass\n\n\n"  # 17
        "def docs_only():\n    '''Only a docstring is not a filler.'''\n\n\n"
        "class Base(ABC):\n"
        "    @abstractmethod\n    def run(self):\n        raise NotImplementedError\n\n"
        "    def hook(self):\n        ...\n\n\n"
        "class Shape(Protocol):\n    def area(self) -> float: ...\n\n\n"
        "class Plain:\n"
        "    @abstractmethod\n    def a(self): ...\n\n"
        "    @overload\n    def b(self, x: int) -> int: ...\n\n"
        "    def c(self):\n        pass\n"
    )
    result = run(strict_config, "src/a.py", text)
    assert rows(result) == [
        ("STUB001", 6, "warning"),
        ("STUB001", 10, "warning"),
        ("STUB001", 14, "warning"),
        ("STUB001", 17, "warning"),
        ("STUB001", 46, "warning"),
    ]
    messages = [f.message for f in result.findings if f.rule_id == "STUB001"]
    assert messages[2].startswith("wrong raises NotImplemented, which is not an exception")
    assert messages[4].startswith("Plain.c has an empty body")


def test_stub001_javascript_not_implemented_throws(strict_config: EffectiveConfig) -> None:
    text = (
        'export function a() { throw new Error("Not implemented"); }\n'
        'export function b() { throw new TypeError("not yet implemented: refunds"); }\n'
        'export function c() { throw new Error("TODO: wire the API"); }\n'
        'export function d() { throw new Error("unimplemented"); }\n'
        'export function e() { throw new Error("implemented elsewhere"); }\n'
        'export function f() { throw new Failure("not implemented"); }\n'
        "export function g() {}\n"
        'export function h() { throw new Error("Todo toggle missing from the toolbar"); }\n'
        'export function i() { throw new Error("todo(alice): later"); }\n'  # 9
        'export function j() { throw new Error("TODO"); }\n'  # 10
    )
    assert [r[1] for r in rows(run(strict_config, "src/a.js", text))] == [1, 2, 3, 4, 9, 10]


def test_stub001_markers_are_opt_in(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = (
        "x = compute()  # TODO: remove\ny = other()  # TODOS are fine\n# FIXME later\n"
        "z = 1  # calls the TODO service, not a marker\n"
    )
    assert rows(run(make_config(""), "src/a.py", text)) == []
    config = make_config('[tool.shockharness.rules.stubs]\nmarkers = ["TODO", "FIXME"]\n')
    assert rows(run(config, "src/a.py", text)) == [
        ("STUB001", 1, "warning"),
        ("STUB001", 3, "warning"),
    ]


# -- STUB002 -----------------------------------------------------------------------------


def test_stub002_python_imports(strict_config: EffectiveConfig) -> None:
    text = (
        "from unittest import mock\n"  # 1
        "import unittest.mock as um\n"  # 2
        "from tests.fakes import FakeClient\n"  # 3
        "from .fixtures import data\n"  # 4
        "from . import conftest\n"  # 5
        "import fakerlib\n"
        "from unittest import TestCase\n"
        "from app.testing_utils import x\n"
        "import faker.providers\n"  # 9
    )
    result = run(strict_config, "src/a.py", text)
    assert [r[1] for r in rows(result)] == [1, 2, 3, 4, 5, 9]
    first = next(f for f in result.findings if f.rule_id == "STUB002")
    assert first.message.startswith("production code imports unittest.mock:")


def test_stub002_javascript_imports(strict_config: EffectiveConfig) -> None:
    text = (
        'import sinon from "sinon";\n'  # 1
        'import { faker } from "@faker-js/faker/locale/en";\n'  # 2
        'import { api } from "./__mocks__/api.js";\n'  # 3
        'const helper = require("../tests/helper.js");\n'  # 4
        'import fixtures from "fixtures";\n'  # a package named fixtures: not a path
        'import { jestish } from "jest-dom-utils";\n'
    )
    assert [r[1] for r in rows(run(strict_config, "src/a.js", text))] == [1, 2, 3, 4]


def test_stub_rules_follow_roles(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = "from unittest import mock\n\n\ndef f():\n    raise NotImplementedError\n"
    default = make_config("")
    assert rows(run(default, "tests/test_a.py", text)) == []
    assert len(rows(run(default, "src/a.py", text))) == 2
    widened = make_config('[tool.shockharness.rules.stubs]\nroles = ["production", "test"]\n')
    assert len(rows(run(widened, "tests/test_a.py", text))) == 2
    narrowed = make_config("[tool.shockharness.rules.stubs]\nroles = []\n")
    assert rows(run(narrowed, "src/a.py", text)) == []
    assert any("rules.stubs.roles no longer lists 'production'" in d for d in narrowed.deviations)


# -- ASSERT001 ---------------------------------------------------------------------------


def test_assert001_reports_asserts_on_external_input_only(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    """Decision 28: an internal invariant is never reported; an assert on input is."""
    text = (
        "import os\nimport sys\nfrom typing import TYPE_CHECKING\n\n"
        "from flask import request\n\n\n"
        "def f(x, y):\n"
        "    assert x is not None\n"  # 9: an invariant
        "    assert x > 0 and y, 'positive'\n"  # 10: an invariant on parameters
        "    amount = int(request.form['amount'])\n"
        "    assert amount > 0\n"  # 12: input, even after int()
        "    assert os.environ['MODE'] in ('a', 'b')\n"  # 13: configuration
        "    assert isinstance(request.json, dict)\n"  # 14: narrowing, allowed by default
        "    assert len(sys.argv) > 1\n"  # 15: command-line arguments
        "    return check(amount)\n\n\n"
        "def check(value):\n"
        "    assert value < LIMIT\n"  # 20: input from f, across a call
        "    return value\n\n\n"
        "if TYPE_CHECKING:\n    assert False\n"
    )
    guarded = text + "\n\nif sys.flags.optimize:\n    raise SystemExit('no -O')\n"
    default = make_config("")
    found = [
        (f.span.line, f.message)
        for f in run(default, "src/a.py", guarded).findings
        if f.rule_id == "ASSERT001"
    ]
    assert [line for line, _ in found] == [12, 13, 15, 20]
    assert found[0][1].startswith("assert amount > 0 checks external input, flask.request.form")
    assert "(through check)" in found[3][1]
    strict = make_config("[tool.shockharness.rules.assertions]\nallow_type_narrowing = false\n")
    lines = [
        f.span.line for f in run(strict, "src/a.py", guarded).findings if f.rule_id == "ASSERT001"
    ]
    assert lines == [12, 13, 14, 15, 20]
    assert rows(run(default, "tests/test_a.py", guarded)) == []


def test_assert002_asks_for_a_startup_guard(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = (
        "def head(items):\n    assert items, 'the ordering has a head here'\n    return items[0]\n"
    )
    result = run(make_config(""), "src/a.py", text)
    assert rows(result) == [("ASSERT002", 2, "review")]
    message = next(f.message for f in result.findings if f.rule_id == "ASSERT002")
    assert message.startswith("production code relies on 1 assert(s) in 1 file(s)")
    guard = "import sys\n\nif sys.flags.optimize:\n    raise SystemExit('do not run with -O')\n"
    assert rows(run(make_config(""), "src/a.py", guard + text)) == []
    narrowing = "def f(x):\n    assert x is not None\n    return x\n"
    assert rows(run(make_config(""), "src/a.py", narrowing)) == []


# -- BOOL001 -----------------------------------------------------------------------------


def test_bool001_positional_booleans(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = (
        "render(page, True, False)\n"  # 1: two findings
        "toggle(True)\n"  # one argument: clear enough
        "render(page, escape=True)\n"
        "value = config.get('x', False)\n"  # DEF002's
        "call(*args, True)\n"
        "obj.method(a, False)\n"  # 6
    )
    default = make_config("")
    result = run(default, "src/a.py", text)
    assert rows(result) == [
        ("BOOL001", 1, "review"),
        ("BOOL001", 1, "review"),
        ("BOOL001", 6, "review"),
    ]
    assert "positional argument 2 of render(...)" in result.findings[0].message
    allowed = make_config(
        '[tool.shockharness.rules.boolean_arguments]\nallowed_callees = ["get", "render"]\n'
    )
    assert [r[1] for r in rows(run(allowed, "src/a.py", text))] == [6]
    assert any("allowed_callees also permits 'render'" in d for d in allowed.deviations)
    js = "connect(host, true);\nflag(true);\nopen(path, { sync: true });\n"
    assert rows(run(default, "src/a.js", js)) == [("BOOL001", 1, "review")]


def test_bool001_skips_the_expected_value_of_an_assertion(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    # MetaList: 159 of its 353 BOOL001 findings were assertion arguments in browser test
    # scripts outside the test role; the assertion says what the Boolean means.
    default = make_config("")
    text = (
        "self.assertEqual(result, True)\n"
        "assertIs(flag, False)\n"
        "mock.assert_called_with(path, True)\n"
        "render(page, True)\n"  # 4: still reported
    )
    assert rows(run(default, "src/a.py", text)) == [("BOOL001", 4, "review")]
    js = (
        "assert.equal(visible, true);\n"
        "assert.strictEqual(state.open, false, 'closed after Escape');\n"
        "connect(host, true);\n"  # 3: still reported
    )
    assert rows(run(default, "src/a.js", js)) == [("BOOL001", 3, "review")]


# -- STATE001 ----------------------------------------------------------------------------


def test_state001_module_state_written_by_functions(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    text = (
        "_SEEN = set()\n"  # 1
        "_CACHE: dict = {}\n"  # 2
        "LIMITS = [ONE]\n"
        "_COUNT = 0\n"  # 4 (global)
        "\n\n"
        "def mark(key):\n    _SEEN.add(key)\n\n\n"
        "def remember(k, v):\n    _CACHE[k] = v\n\n\n"
        "def bump():\n    global _COUNT\n    _COUNT += 1\n\n\n"
        "def read():\n    return LIMITS[0]\n"
    )
    default = make_config("")
    result = run(default, "src/a.py", text)
    assert [r[1] for r in rows(result)] == [1, 2, 4]
    assert "written by mark" in result.findings[0].message
    allowed = make_config(
        "[[tool.shockharness.rules.module_state.allowed]]\n"
        'path = "src/*.py"\nname = "_CACHE"\nreason = "process-wide memo"\n'
    )
    assert [r[1] for r in rows(run(allowed, "src/a.py", text))] == [1, 4]
    assert any("allowed[0] permits module state '_CACHE'" in d for d in allowed.deviations)
    js = (
        "let counter = 0;\nconst seen = new Set();\n"
        "export function bump() { counter += 1; seen.add(1); }\n"
    )
    assert [r[1] for r in rows(run(default, "src/a.js", js))] == [1, 2]


# -- IMPORT001 ---------------------------------------------------------------------------


def test_import001_python_import_time_effects(strict_config: EffectiveConfig) -> None:
    text = (
        "import subprocess as sp\n"
        "import requests\n"
        "from os import system\n"
        "import threading\n\n"
        "sp.run(['ls'], check=True)\n"  # 6
        "CONFIG = requests.get(URL).json()\n"  # 7
        "system('ls')\n"  # 8
        "\n\n"
        "class Worker:\n    thread = threading.Thread(target=print)\n"  # 12
        "\n\n"
        "def later():\n    sp.run(['ls'], check=True)\n\n\n"
        "def default(x=requests.get(URL)):\n    return x\n\n\n"  # 19
        "if __name__ == '__main__':\n    sp.run(['main'], check=True)\n"
    )
    result = run(strict_config, "src/a.py", text)
    assert rows(result) == [
        ("IMPORT001", 6, "warning"),
        ("IMPORT001", 7, "warning"),
        ("IMPORT001", 8, "warning"),
        ("IMPORT001", 12, "warning"),
        ("IMPORT001", 19, "warning"),
    ]
    assert result.findings[0].message.startswith("subprocess.run runs when the module is imported")


def test_import001_javascript_import_time_effects(strict_config: EffectiveConfig) -> None:
    text = (
        'import { execSync } from "node:child_process";\n'
        'import * as fs from "fs";\n'
        'const cp = require("child_process");\n'
        'execSync("ls");\n'  # 4
        'fs.rmSync("dist", { recursive: true });\n'  # 5
        'const data = await fetch("https://example.invalid");\n'  # 6
        'cp.spawn("x");\n'  # 7
        "class A { static boot = setInterval(tick, PERIOD); later = fetch(URL); }\n"  # 8
        'export function run() { execSync("ls"); }\n'
    )
    assert [r[1] for r in rows(run(strict_config, "src/a.js", text))] == [4, 5, 6, 7, 8]


def test_import001_operations_are_configurable(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    text = "import subprocess\nsubprocess.run(['ls'], check=True)\n"
    narrowed = make_config("[tool.shockharness.rules.import_effects]\npython_operations = []\n")
    assert rows(run(narrowed, "src/a.py", text)) == []
    assert any(
        "python_operations no longer lists 'subprocess.run'" in d for d in narrowed.deviations
    )


def test_import001_skips_scripts_run_directly(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    effect = "import subprocess\nsubprocess.run(['make'], check=True)\n"
    files = {
        "tools.py": "#!/usr/bin/env python3\n" + effect,  # a shebang
        "bin/cli.mjs": '#!/usr/bin/env node\nimport { execSync } from "node:child_process";\n'
        'execSync("ls");\n',
        "scripts/__init__.py": "",
        "scripts/build.py": effect,  # nothing imports it
        "scripts/shared.py": effect,  # app/use.py imports it: its effects run there
        "app/__init__.py": "",
        "app/use.py": "from scripts import shared\n",
        "app/eager.py": effect,
    }
    for name, body in files.items():
        (empty_root / name).parent.mkdir(parents=True, exist_ok=True)
        (empty_root / name).write_text(body, encoding="utf-8")
    report = analyze_paths([empty_root], empty_root, make_config(""), OPTIONS)
    found = [(f.path, f.span.line) for f in report.findings if f.rule_id == "IMPORT001"]
    assert found == [("app/eager.py", 2), ("scripts/shared.py", 2)]
    exempt = {
        file.path: disable.reason
        for file in report.files
        for disable in file.rules_disabled
        if disable.rule_id == "IMPORT001"
    }
    assert exempt["tools.py"].startswith("a script run directly (#! on line 1)")
    assert exempt["bin/cli.mjs"].startswith("a script run directly")
    assert exempt["scripts/build.py"].startswith("a script (rules.import_effects.script_files)")
    assert "scripts/shared.py" not in exempt
    widened = make_config('[tool.shockharness.rules.import_effects]\nscript_files = ["tools/**"]\n')
    assert any("script_files also permits 'tools/**'" in d for d in widened.deviations)


# -- configuration -----------------------------------------------------------------------


def test_severity_error_gates_and_review_is_a_deviation(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    text = "def f():\n    raise NotImplementedError\n"
    error = make_config('[tool.shockharness.rules.stubs]\nseverity = "error"\n')
    assert rows(run(error, "src/a.py", text)) == [("STUB001", 2, "error")]
    assert not any("rules.stubs" in d for d in error.deviations)
    review = make_config('[tool.shockharness.rules.stubs]\nseverity = "review"\n')
    assert rows(run(review, "src/a.py", text)) == [("STUB001", 2, "review")]
    assert any("rules.stubs.severity is 'review'" in d for d in review.deviations)


def test_invalid_guardrail_configuration_is_rejected(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    for body, key in (
        ('[tool.shockharness.rules.stubs]\nseverity = "fatal"\n', "rules.stubs.severity"),
        ('[tool.shockharness.rules.assertions]\nroles = ["prod"]\n', "rules.assertions.roles[0]"),
        (
            "[[tool.shockharness.rules.module_state.allowed]]\n"
            'path = "src/[a.py"\nname = "X"\nreason = "r"\n',
            "rules.module_state.allowed[0].path",
        ),
        ("[[tool.shockharness.rules.module_state.allowed]]\nname = 'X'\n", "allowed[0]"),
    ):
        with pytest.raises(ConfigError) as info:
            make_config(body)
        assert key in str(info.value), body
