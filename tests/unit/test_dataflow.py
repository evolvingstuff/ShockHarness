"""H6: dataflow facts (ir/*_dataflow.py) and the INPUT001-INPUT002 rules (spec 21.1
decision 26)."""

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from shockharness.ir.javascript import extract_javascript_facts, extract_typescript_facts
from shockharness.ir.model import FlowUnit
from shockharness.ir.python_dataflow import collect_python_dataflow
from shockharness.rules import registry
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def py_units(text: str) -> dict[str, FlowUnit]:
    facts = collect_python_dataflow(SourceText.from_text(text), ast.parse(text))
    return {unit.name: unit for unit in facts.units}


def js_units(text: str, path: str) -> dict[str, FlowUnit]:
    extract = extract_typescript_facts if path.endswith(".ts") else extract_javascript_facts
    return {u.name: u for u in extract(SourceText.from_text(text), path).dataflow.units}


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    write(root, files)
    return analyze_paths([root], root, config, OPTIONS)


def rows(report: Any, rule: str) -> list[tuple[str, int, str]]:
    return [(f.path, f.span.line, f.message) for f in report.findings if f.rule_id == rule]


def run(config: EffectiveConfig, path: str, text: str) -> FileResult:
    language = "python" if path.endswith(".py") else "javascript"
    return analyze_text(path, language, text, config, OPTIONS)


# -- facts ------------------------------------------------------------------------------


def test_python_facts_follow_assignments_in_source_order() -> None:
    units = py_units(
        "import os\nfrom flask import request\n\nHOST = os.getenv('HOST')\n\n\n"
        "def view(req):\n"
        "    cmd = request.args.get('cmd')\n"  # 8
        "    safe = cmd\n"
        "    safe = quote(safe)\n"  # 10: replaced at the top level
        "    if req.ok:\n        cmd = quote(cmd)\n"  # 12: added to in a branch
        "    req.body['k'] = cmd\n"  # 13: a store
        "    run(cmd, safe, key=req.body.name)\n"
        "    return [c for c in cmd if c]\n"
    )
    module, view = units["<module>"], units["view"]
    assert [(s.target, s.origins) for s in module.stores] == [("HOST", ("c:0",))]
    assert [(r.text, r.on_parameter) for r in view.reads] == [
        ("request.args", False),
        ("req.ok", True),
        ("req.body", True),  # the object of the store
        ("req.body.name", True),
    ]
    callees = [c.callee for c in view.calls]
    assert callees == ["request.args.get", "quote", "quote", "run"]
    run_call = view.calls[3]
    assert run_call.arguments == (("c:0", "c:2"), ("c:1",))
    assert run_call.keywords == (("key", ("p:0", "r:3")),)
    assert [s.target for s in view.stores] == ["req.body['k']"]
    assert view.returns[0].origins == ("c:0", "c:2")
    assert set(view.tested) >= {"p:0", "r:1"}


def test_python_methods_and_depth() -> None:
    units = py_units(
        "class S:\n    def m(self, x):\n        return x\n\n"
        "    @staticmethod\n    def s(x):\n        return x\n"
    )
    assert units["S.m"].bound_receiver
    assert units["S.m"].parameters == ("self", "x")
    assert not units["S.s"].bound_receiver
    # 800 terms: far past the depth cap; CPython 3.11's parser builds about 1000 at most.
    chain = py_units("def g(a):\n    return " + " + ".join(["a"] * 800) + "\n")["g"]
    assert chain.returns[0].origins == ("p:0",)
    assert not chain.truncated


def test_javascript_facts() -> None:
    units = js_units(
        "const DB = process.env.DATABASE_URL;\n"
        "export function f(req, { a }) {\n"
        "  const { cmd } = req.body;\n"
        "  let x = `ls ${cmd} ${a}`;\n"
        "  process.env.TZ ??= 'UTC';\n"
        "  return run(x as string, req.query['next']);\n"
        "}\n"
        "class K { field = process.env.FIELD; }\n",
        "a.ts",
    )
    assert [(s.target, s.origins) for s in units["<module>"].stores] == [("DB", ("r:0",))]
    f = units["f"]
    assert f.parameters == ("req", "{ a }")
    assert [(r.text, r.on_parameter) for r in f.reads] == [
        ("req.body", True),
        ("process.env.TZ", False),
        ("process.env", False),  # the object of the store
        ("req.query.next", True),
    ]
    assert "r:1" in f.tested  # ??= tests its left side
    assert f.calls[0].arguments == (("p:0", "p:1", "r:0"), ("p:0", "r:3"))
    assert [s.target for s in units["K"].stores] == ["field"]
    deep = "function f(a) {\n" + "if (a) {\n" * 300 + "x(a);\n" + "}\n" * 300 + "}\n"
    assert js_units(deep, "d.js")["f"].truncated


