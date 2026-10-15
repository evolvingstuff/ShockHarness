"""Call graph and coupling: edge confidence classification, import resolution in both
languages, module cycles, fan-out, shared mutable state, and the CPLX005 rule."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.complexity.coupling import strongly_connected_components
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True)


def _report(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return analyze_paths([root], root, config, OPTIONS)


def _edges(report: Any, source: str) -> list[tuple[str, str, str, str]]:
    """(target kind, target id, confidence, edge kind) of every edge leaving ``source``."""
    return [
        (e["to"]["kind"], e["to"]["id"], e["confidence"], e["kind"])
        for e in report.metrics["graph"]["edges"]
        if e["from"] == source
    ]


def _unit(report: Any, key: str) -> dict[str, Any]:
    (unit,) = [u for u in report.metrics["graph"]["units"] if u["key"] == key]
    return unit


PY_UTIL = "def helper(x):\n    return x\n\n\nclass Base:\n    def run(self):\n        return 1\n"
PY_MAIN = (
    "import json\n"
    "import os.path as osp\n"
    "import pkg.util as u\n"
    "from pkg.util import helper, Base\n"
    "from .util import helper as local_helper\n"
    "from pkg.api import exported\n"
    "import pkg.util\n\n\n"
    "def direct():\n    return helper(1) + local_helper(1) + u.helper(1) + pkg.util.helper(1)\n\n\n"
    "def external():\n    return json.loads('1') + len([]) + osp.join('a', 'b') + exported()\n\n\n"
    "def higher(xs, cb):\n    return sorted(xs, key=helper) + list(map(cb, xs)) + cb(1)\n\n\n"
    "def dynamic(o, n, table, k):\n"
    "    return getattr(o, n)() + table[k]() + o.method() + (o)()\n\n\n"
    "class K(Base):\n    def m(self):\n"
    "        return self.n() + self.run() + K.m(self) + Base()\n\n"
    "    def n(self):\n        def inner():\n            return 1\n        return inner()\n"
)
PY_API = "from pkg.util import helper\n\nexported = helper\n"


def test_python_resolution_classes(empty_root: Path, strict_config: EffectiveConfig) -> None:
    report = _report(
        empty_root,
        strict_config,
        {
            "pkg/__init__.py": "",
            "pkg/util.py": PY_UTIL,
            "pkg/api.py": PY_API,
            "pkg/main.py": PY_MAIN,
        },
    )
    direct = _edges(report, "pkg/main.py::direct")
    assert ("unit", "pkg/util.py::helper", "resolved", "call") in direct  # from-import
    assert direct.count(("unit", "pkg/util.py::helper", "resolved", "call")) == 1
    # u.helper() and pkg.util.helper(): attribute calls on module aliases are probable
    assert direct.count(("unit", "pkg/util.py::helper", "probable", "call")) == 1
    resolved_targets = {e[1] for e in direct if e[2] == "resolved"}
    assert resolved_targets == {"pkg/util.py::helper"}  # local_helper and helper, deduplicated

    external = _edges(report, "pkg/main.py::external")
    assert ("external", "json.loads", "probable", "call") in external  # module alias attribute
    assert ("builtin", "len", "resolved", "call") in external
    assert ("external", "os.path.join", "probable", "call") in external
    # pkg.api is analyzed but defines no unit `exported` (a re-export): probable, never resolved
    assert ("external", "pkg/api.py::exported", "probable", "call") in external

    higher = _edges(report, "pkg/main.py::higher")
    assert ("unit", "pkg/util.py::helper", "probable", "argument") in higher
    assert ("unresolved", "cb", "unresolved", "call") in higher
    assert all(e[1] != "cb" or e[2] == "unresolved" for e in higher)  # cb as argument: no edge
    assert ("builtin", "sorted", "resolved", "call") in higher

    dynamic = _edges(report, "pkg/main.py::dynamic")
    assert ("builtin", "getattr", "resolved", "call") in dynamic  # getattr itself is a builtin
    computed = [e for e in dynamic if e[0] != "builtin"]
    assert {e[2] for e in computed} == {"unresolved"}
    assert {e[0] for e in computed} == {"unresolved"}
    unit = _unit(report, "pkg/main.py::dynamic")
    assert unit["fan_out"] == 0 and unit["fan_out_external"] == 0
    assert unit["calls"]["unresolved"] == 4

    method = _edges(report, "pkg/main.py::K.m")
    assert ("unit", "pkg/main.py::K.n", "probable", "call") in method  # self.n defined in class
    assert ("unresolved", "self.run", "unresolved", "call") in method  # inherited: not guessed
    assert ("unit", "pkg/main.py::K.m", "probable", "call") in method  # static K.m(self)
    assert ("unit", "pkg/util.py::Base", "resolved", "call") in method  # imported class call
    nested = _edges(report, "pkg/main.py::K.n")
    assert nested == [("unit", "pkg/main.py::K.n.inner", "resolved", "call")]

    summary = report.metrics["graph"]["summary"]
    assert summary["call_edges"]["unresolved"] >= 5
    assert all(
        e["to"]["kind"] != "unresolved" or e["confidence"] == "unresolved"
        for e in report.metrics["graph"]["edges"]
    )
    # `exported = helper` in pkg/api.py is a reference, not a call: it adds no edge
    assert _unit(report, "pkg/util.py::helper")["fan_in"] == 2
    fan_in_sources = {
        e["from"]
        for e in report.metrics["graph"]["edges"]
        if e["to"]["id"] == "pkg/util.py::helper" and e["confidence"] in ("resolved", "probable")
    }
    assert fan_in_sources == {"pkg/main.py::direct", "pkg/main.py::higher"}


def test_python_module_edges_and_canonical_names(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = _report(
        empty_root,
        strict_config,
        {
            "src/pkg/__init__.py": "from pkg import api\n",
            "src/pkg/api.py": "import json\nfrom pkg.output import json as out\n"
            "from . import util\nfrom .util import helper\nimport requests\n",
            "src/pkg/output/__init__.py": "",
            "src/pkg/output/json.py": "def render():\n    return 1\n",
            "src/pkg/util.py": "def helper():\n    return 1\n",
        },
    )
    edges = {
        (e["specifier"], e["imported"]): (e["to"], e["confidence"])
        for e in report.metrics["graph"]["module_edges"]
        if e["from"] == "src/pkg/api.py"
    }
    assert edges[("json", "")] == (None, "external")  # never matched by suffix
    assert edges[("pkg.output", "json")] == ("src/pkg/output/json.py", "resolved")
    assert ("pkg.output", "") not in edges  # every name was a submodule: no package edge
    assert edges[(".", "util")] == ("src/pkg/util.py", "resolved")
    assert edges[(".util", "")] == ("src/pkg/util.py", "resolved")
    assert edges[("requests", "")] == (None, "external")
    # the package facade imports its submodule; the submodule does not import the package back
    facade = [
        e for e in report.metrics["graph"]["module_edges"] if e["from"] == "src/pkg/__init__.py"
    ]
    assert [(e["to"], e["confidence"]) for e in facade] == [("src/pkg/api.py", "resolved")]
    assert report.metrics["graph"]["cycles"] == []


JS_UTIL = "export function helper(x) { return x; }\nexport class Base { run() { return 1; } }\n"
JS_MAIN = """import { helper as h, Base } from "./util.js";
import * as ns from "./util.js";
import def from "./util.js";
import lodash from "lodash";
const u = require("./util.js");
const { helper } = require("./util.js");
const fs = require("node:fs");
export { helper as reexported } from "./util.js";
export * from "./missing.js";

