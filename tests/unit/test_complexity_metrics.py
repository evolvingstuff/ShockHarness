"""Complexity metrics: golden counts per construct in both languages, Python/JavaScript
parity, NPath saturation, size, nested units, and the metamorphic properties
(whitespace and rename invariance, helper extraction, artificial splitting)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.complexity.metrics import measure_units
from shockharness.config import EffectiveConfig
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.python import extract_python_facts
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True)
SETTINGS: dict[str, Any] = {"cyclomatic_counts_boolean_operators": True, "npath_cap": 10000}
PY = "python"
JS = "javascript"


def units_of(language: str, text: str, settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = SourceText.from_text(text)
    if language == PY:
        facts = extract_python_facts(source, "t.py")
    else:
        facts = extract_javascript_facts(source, "t.js")
    assert facts.parse_failure is None, facts.parse_failure
    measured = measure_units("t", facts.functions, settings)
    return {
        u.name: {
            "cyclomatic": u.cyclomatic,
            "cognitive": u.cognitive,
            "nesting": u.nesting,
            "npath": u.npath,
            "saturated": u.npath_saturated,
            "kind": u.kind,
            "statements": u.fact.statements,
            "logical_lines": u.fact.logical_lines,
            "parameters": u.fact.parameters,
            "async": u.is_async,
            "generator": u.is_generator,
        }
        for u in measured
    }


def metrics(language: str, text: str, name: str) -> tuple[int, int, int, int]:
    unit = units_of(language, text, SETTINGS)[name]
    return unit["cyclomatic"], unit["cognitive"], unit["nesting"], unit["npath"]


# --- golden table: (python source, javascript source, name, cyclomatic, cognitive, nesting, npath)
# Every row is an equivalent construct in both languages and must give the same four numbers.
PARITY: list[tuple[str, str, str, tuple[int, int, int, int]]] = [
    (
        "def f(a, b, c):\n    if a:\n        pass\n    if b:\n        pass\n"
        "    if c:\n        pass\n",
        "function f(a, b, c) { if (a) {} if (b) {} if (c) {} }",
        "f",
        (4, 3, 1, 8),  # flat: three independent decisions multiply paths
    ),
    (
        "def f(a, b, c):\n    if a:\n        if b:\n            if c:\n                pass\n",
        "function f(a, b, c) { if (a) { if (b) { if (c) {} } } }",
        "f",
        (4, 6, 3, 4),  # nested: same cyclomatic, cognitive 1+2+3, depth 3
    ),
    (
        "def f(a, b, c, d, e):\n    return a and b and c or d or e\n",
        "function f(a, b, c, d, e) { return a && b && c || d || e; }",
        "f",
        (5, 2, 0, 5),  # four operators, two runs
    ),
    (
        "def f(a, b, c, d):\n    return a and (b or c) and d\n",
        "function f(a, b, c, d) { return a && (b || c) && d; }",
        "f",
        (4, 3, 0, 4),  # parentheses split the runs: and, or, and
    ),
    (
        "def f(x):\n    if x == 1:\n        return 1\n    elif x == 0:\n        return 0\n"
        "    else:\n        return x\n",
        "function f(x) { if (x === 1) { return 1; } else if (x === 0) { return 0; }"
        " else { return x; } }",
        "f",
        (3, 3, 1, 3),  # if +1, elif +1 (no nesting), else +1
    ),
    (
        "def f(a, b, c):\n    return a if b else (c if a else b)\n",
        "function f(a, b, c) { return b ? a : (a ? c : b); }",
        "f",
        (3, 3, 2, 3),  # nested conditional: +1 and +2
    ),
    (
        "def f(p):\n    try:\n        g(p)\n    except ValueError:\n        return 1\n"
        "    finally:\n        h()\n",
        "function f(p) { try { g(p); } catch (e) { return 1; } finally { h(); } }",
        "f",
        (2, 1, 1, 2),  # one handler; try and finally add nothing
    ),
    (
        "def f(n):\n    if n == 0:\n        return 1\n    return n * f(n - 1)\n",
        "function f(n) { if (n === 0) { return 1; } return n * f(n - 1); }",
        "f",
        (2, 2, 1, 2),  # recursion +1 cognitive only
    ),
    (
        "def f(x, y):\n    match x:\n        case 1:\n            if x and y:\n"
        "                return 1\n        case 0:\n            return 0\n"
        "        case _:\n            return x\n",
        "function f(x, y) { switch (x) { case 1: if (x && y) { return 1; } break;"
        " case 0: return 0; default: return x; } }",
        "f",
        (5, 4, 2, 5),  # two non-default arms + the operator; switch +1, nested if +2, run +1
    ),
    (
        "def f(xs):\n    for x in xs:\n        while x:\n            x -= 1\n",
        "function f(xs) { for (const x of xs) { let y = x; while (y) { y -= 1; } } }",
        "f",
        (3, 3, 2, 3),
    ),
    (
        "def f(a):\n    a = a or 1\n    a = a and 1\n    return a\n",
        "function f(a) { a ||= 1; a &&= 1; return a; }",
        "f",
        (3, 2, 0, 4),  # a logical assignment is one operator and one run
    ),
    (
        "def f(items):\n    total = 0\n    for item in items:\n        if item.ok:\n"
        "            if item.value:\n                if valid(item):\n"
        "                    total += 1\n    return total\n",
        "function f(items) { let total = 0; for (const item of items) { if (item.ok) {"
        " if (item.value) { if (valid(item)) { total += 1; } } } } return total; }",
        "f",
        (5, 10, 4, 5),  # loop 1, if 2, if 3, if 4
    ),
]


@pytest.mark.parametrize(("py", "js", "name", "expected"), PARITY)
def test_python_and_javascript_parity_table(
    py: str, js: str, name: str, expected: tuple[int, int, int, int]
) -> None:
    assert metrics(PY, py, name) == expected, "python"
    assert metrics(JS, js, name) == expected, "javascript"


def test_equivalent_functions_produce_identical_control_trees() -> None:
    py = (
        "def f(a, b):\n    if a and b:\n        for x in a:\n            if x:\n"
        "                return x if b else a\n    else:\n        return 0\n"
    )
    js = (
        "function f(a, b) { if (a && b) { for (const x of a) { if (x) { return b ? x : a; } } }"
        " else { return 0; } }"
    )
    py_tree = extract_python_facts(SourceText.from_text(py), "t.py").functions[1].control
    js_tree = extract_javascript_facts(SourceText.from_text(js), "t.js").functions[1].control
    assert py_tree == js_tree


def test_python_only_constructs() -> None:
    # for/else and try/else each add one (no nesting increment); comprehensions: only `if`
    text = (
        "def loops(xs):\n    for x in xs:\n        pass\n    else:\n        return 0\n\n"
        "def tries(p):\n    try:\n        g(p)\n    except OSError:\n        raise\n"
        "    else:\n        return 1\n\n"
        "def comp(xs):\n    return [x for x in xs if x if x > 1]\n\n"
        "def nested_comp(xs):\n    return [y for x in xs for y in x if y]\n\n"
        "def gen(xs):\n    yield from (x for x in xs)\n"
    )
    assert metrics(PY, text, "loops") == (2, 2, 1, 2)
    assert metrics(PY, text, "tries") == (2, 2, 1, 2)
    assert metrics(PY, text, "comp") == (4, 3, 2, 3)  # for, if, if: cyclomatic; ifs nest
    assert metrics(PY, text, "nested_comp") == (4, 1, 1, 2)
    unit = units_of(PY, text, SETTINGS)["gen"]
    assert unit["generator"] is True
    assert metrics(PY, text, "gen") == (2, 0, 0, 1)
    guarded = (
        "def f(x, y):\n    match x:\n        case 1 if x and y:\n            return 1\n"
        "        case 0:\n            return 0\n        case _:\n            return x\n"
    )
    # a guard's operators count; the guard itself is part of the arm, not an extra `if`
    assert metrics(PY, guarded, "f") == (4, 2, 1, 4)


def test_javascript_only_constructs() -> None:
    text = (
        "function jumps(xs) { outer: for (const x of xs) { for (const y of x) {"
        " if (y) { continue outer; } } } }\n"
        "function nullish(a, b) { return a ?? b ?? 0; }\n"
        "function dos(a) { do { a -= 1; } while (a); }\n"
        "function chain(o) { return o?.a?.b(); }\n"
        "async function* agen() { yield 1; }\n"
    )
    assert metrics(JS, text, "jumps") == (4, 7, 3, 4)  # labeled continue +1
    assert metrics(JS, text, "nullish") == (3, 1, 0, 3)  # ?? counts as one run of two operators
    assert metrics(JS, text, "dos") == (2, 1, 1, 2)
    assert metrics(JS, text, "chain") == (1, 0, 0, 1)  # optional chaining is never counted
    unit = units_of(JS, text, SETTINGS)["agen"]
    assert unit["async"] is True and unit["generator"] is True


def test_boolean_operator_counting_can_be_switched_off() -> None:
    text = "def f(a, b, c):\n    return a and b or c\n"
    counted = units_of(PY, text, SETTINGS)["f"]
    uncounted = units_of(PY, text, {**SETTINGS, "cyclomatic_counts_boolean_operators": False})["f"]
    assert counted["cyclomatic"] == 3
    assert uncounted["cyclomatic"] == 1
    assert counted["cognitive"] == uncounted["cognitive"] == 2  # cognitive is unaffected


def test_npath_saturates_at_the_cap_without_enumerating() -> None:
    py = "def f(" + ", ".join(f"a{i}" for i in range(40)) + "):\n"
    py += "".join(f"    if a{i}:\n        pass\n" for i in range(40))
    js = "function f(" + ", ".join(f"a{i}" for i in range(40)) + ") {"
    js += "".join(f" if (a{i}) {{}}" for i in range(40)) + " }"
    for language, text in ((PY, py), (JS, js)):
        unit = units_of(language, text, {**SETTINGS, "npath_cap": 1000})["f"]
        assert unit["saturated"] is True
        assert unit["npath"] == 1000
        assert unit["cyclomatic"] == 41
    exact = units_of(PY, py, {**SETTINGS, "npath_cap": 10**15})["f"]
    assert exact["saturated"] is False
    assert exact["npath"] == 2**40


def test_nested_units_are_measured_separately_and_excluded_from_their_parent() -> None:
    text = (
        "def outer(xs):\n"
        "    def inner(x):\n"
        "        if x:\n"
        "            if x > 1:\n"
        "                return 1\n"
        "        return 0\n"
        "    key = lambda v: v if v else 0\n"
        "    class Local:\n"
        "        if True:\n"
        "            attr = 1\n"
        "        def method(self):\n"
        "            return self.method() if self else None\n"
        "    return sorted(xs, key=key)\n"
    )
    units = units_of(PY, text, SETTINGS)
    assert set(units) == {
        "<module>",
        "outer",
        "outer.inner",
        "outer.<lambda>",
        "outer.Local",
        "outer.Local.method",
    }
    assert (
        units["outer"]["cyclomatic"],
        units["outer"]["cognitive"],
        units["outer"]["nesting"],
    ) == (
        1,
        0,
        0,
    )
    assert metrics(PY, text, "outer.inner") == (3, 3, 2, 3)
    assert metrics(PY, text, "outer.<lambda>") == (2, 1, 1, 2)
    assert metrics(PY, text, "outer.Local") == (2, 1, 1, 2)
    assert metrics(PY, text, "outer.Local.method") == (2, 2, 1, 2)  # conditional + recursion
    assert units["outer.Local.method"]["kind"] == "method"
    assert units["outer.inner"]["kind"] == "function"
    assert units["outer.<lambda>"]["kind"] == "lambda"
    assert units["outer.Local"]["kind"] == "class"
    assert units["<module>"]["kind"] == "module"
    # the parent's statements count the nested definitions once each; its lines exclude them
    assert units["outer"]["statements"] == 4
    assert units["outer"]["logical_lines"] == 3  # def, key = lambda, return
    assert units["outer.inner"]["logical_lines"] == 5


def test_size_measures_follow_the_documented_convention() -> None:
    text = (
        "# leading comment\n\n"
        "def f(a, b, *args, key, **kw):  # trailing comment\n"
        "    '''docstring\n    on two lines'''\n"
        "    # only a comment\n"
        "\n"
        "    x = (a +\n"
        "         b)\n"
        "    return x\n"
    )
    unit = units_of(PY, text, SETTINGS)["f"]
    assert unit["parameters"] == 5
    assert unit["statements"] == 3
    assert unit["logical_lines"] == 6  # def, two docstring lines, two expression lines, return
    js = (
        "function f(a, b = 1, ...rest) {\n  // comment only\n  /* block\n  comment */\n"
        "  return a;\n}\n"
    )
    js_unit = units_of(JS, js, SETTINGS)["f"]
    assert js_unit["parameters"] == 3
    assert js_unit["statements"] == 1
    assert js_unit["logical_lines"] == 3


def test_whitespace_and_rename_invariance() -> None:
    original = (
        "def process(items, limit):\n    count = 0\n    for item in items:\n"
        "        if item.ok and item.value:\n            count += 1\n"
        "    return count if count < limit else limit\n"
    )
    reformatted = (
        "def process(items, limit):\n\n    count = 0\n\n    for item in items:\n"
        "        # a comment\n\n        if (item.ok and\n                item.value):\n"
        "            count += 1\n\n\n    return (count if count < limit\n            else limit)\n"
    )
    renamed = original.replace("process", "handle").replace("count", "n").replace("item", "row")
    base = units_of(PY, original, SETTINGS)["process"]
    reformatted_unit = units_of(PY, reformatted, SETTINGS)["process"]
    # logical lines are, by definition, a line count; everything else is whitespace-blind
    assert {k: v for k, v in reformatted_unit.items() if k != "logical_lines"} == {
        k: v for k, v in base.items() if k != "logical_lines"
    }
    assert reformatted_unit["logical_lines"] > base["logical_lines"]
    assert units_of(PY, renamed, SETTINGS)["handle"] == base


def _file_report(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return analyze_paths([root / "src"], root, config, OPTIONS)


def _cognitive(report: Any, path: str) -> dict[str, int]:
    return {
        f["name"]: f["cognitive"]
        for f in report.metrics["complexity"]["functions"]
        if f["path"] == path
    }


def _resolved_edges(report: Any) -> list[tuple[str, str]]:
    return [
        (e["from"], e["to"]["id"])
        for e in report.metrics["graph"]["edges"]
        if e["confidence"] == "resolved" and e["to"]["kind"] == "unit"
    ]


def _fan_out(report: Any, key: str) -> int:
    (unit,) = [u for u in report.metrics["graph"]["units"] if u["key"] == key]
    return int(unit["fan_out"])


EXTRACTION_CASES: list[tuple[str, str, str, str]] = [
    (
        # depth 0: a top-level block of the function becomes a helper
        "python",
        "src/a.py",
        "def f(xs, flag):\n    total = 0\n    for x in xs:\n        if x and flag:\n"
        "            total += 1\n    if total:\n        return total\n    return 0\n",
        "def count(xs, flag):\n    total = 0\n    for x in xs:\n        if x and flag:\n"
        "            total += 1\n    return total\n\n\ndef f(xs, flag):\n"
        "    total = count(xs, flag)\n    if total:\n        return total\n    return 0\n",
    ),
    (
        # depth 1: the loop body is extracted
        "python",
        "src/a.py",
        "def f(xs, flag):\n    total = 0\n    for x in xs:\n        if x and flag:\n"
        "            total += 1\n    return total\n",
        "def bump(x, flag, total):\n    if x and flag:\n        return total + 1\n"
        "    return total\n\n\ndef f(xs, flag):\n    total = 0\n    for x in xs:\n"
        "        total = bump(x, flag, total)\n    return total\n",
    ),
    (
        "javascript",
        "src/a.js",
        "export function f(xs, flag) { let total = 0; for (const x of xs) { if (x && flag) {"
        " total += 1; } } if (total) { return total; } return 0; }\n",
        "function count(xs, flag) { let total = 0; for (const x of xs) { if (x && flag) {"
        " total += 1; } } return total; }\nexport function f(xs, flag) {"
        " const total = count(xs, flag); if (total) { return total; } return 0; }\n",
    ),
    (
        "javascript",
        "src/a.js",
        "export function f(xs, flag) { let total = 0; for (const x of xs) { if (x && flag) {"
        " total += 1; } } return total; }\n",
        "function bump(x, flag, total) { if (x && flag) { return total + 1; } return total; }\n"
        "export function f(xs, flag) { let total = 0; for (const x of xs) {"
        " total = bump(x, flag, total); } return total; }\n",
    ),
]


@pytest.mark.parametrize(("language", "path", "before", "after"), EXTRACTION_CASES)
def test_metamorphic_helper_extraction_never_looks_better_by_itself(
    language: str,
    path: str,
    before: str,
    after: str,
    tmp_path: Path,
    strict_config: EffectiveConfig,
) -> None:
    """Extracting a helper moves cognitive work; it must not make the file score drop below the
    original minus the helper's own score, must not change the verdict, and must show up in
    the graph as a new resolved edge (the delegation is recorded, not hidden)."""
    original = _file_report(tmp_path / "before", strict_config, {path: before})
    extracted = _file_report(tmp_path / "after", strict_config, {path: after})
    helper = "count" if "count" in after else "bump"
    before_f = _cognitive(original, path)["f"]
    after_scores = _cognitive(extracted, path)
    helper_score = after_scores[helper]
    file_after = sum(after_scores.values())
    assert file_after >= before_f - helper_score
    assert after_scores["f"] < before_f  # the work moved, it did not vanish
    assert original.gate.status == extracted.gate.status == "pass"
    assert extracted.gate.hard_violations == original.gate.hard_violations
    assert (f"{path}::f", f"{path}::{helper}") in _resolved_edges(extracted)
    assert _fan_out(extracted, f"{path}::f") == _fan_out(original, f"{path}::f") + 1
    # the reachable burden through the new edge is the original work, give or take nesting
    assert after_scores["f"] + helper_score >= before_f - helper_score


def test_metamorphic_artificial_splitting_grows_the_graph(
    tmp_path: Path, strict_config: EffectiveConfig
) -> None:
    whole = (
        "def f(a, b, c):\n    if a:\n        a += 1\n    if b:\n        b += 1\n"
        "    if c:\n        c += 1\n    return a + b + c\n"
    )
    split = (
        "def step_a(a):\n    if a:\n        a += 1\n    return a\n\n\n"
        "def step_b(b):\n    if b:\n        b += 1\n    return b\n\n\n"
        "def step_c(c):\n    if c:\n        c += 1\n    return c\n\n\n"
        "def f(a, b, c):\n    return step_a(a) + step_b(b) + step_c(c)\n"
    )
    before = _file_report(tmp_path / "before", strict_config, {"src/a.py": whole})
    after = _file_report(tmp_path / "after", strict_config, {"src/a.py": split})
    assert sum(_cognitive(before, "src/a.py").values()) == 3
    assert sum(_cognitive(after, "src/a.py").values()) == 3  # the work did not shrink
    before_edges = before.metrics["graph"]["summary"]["call_edges"]
    after_edges = after.metrics["graph"]["summary"]["call_edges"]
    assert after_edges["resolved"] == before_edges["resolved"] + 3
    assert _fan_out(after, "src/a.py::f") == 3
    assert _fan_out(before, "src/a.py::f") == 0
    assert before.gate.status == after.gate.status == "pass"


def test_report_shapes_and_ordering(empty_root: Path, strict_config: EffectiveConfig) -> None:
    report = _file_report(
        empty_root,
        strict_config,
        {
            "src/b.py": "def z():\n    pass\n\n\ndef a():\n    if 1:\n        pass\n",
            "src/a.js": "export const k = (x) => x ? 1 : 0;\n",
        },
    )
    complexity = report.metrics["complexity"]
    assert complexity["status"] == "available"
    assert complexity["conventions"]["cyclomatic"] == "cyclomatic/1"
    assert complexity["conventions"]["cognitive"] == "cognitive/1"
    assert complexity["conventions"]["optional_chaining_counted"] is False
    assert "not a SonarSource score" in complexity["conventions"]["cognitive_note"]
    assert complexity["thresholds"] == {
        "cyclomatic_warn": 15,
        "cognitive_warn": 15,
        "max_nesting_warn": 4,
        "npath_warn": 200,
        "fan_out_warn": 20,
        "max_lines_warn": 50,
    }
    assert [(f["path"], f["name"]) for f in complexity["functions"]] == [
        ("src/a.js", "<module>"),
        ("src/a.js", "k"),
        ("src/b.py", "<module>"),
        ("src/b.py", "z"),
        ("src/b.py", "a"),
    ]
    assert [f["key"] for f in complexity["functions"]][1] == "src/a.js::k"
    assert complexity["files"]["src/b.py"] == {
        "units": 3,
        "cyclomatic_total": 4,
        "cyclomatic_max": 2,
        "cognitive_total": 1,
        "cognitive_max": 1,
        "nesting_max": 1,
        "npath_max": 2,
        "npath_saturated_units": 0,
        "logical_lines": 5,
        "statements": 5,
    }
    arrow = complexity["functions"][1]
    assert arrow["kind"] == "arrow"
    assert arrow["npath"] == {"value": 2, "saturated": False, "cap": 10000, "text": "2"}
    assert json.dumps(report.to_json_dict(), sort_keys=True)  # serializable


def test_complexity_disabled_reports_status_and_runs_no_rule(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nenabled = false\n")
    deep = (
        "def f(a):\n"
        + "".join("    " * (i + 1) + f"if a{i}:\n" for i in range(6))
        + "    " * 7
        + "pass\n"
    )
    report = _file_report(empty_root, config, {"src/a.py": deep})
    assert report.metrics["complexity"]["status"] == "disabled"
    assert report.metrics["complexity"]["reason"] == "complexity.enabled = false"
    assert report.metrics["complexity"]["functions"] == []
    assert report.metrics["graph"]["status"] == "disabled"
    assert report.findings == ()
    assert "CPLX003" not in report.files[0].rules_applied
    assert "CPLX003" in [d.rule_id for d in report.files[0].rules_disabled]
    assert "complexity is disabled" in config.deviations


def test_unit_rules_name_value_threshold_and_convention(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(
        "[tool.shockharness.complexity]\ncyclomatic_warn = 2\ncognitive_warn = 2\n"
        "max_nesting_warn = 1\nnpath_warn = 4\nnpath_only_without_cognitive = false\n"
    )
    text = "def f(a, b):\n    if a:\n        if b:\n            return 1\n    return 0\n"
    result = analyze_text("src/a.py", PY, text, config, OPTIONS)
    rows = {f.rule_id: f for f in result.findings}
    assert set(rows) == {"CPLX001", "CPLX002", "CPLX003"}
    assert all(f.severity == "warning" for f in rows.values())
    assert all(f.span.line == 1 and f.scope == "f" for f in rows.values())
    assert rows["CPLX001"].message == (
        "cyclomatic complexity of function f is 3, above cyclomatic_warn = 2 "
        "(convention cyclomatic/1)"
    )
    assert "cognitive/1; not a Sonar score" in rows["CPLX002"].message
    assert "nesting depth of function f is 2, above max_nesting_warn = 1" in rows["CPLX003"].message
    assert result.status == "analyzed"
    flat = (
        "def g(a, b, c):\n    if a:\n        pass\n    if b:\n        pass\n"
        "    if c:\n        pass\n"
    )
    npath = analyze_text("src/b.py", PY, flat, config, OPTIONS)
    (finding,) = [f for f in npath.findings if f.rule_id == "CPLX004"]
    assert "NPath estimate of function g is 8, at or above npath_warn = 4" in finding.message
    assert "npath/1" in finding.message


def test_complexity_warnings_never_fail_a_plain_check(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\ncognitive_warn = 1\n")
    text = "def f(a):\n    if a:\n        if a:\n            return 1\n    return 0\n"
    report = _file_report(empty_root, config, {"src/a.py": text})
    assert [f.rule_id for f in report.findings] == ["CPLX002"]
    assert report.gate.status == "pass"
    assert report.gate.exit_code == 0
    assert report.gate.warnings == 1
    assert report.gate.hard_violations == 0


def test_complexity_rules_can_be_disabled_per_path_and_suppressed_inline(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(
        "[tool.shockharness.complexity]\ncognitive_warn = 1\n"
        '[[tool.shockharness.overrides]]\npaths = ["src/legacy/**"]\ndisable = ["CPLX002"]\n'
        'reason = "legacy"\n'
    )
    text = "def f(a):\n    if a:\n        if a:\n            return 1\n    return 0\n"
    legacy = analyze_text("src/legacy/a.py", PY, text, config, OPTIONS)
    assert legacy.findings == ()
    assert "CPLX002" in [d.rule_id for d in legacy.rules_disabled]
    assert "CPLX001" in legacy.rules_applied
    suppressed = analyze_text(
        "src/a.py",
        PY,
        'def f(a):  # shockharness: ignore[CPLX002] reason="state machine"\n'
        "    if a:\n        if a:\n            return 1\n    return 0\n",
        config,
        OPTIONS,
    )
    (finding,) = suppressed.findings
    assert finding.rule_id == "CPLX002" and finding.is_suppressed
    assert finding.fingerprint is not None


# --- CPLX006: unit size ------------------------------------------------------------------


def _long_function(name: str, body_lines: int) -> str:
    return f"def {name}():\n" + "".join(f"    x{i} = 1\n" for i in range(body_lines))


def test_cplx006_reports_units_above_max_lines_warn_and_exempts_module_bodies(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # the def line counts: 50 body lines make a 51-line unit; 49 make a 50-line one
    text = _long_function("long", 50) + "\n\n" + _long_function("fits", 49) + "\n"
    report = _file_report(empty_root, strict_config, {"src/a.py": text})
    units = {f["name"]: f for f in report.metrics["complexity"]["functions"]}
    assert units["long"]["size"]["logical_lines"] == 51
    assert units["fits"]["size"]["logical_lines"] == 50
    findings = [f for f in report.findings if f.rule_id == "CPLX006"]
    assert [(f.scope, f.span.line, f.severity) for f in findings] == [("long", 1, "warning")]
    assert findings[0].message == (
        "size of function long is 51 logical line(s), above max_lines_warn = 50 "
        "(convention size/1; module bodies are exempt)"
    )
    assert report.gate.status == "pass"
    # the module body alone, of any length, is never reported
    module_only = "".join(f"x{i} = 1\n" for i in range(120))
    (empty_root / "src" / "a.py").unlink()
    report = _file_report(empty_root, strict_config, {"src/m.py": module_only})
    assert [f.rule_id for f in report.findings] == []
    assert report.metrics["complexity"]["functions"][0]["size"]["logical_lines"] == 120


def test_cplx006_javascript_and_threshold_key(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nmax_lines_warn = 3\n")
    text = "function f() {\n  a();\n  b();\n  c();\n}\nfunction g() {\n  a();\n}\n"
    report = _file_report(empty_root, config, {"src/a.js": text})
    (finding,) = [f for f in report.findings if f.rule_id == "CPLX006"]
    assert finding.scope == "f"
    assert "is 5 logical line(s), above max_lines_warn = 3" in finding.message
    assert report.metrics["complexity"]["thresholds"]["max_lines_warn"] == 3


def test_cplx006_is_disabled_with_the_family(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nenabled = false\n")
    report = _file_report(empty_root, config, {"src/a.py": _long_function("long", 80)})
    assert report.findings == ()
    assert "CPLX006" in [d.rule_id for d in report.files[0].rules_disabled]
    assert "CPLX006" not in report.files[0].rules_applied


# --- CPLX004 folded into CPLX002 (npath_only_without_cognitive) --------------------------

# Eight independent ifs with nested bodies: cognitive 24 (above 15), NPath 3**8 = 6561 >= 200.
BOTH_OVER = "def f(a):\n" + "".join(
    f"    if a{i}:\n        if b{i}:\n            pass\n" for i in range(8)
)
# Eight flat ifs: cognitive 8 (not above 15), NPath 256 (at or above 200).
NPATH_ONLY = "def g(a):\n" + "".join(f"    if a{i}:\n        pass\n" for i in range(8))


def _rules_for(report: Any, name: str) -> list[str]:
    return [f.rule_id for f in report.findings if f.scope == name]


def test_npath_is_folded_into_cognitive_by_default(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = _file_report(empty_root, strict_config, {"src/a.py": BOTH_OVER + "\n\n" + NPATH_ONLY})
    units = {u["name"]: u for u in report.metrics["complexity"]["functions"]}
    assert units["f"]["cognitive"] == 24 and units["f"]["npath"]["value"] == 6561
    assert units["g"]["cognitive"] == 8 and units["g"]["npath"]["value"] == 256
    assert _rules_for(report, "f") == ["CPLX001", "CPLX002"]  # no separate CPLX004
    assert _rules_for(report, "g") == ["CPLX004"]  # NPath alone is still CPLX004
    (cognitive,) = [f for f in report.findings if f.scope == "f" and f.rule_id == "CPLX002"]
    assert f"cognitive complexity of function f is {units['f']['cognitive']}" in cognitive.message
    assert (
        "its NPath estimate is 6561, at or above npath_warn = 200 (convention npath/1), "
        "reported here instead of as CPLX004 (npath_only_without_cognitive = true)"
        in cognitive.message
    )
    from shockharness.output import text as text_output

    lines = [line for line in text_output.render(report).splitlines() if "src/a.py:1:" in line]
    assert len(lines) == 2  # CPLX001 and the one CPLX002 line naming both numbers
    assert sum(1 for line in lines if "NPath" in line) == 1
    # the per-unit numbers are unchanged in metrics
    assert units["f"]["npath"] == {"value": 6561, "saturated": False, "cap": 10000, "text": "6561"}


def test_npath_option_off_reports_both_rule_ids(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nnpath_only_without_cognitive = false\n")
    report = _file_report(empty_root, config, {"src/a.py": BOTH_OVER})
    assert _rules_for(report, "f") == ["CPLX001", "CPLX002", "CPLX004"]
    (cognitive,) = [f for f in report.findings if f.rule_id == "CPLX002"]
    assert "NPath" not in cognitive.message
    assert config.deviations == ()  # reporting both is not a loosening


def test_npath_folding_needs_cplx002_active(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(
        '[[tool.shockharness.overrides]]\npaths = ["src/**"]\ndisable = ["CPLX002"]\n'
        'reason = "test"\n'
    )
    report = _file_report(empty_root, config, {"src/a.py": BOTH_OVER})
    assert _rules_for(report, "f") == ["CPLX001", "CPLX004"]