# -- INPUT001 ---------------------------------------------------------------------------

FLASK = (
    "import subprocess\nfrom flask import request as rq\n\n\n"
    "def convert(db):\n"
    "    cmd = rq.args.get('cmd')\n"  # 6
    "    subprocess.run(f'convert {cmd}', shell=True)\n"  # 7
    "    subprocess.run(['convert', str(int(rq.args['n']))])\n"  # 8: validated
    "    if db.strict:\n        cmd = quote(cmd)\n"
    "    db.execute('SELECT ' + cmd)\n"  # 11: quoted on one branch only
    "    db.execute('SELECT ?', (cmd,))\n"  # 12: a parameter, not the query
)


def test_input001_in_one_function(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, "app/views.py", FLASK)
    found = [(f.span.line, f.confidence) for f in result.findings if f.rule_id == "INPUT001"]
    assert found == [(7, "exact"), (11, "approximate")]  # .execute is matched by name
    message = next(f.message for f in result.findings if f.rule_id == "INPUT001")
    assert message.startswith(
        "flask.request.args (app/views.py:6) reaches argument 1 of subprocess.run(...) "
        "without passing a validator"
    )
    assert registry.category_of("INPUT001") == "contract_integrity"
    tests_file = run(strict_config, "tests/test_views.py", FLASK)
    assert "INPUT001" not in tests_file.rules_applied  # rules.input.roles: production


CROSS = {
    "app/__init__.py": "",
    "app/views.py": (
        "from flask import request\n\nfrom app.shell import run_shell, source\n\n\n"
        "def view():\n"
        "    run_shell(request.form['x'], flag=True)\n"  # 7
        "    return run_shell(source(), flag=False)\n"
    ),
    "app/shell.py": (
        "import os\n\nfrom flask import request\n\n\n"
        "def run_shell(command, *, flag):\n"
        "    return _go(command, flag=flag)\n\n\n"
        "def _go(text, flag):\n"
        "    os.system('sh -c ' + text)\n"  # 11
        "    return flag\n\n\n"
        "def source():\n"
        "    return request.args['y']\n\n\n"  # 16
        "class Handler:\n"
        "    def handle(self):\n"
        "        self._sink(request.args['z'])\n\n"  # 21
        "    def _sink(self, text):\n"
        "        os.system(text)\n"  # 24
    ),
}