export function direct(xs) { return h(1) + helper(1) + ns.helper(1) + u.helper(1); }
export function external() {
  return lodash.map([], helper) + fs.readFileSync("x") + console.log(1)
    + Math.max(1, 0) + fetch("u");
}
export function higher(xs, cb) { return xs.map(helper) + xs.map(cb) + cb(1); }
export function dynamic(o, k, n) {
  return o[k]() + o.method() + (n ? h : helper)() + import("./dyn.js") + require(n);
}
export class K extends Base {
  m() { return this.n() + this.run() + new Base() + new K(); }
  n() { const inner = () => 1; return inner(); }
}
"""


def test_javascript_resolution_classes(empty_root: Path, strict_config: EffectiveConfig) -> None:
    report = _report(empty_root, strict_config, {"src/util.js": JS_UTIL, "src/main.js": JS_MAIN})
    direct = _edges(report, "src/main.js::direct")
    assert direct.count(("unit", "src/util.js::helper", "resolved", "call")) == 1  # h, helper
    assert direct.count(("unit", "src/util.js::helper", "probable", "call")) == 1  # ns.*, u.*
    external = _edges(report, "src/main.js::external")
    assert ("external", "lodash.map", "probable", "call") in external
    assert ("unit", "src/util.js::helper", "probable", "argument") in external
    assert ("external", "node:fs.readFileSync", "probable", "call") in external
    assert ("builtin", "console.log", "resolved", "call") in external
    assert ("builtin", "Math.max", "resolved", "call") in external
    assert ("builtin", "fetch", "resolved", "call") in external
    higher = _edges(report, "src/main.js::higher")
    assert ("unit", "src/util.js::helper", "probable", "argument") in higher
    assert ("unresolved", "xs.map", "unresolved", "call") in higher
    assert ("unresolved", "cb", "unresolved", "call") in higher
    dynamic = _edges(report, "src/main.js::dynamic")
    assert {e[2] for e in dynamic} == {"unresolved"}
    assert len(dynamic) == 3  # o[k](), o.method(), (n ? h : helper)(); import/require are not calls
    method = _edges(report, "src/main.js::K.m")
    assert ("unit", "src/main.js::K.n", "probable", "call") in method
    assert ("unresolved", "this.run", "unresolved", "call") in method
    assert ("unit", "src/util.js::Base", "resolved", "new") in method
    assert ("unit", "src/main.js::K", "resolved", "new") in method
    assert _edges(report, "src/main.js::K.n") == [
        ("unit", "src/main.js::K.n.inner", "resolved", "call")
    ]
    module_edges = {
        (e["specifier"], e["kind"]): (e["to"], e["confidence"])
        for e in report.metrics["graph"]["module_edges"]
        if e["from"] == "src/main.js"
    }
    assert module_edges[("./util.js", "names")] == ("src/util.js", "resolved")
    assert module_edges[("./util.js", "module")] == ("src/util.js", "resolved")
    assert module_edges[("lodash", "names")] == (None, "external")
    assert module_edges[("node:fs", "module")] == (None, "external")
    assert module_edges[("./util.js", "reexport")] == ("src/util.js", "resolved")
    assert module_edges[("./missing.js", "reexport")] == (None, "unresolved")
    assert module_edges[("./dyn.js", "module")] == (None, "unresolved")  # import() is dynamic
    assert module_edges[("require(n)", "dynamic")] == (None, "unresolved")


def test_module_cycles_produce_cplx005_per_member_in_both_languages(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = _report(
        empty_root,
        strict_config,
        {
            "py/__init__.py": "",
            "py/a.py": "from py import b\n\n\ndef fa():\n    return b.fb()\n",
            "py/b.py": "from py.c import fc\n\n\ndef fb():\n    return fc()\n",
            "py/c.py": "import py.a\n\n\ndef fc():\n    return py.a.fa()\n",
            "js/x.js": 'import { y } from "./y.js";\nexport function x() { return y(); }\n',
            "js/y.js": 'const { x } = require("./x");\nexport function y() { return x(); }\n',
            "js/z.js": 'import { x } from "./x.js";\nexport function z() { return x(); }\n',
        },
    )
    cycles = report.metrics["graph"]["cycles"]
    assert [c["modules"] for c in cycles] == [
        ["js/x.js", "js/y.js"],
        ["py/a.py", "py/b.py", "py/c.py"],
    ]
    assert all(c["confidence"] == "resolved" for c in cycles)
    findings = [
        (f.path, f.span.line, f.rule_id, f.severity)
        for f in report.findings
        if f.rule_id == "CPLX005"
    ]
    assert findings == [
        ("js/x.js", 1, "CPLX005", "warning"),
        ("js/y.js", 1, "CPLX005", "warning"),
        ("py/a.py", 1, "CPLX005", "warning"),
        ("py/b.py", 1, "CPLX005", "warning"),
        ("py/c.py", 1, "CPLX005", "warning"),
    ]
    (first,) = [f for f in report.findings if f.path == "py/a.py"]
    assert "py/a.py -> py/b.py -> py/c.py -> py/a.py" in first.message
    assert "resolved edges only" in first.message
    assert first.scope == "<module>"
    assert report.gate.status == "pass"  # cycles are warnings
    modules = {m["path"]: m for m in report.metrics["graph"]["modules"]}
    assert modules["js/z.js"]["cycle"] is None and modules["js/x.js"]["cycle"] == 0
    assert modules["js/x.js"]["fan_in"] == 2 and modules["js/x.js"]["fan_out"] == 1


def test_fan_out_above_threshold(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nfan_out_warn = 2\n")
    text = (
        "import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 1\n\n\n"
        "def c():\n    return 1\n\n\n"
        "def busy(cb):\n    return a() + b() + c() + os.getcwd() + len([]) + cb() + a()\n\n\n"
        "def calm():\n    return a() + b()\n"
    )
    report = _report(empty_root, config, {"src/m.py": text})
    (finding,) = [f for f in report.findings if f.rule_id == "CPLX005"]
    assert finding.scope == "busy" and finding.span.line == 16
    assert "fan-out of busy is 4 distinct call target(s) (3 analyzed, 1 external" in finding.message
    assert "1 unresolved call(s) not counted" in finding.message
    unit = _unit(report, "src/m.py::busy")
    assert unit["fan_out"] == 3 and unit["fan_out_external"] == 1 and unit["fan_out_total"] == 4
    # a() twice, b(), c() and the builtin len() resolve; os.getcwd() is probable; cb() is not
    assert unit["calls"] == {"resolved": 5, "probable": 1, "unresolved": 1}
    assert _unit(report, "src/m.py::calm")["fan_out_total"] == 2  # not above the threshold
    assert _unit(report, "src/m.py::a")["fan_in"] == 2


def test_shared_mutable_state_heuristic(empty_root: Path, strict_config: EffectiveConfig) -> None:
    report = _report(
        empty_root,
        strict_config,
        {
            "src/state.py": (
                "CACHE = {}\nCOUNTER = 0\nLIMITS = [1]\nNAME = 'x'\nONCE = set()\n\n\n"
                "def put(k, v):\n    CACHE[k] = v\n\n\n"
                "def merge(d):\n    CACHE.update(d)\n\n\n"
                "def bump():\n    global COUNTER\n    COUNTER += 1\n\n\n"
                "def reset():\n    global COUNTER\n    COUNTER = 0\n\n\n"
                "def shadow():\n    LIMITS = []\n    LIMITS.append(1)\n    return LIMITS\n\n\n"
                "def extend():\n    LIMITS.append(1)\n\n\n"
                "def single():\n    ONCE.add(1)\n\n\n"
                "def rename():\n    NAME = 'y'\n    return NAME\n"
            ),
            "src/state.js": (
                "let state = 0;\nconst registry = new Map();\nconst frozen = 1;\nvar flag;\n\n"
                "export function inc() { state += 1; }\nexport function reset() { state = 0; }\n"
                "export function add(k, v) { registry.set(k, v); }\n"
                "export function merge(o) { Object.assign(registry, o); }\n"
                "export function local() { let state = 1; state = 2; return state; }\n"
                "export function one() { flag = true; }\n"
            ),
        },
    )
    rows = [
        (s["path"], s["name"], s["writers"], s["confidence"])
        for s in report.metrics["graph"]["shared_mutable_state"]
    ]
    assert rows == [
        ("src/state.js", "registry", ["add", "merge"], "approximate"),
        ("src/state.js", "state", ["inc", "reset"], "approximate"),
        ("src/state.py", "CACHE", ["merge", "put"], "approximate"),
        ("src/state.py", "COUNTER", ["bump", "reset"], "approximate"),
    ]
    assert report.metrics["graph"]["summary"]["shared_mutable_state"] == 4
    assert not any(f.rule_id == "CPLX005" for f in report.findings)  # a note, not a finding


def test_strongly_connected_components_is_iterative_on_a_long_chain() -> None:
    nodes = [f"m{i}" for i in range(5000)]
    successors = {nodes[i]: [nodes[i + 1]] for i in range(len(nodes) - 1)}
    successors[nodes[len(nodes) - 1]] = [nodes[0]]
    components = strongly_connected_components(nodes, successors)
    assert components == [sorted(nodes)]
    acyclic = {nodes[i]: [nodes[i + 1]] for i in range(len(nodes) - 1)}
    acyclic[nodes[len(nodes) - 1]] = []
    assert all(len(c) == 1 for c in strongly_connected_components(nodes, acyclic))


def test_graph_metrics_are_byte_identical_across_runs(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    files = {
        "src/a.py": "from src import b\n\n\ndef f():\n    return b.g()\n",
        "src/b.py": "def g():\n    return 1\n",
        "src/__init__.py": "",
    }
    first = _report(empty_root, strict_config, files).metrics["graph"]
    second = _report(empty_root, strict_config, files).metrics["graph"]
    assert first == second
    assert first["abstraction_displacement"]["status"] == "not_applicable"
    assert first["abstraction_displacement"]["enabled"] is False