def test_input001_across_files_and_depth(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    report = project(empty_root, make_config(""), CROSS)
    found = [
        (f.path, f.span.line, f.confidence, f.message)
        for f in report.findings
        if f.rule_id == "INPUT001"
    ]
    assert [(path, line, confidence) for path, line, confidence, _ in found] == [
        ("app/shell.py", 11, "exact"),
        ("app/shell.py", 11, "exact"),
        ("app/shell.py", 24, "approximate"),  # self._sink: a probable resolution
    ]
    messages = [m for _, _, _, m in found]
    assert "flask.request.args (app/shell.py:16)" in messages[0]
    assert messages[0].endswith("(through source -> run_shell -> _go): os.system('sh -c ' + text)")
    assert "flask.request.form (app/views.py:7)" in messages[1]
    assert "(through run_shell -> _go)" in messages[1]
    assert "flask.request.args (app/shell.py:21)" in messages[2]
    assert "(through Handler._sink)" in messages[2]
    shallow = make_config("[tool.shockharness.rules.input]\nmax_depth = 2\n")
    kept = [f.message for f in project(empty_root, shallow, {}).findings if f.rule_id == "INPUT001"]
    assert kept == [messages[1], messages[2]]
    assert any("rules.input.max_depth is 2 (strict: 3)" in d for d in shallow.deviations)


def test_input001_javascript(strict_config: EffectiveConfig) -> None:
    text = (
        'import { exec } from "node:child_process";\n'
        'import { z } from "zod";\n'
        "const Cmd = z.string();\n"
        'app.post("/run", (req, res) => {\n'
        "  const { cmd } = req.body;\n"
        "  exec(`ls ${cmd}`);\n"  # 6
        "  exec(`ls ${Number(req.query.n)}`);\n"
        "  exec(Cmd.parse(req.body.other));\n"  # zod: a validator
        "  exec(JSON.parse(req.body.raw));\n"  # 9: JSON.parse decodes, it does not check
        "  res.redirect(req.query.next);\n"  # 10
        "});\n"
    )
    found = [
        (f.span.line, f.confidence)
        for f in run(strict_config, "web/a.js", text).findings
        if f.rule_id == "INPUT001"
    ]
    assert found == [(6, "approximate"), (9, "approximate"), (10, "approximate")]


# -- INPUT002 ---------------------------------------------------------------------------


def test_input002_javascript(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = (
        "const DB = process.env.DATABASE_URL;\n"  # 1: stored at module level
        "export function port() { const raw = process.env.PORT; return listen(raw); }\n"
        "export function url() {\n"
        "  const u = process.env.URL;\n"
        '  if (!u) { throw new Error("URL is required"); }\n'
        "  return u;\n"
        "}\n"
        'export const mode = process.env.MODE === undefined ? "dev" : process.env.MODE;\n'
        "export const n = Number(process.env.N);\n"  # 9: Number(undefined) is NaN
        "export const h = process.env.HOME.length;\n"  # throws when unset: loud
    )
    result = run(make_config(""), "src/a.js", text)
    found = [
        (f.span.line, f.message.split(", and the value ")[1].split(" without")[0])
        for f in result.findings
        if f.rule_id == "INPUT002"
    ]
    assert found == [
        (1, "is stored in DB"),
        (2, "is passed to listen(...)"),
        (9, "is passed to Number(...)"),
    ]
    assert {f.severity for f in result.findings if f.rule_id == "INPUT002"} == {"review"}
    raised = make_config('[tool.shockharness.rules.input]\ninput002_severity = "warning"\n')
    assert {
        f.severity for f in run(raised, "src/a.js", text).findings if f.rule_id == "INPUT002"
    } == {"warning"}
    assert not any("input002_severity" in d for d in raised.deviations)


def test_input002_python(strict_config: EffectiveConfig) -> None:
    text = (
        "import os\n\nHOST = os.getenv('HOST')\n\n\n"  # 3: DEF006's line
        "def connect():\n"
        "    url = os.environ.get('URL')\n"
        "    port = int(os.getenv('PORT'))\n"  # int(None) raises
        "    token = os.getenv('TOKEN')\n"
        "    if token is None:\n        raise RuntimeError('TOKEN is required')\n"
        "    return open_db(url, port, token)\n"  # 12: url unchecked
    )
    result = run(strict_config, "src/db.py", text)
    assert [
        (f.span.line, f.message.split(" is None")[0])
        for f in result.findings
        if f.rule_id == "INPUT002"
    ] == [(12, "os.environ.get('URL')")]
    assert [f.span.line for f in result.findings if f.rule_id == "DEF006"] == [3, 7, 8, 9]


def test_sink_entries_name_an_argument(make_config: Callable[[str], EffectiveConfig]) -> None:
    with pytest.raises(ConfigError, match=r"python_sinks\[1\]: must be 'callee:N'"):
        make_config('[tool.shockharness.rules.input]\npython_sinks = ["os.system:0", "eval"]\n')
    assert registry.INPUT002.default_severity == "review"


def test_input002_counts_node_assert_as_a_check(strict_config: EffectiveConfig) -> None:
    """MetaList feedback (0.7.0): assert([...].includes(name)) from node:assert checks name;
    console.assert only logs."""
    text = (
        'import assert from "node:assert";\n'
        "const browserName = process.env.BROWSER_TEST_BROWSER;\n"
        'assert(["chrome", "firefox"].includes(browserName), "chrome or firefox");\n'
        "const port = process.env.PORT;\n"  # 4
        'console.assert(port, "port");\n'
        "export const config = { browserName, port };\n"
    )
    result = run(strict_config, "scripts/browser-smoke.mjs", text)
    assert [f.span.line for f in result.findings if f.rule_id == "INPUT002"] == [4]


def test_assert001_reports_an_assert_once_with_every_source(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "import sys\nfrom pathlib import Path\n\n\n"
        "def run_update(path):\n"
        "    text = Path(path).read_text()\n"  # a method on a computed receiver
        "    check(text, sys.argv[1])\n\n\n"
        "def check(text, arg):\n"
        "    assert text.startswith('v') and arg, 'bad update'\n"  # 11
    )
    result = run(strict_config, "app/app_updates.py", text)
    found = [f for f in result.findings if f.rule_id == "ASSERT001"]
    assert [f.span.line for f in found] == [11]
    assert ".read_text (app/app_updates.py:6) (through check); sys.argv" in found[0].message
