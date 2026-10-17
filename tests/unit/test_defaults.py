"""DEF001-DEF006: default and fallback rules, per rule, per language, per confidence level."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import (
    CONTEXT_ARGUMENT,
    CONTEXT_ASSIGNMENT,
    CONTEXT_RETURN,
    FAMILY_TRUTHINESS,
    KIND_DATACLASS_FACTORY,
    KIND_DATACLASS_FIELD,
    KIND_MAPPING_GET_IMPLICIT,
    KIND_PARAMETER,
)
from shockharness.ir.python import extract_python_facts
from shockharness.source import SourceText
from tests.conftest import FIXTURES, fixture_config, language_for_fixture

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
PY = "python"
JS = "javascript"


def _run(config: EffectiveConfig, language: str, text: str) -> FileResult:
    return analyze_text("t.py" if language == PY else "t.js", language, text, config, OPTIONS)


def _rows(result: FileResult, rule_id: str) -> list[tuple[int, str, str]]:
    return [
        (f.span.line, f.severity, f.confidence) for f in result.findings if f.rule_id == rule_id
    ]


def _ids(result: FileResult) -> list[str]:
    return [f.rule_id for f in result.findings]


def _defaults_config(make_config: Callable[[str], EffectiveConfig], body: str) -> EffectiveConfig:
    return make_config("[tool.shockharness.rules.defaults]\n" + body)


# --- DEF001: parameter defaults ---------------------------------------------------------------


def test_def001_python_parameter_forms(strict_config: EffectiveConfig) -> None:
    text = (
        "def f(a, b=1, *args, c=None, **kwargs):\n    return a\n"
        "g = lambda x, y=2: x\n"
        "async def h(url, timeout=TIMEOUT):\n    return url\n"
    )
    result = _run(strict_config, PY, text)
    rows = [
        (f.span.line, f.span.column, f.message) for f in result.findings if f.rule_id == "DEF001"
    ]
    assert [(r[0], r[1]) for r in rows] == [(1, 12), (1, 24), (3, 17), (4, 26)]
    assert rows[0][2] == "parameter 'b' of f() has a default value: 1"
    assert rows[2][2] == "parameter 'y' of lambda has a default value: 2"
    assert all(f.severity == "error" and f.confidence == "exact" for f in result.findings)
    assert all(f.safe_autofix is False for f in result.findings)


def test_def001_overload_ellipsis_and_variadics_are_not_defaults(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "from typing import overload\n"
        "@overload\ndef read(path: str, binary: bool = ...) -> str: ...\n"
        "def read(path, binary):\n    return path\n"
        "def v(*args, **kwargs):\n    return args\n"
    )
    assert _ids(_run(strict_config, PY, text)) == []
    plain = "def read(path, binary=...):\n    return path\n"
    assert _ids(_run(strict_config, PY, plain)) == ["DEF001"]


def test_def001_javascript_parameter_forms(strict_config: EffectiveConfig) -> None:
    text = (
        "function f(a, b = 1, ...rest) {}\n"
        "const g = (x, y = []) => x;\n"
        "class K { constructor(c = null) {} m(d = {}) {} }\n"
        "function d({ retries = 3, verbose }, [first = 0] = []) {}\n"
    )
    result = _run(strict_config, JS, text)
    rows = [(f.span.line, f.span.column, f.scope) for f in result.findings if f.rule_id == "DEF001"]
    assert rows == [
        (1, 19, "f"),
        (2, 19, "g"),
        (3, 27, "K.constructor"),
        (3, 42, "K.m"),
        (4, 24, "d"),
        (4, 47, "d"),
        (4, 52, "d"),
    ]
    messages = [f.message for f in result.findings if f.rule_id == "DEF001"]
    assert "parameter 'b' of f has a default value: 1" in messages
    assert "destructuring default for 'retries' in parameters: 3" in messages
    assert "parameter '[first = 0]' of d has a default value: []" in messages


def test_def001_dataclass_fields_have_their_own_kinds_and_key(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "from dataclasses import dataclass, field\nfrom typing import ClassVar\n"
        "@dataclass\nclass S:\n    host: str\n    port: int = 1\n"
        "    tags: list = field(default_factory=list)\n    label: str = field(default='x')\n"
        "    registry: ClassVar[dict] = {}\n    required: float = field()\n"
        "class Plain:\n    limit: int = 1\n"
    )
    facts = extract_python_facts(SourceText.from_text(text), "t.py")
    kinds = [(f.span.line, f.kind, f.subject) for f in facts.defaults]
    assert kinds == [
        (6, KIND_DATACLASS_FIELD, "port"),
        (7, KIND_DATACLASS_FACTORY, "tags"),
        (8, KIND_DATACLASS_FIELD, "label"),
    ]
    assert _rows(_run(strict_config, PY, text), "DEF001") == [
        (6, "error", "exact"),
        (7, "error", "exact"),
        (8, "error", "exact"),
    ]
    review = _defaults_config(make_config, 'dataclass_fields = "review"\n')
    assert {r[1] for r in _rows(_run(review, PY, text), "DEF001")} == {"review"}
    allowed = _defaults_config(make_config, 'dataclass_fields = "allow"\n')
    assert _rows(_run(allowed, PY, text), "DEF001") == []
    # The dataclass key does not touch ordinary parameter defaults.
    assert _rows(_run(allowed, PY, "def f(x=1):\n    return x\n"), "DEF001") == [
        (1, "error", "exact")
    ]


# --- DEF002: mapping / attribute / property fallbacks --------------------------------------------


def test_def002_receiver_knowledge_sets_confidence(strict_config: EffectiveConfig) -> None:
    text = (
        "from collections.abc import Mapping\nCONFIG = {}\n"
        "def f(options: dict, payload, extra: Mapping):\n"
        "    a = CONFIG.get('timeout', 1)\n"
        "    b = options.get('retries', 1)\n"
        "    c = payload.get('items', [])\n"
        "    d = extra.setdefault('k', 0)\n"
        "    e = payload.pop('k', None)\n"
        "    return a, b, c, d, e\n"
    )
    assert _rows(_run(strict_config, PY, text), "DEF002") == [
        (4, "error", "exact"),
        (5, "error", "exact"),
        (6, "error", "approximate"),
        (7, "error", "exact"),
        (8, "error", "approximate"),
    ]
    approximate = next(f for f in _run(strict_config, PY, text).findings if f.span.line == 6)
    assert "receiver's type is not established" in approximate.message
    assert approximate.message.startswith(
        "payload['items'] falls back to [] when the key is missing"
    )


def test_def002_implicit_none_is_review_and_conservative(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "def f(table: dict, payload, client, url):\n"
        "    a = table.get('a')\n"  # known mapping: exact review
        "    b = payload.get('b')\n"  # unknown receiver, string key: approximate review
        "    c = payload.get(url)\n"  # unknown receiver, variable key: nothing
        "    d = client.get(url)\n"  # looks like an HTTP client: nothing
        "    if table.get('e') is None:\n"  # compared with None: handled, nothing
        "        raise KeyError('e')\n"
        "    g = table.get('g') or []\n"  # the 'or' is the finding (DEF003), not the .get
        "    return a, b, c, d, g\n"
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF002") == [(2, "review", "exact"), (3, "review", "approximate")]
    assert _rows(result, "DEF003") == [(8, "review", "exact")]
    assert "yields None for a missing key" in result.findings[0].message
    # The mode applies to explicit fallbacks; implicit None stays review unless allowed.
    forbid = _run(strict_config, PY, "def f(t: dict):\n    return t.get('a')\n")
    assert _rows(forbid, "DEF002") == [(2, "review", "exact")]
    allowed = _defaults_config(make_config, 'missing_value_fallbacks = "allow"\n')
    assert _rows(_run(allowed, PY, "def f(t: dict):\n    return t.get('a', 1)\n"), "DEF002") == []
    awaited = "async def f(c):\n    return await c.get('a')\n"
    assert _rows(_run(strict_config, PY, awaited), "DEF002") == []


def test_def002_getattr_and_membership_ternary(strict_config: EffectiveConfig) -> None:
    text = (
        "def f(obj, table, key):\n"
        "    a = getattr(obj, 'retries', 1)\n"
        "    b = getattr(obj, 'retries')\n"
        "    c = table[key] if key in table else 'missing'\n"
        "    d = 'missing' if key not in table else table[key]\n"
        "    e = table[key] if key in table else table['other']\n"
        "    return a, b, c, d, e\n"
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF002") == [
        (2, "error", "exact"),
        (4, "error", "exact"),
        (5, "error", "exact"),
        (6, "error", "approximate"),
    ]
    assert result.findings[0].message.startswith(
        "obj.'retries' falls back to 1 when the attribute is missing"
    )


def test_def002_javascript_property_and_destructuring_forms(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "const { retries = 3, verbose } = options;\n"
        "const [first = 0] = pair;\n"
        "const a = options?.retries ?? 1;\n"
        "const b = options.mode ?? other;\n"
        "const c = map.get(key) ?? null;\n"
        "options.cache ??= new Map();\n"
        "const d = k in o ? o[k] : 0;\n"
        "const e = o.hasOwnProperty(k) ? o[k] : [];\n"
        "const f = Object.hasOwn(o, 'k') ? o.k : {};\n"
        "const g = other.x == null ? 1 : other.x;\n"
        "for (const { id, label = 'none' } of rows) {}\n"
        "({ port = 80 } = options);\n"
        "const bare = o.x;\nconst chained = o?.x?.y;\nconst got = map.get(k);\n"
    )
    result = _run(strict_config, JS, text)
    assert _rows(result, "DEF002") == [
        (1, "error", "exact"),
        (2, "error", "exact"),
        (3, "error", "exact"),
        (4, "error", "approximate"),
        (5, "error", "exact"),
        (6, "error", "exact"),
        (7, "error", "exact"),
        (8, "error", "exact"),
        (9, "error", "exact"),
        (10, "error", "exact"),
        (11, "error", "exact"),
        (12, "error", "exact"),
    ]
    assert _ids(result).count("DEF004") == 0


# --- DEF003: truthiness fallbacks ---------------------------------------------------------------


def test_def003_is_review_by_default_and_forbid_makes_it_an_error(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = "def f(items):\n    return items or []\n"
    assert _rows(_run(strict_config, PY, text), "DEF003") == [(2, "review", "exact")]
    forbid = _defaults_config(make_config, 'truthiness_fallbacks = "forbid"\n')
    assert _rows(_run(forbid, PY, text), "DEF003") == [(2, "error", "exact")]
    assert "truthiness_fallbacks" not in "\n".join(forbid.deviations)
    allowed = _defaults_config(make_config, 'truthiness_fallbacks = "allow"\n')
    assert _rows(_run(allowed, PY, text), "DEF003") == []
    assert any("rules.defaults.truthiness_fallbacks is 'allow'" in d for d in allowed.deviations)


def test_def003_contexts_and_boolean_logic(strict_config: EffectiveConfig) -> None:
    text = (
        "def f(a, b, flag, items):\n"
        "    x = a or b\n"  # assignment, non-constant: approximate
        "    call(a or b)\n"  # argument, non-constant: nothing
        "    call(a or 0)\n"  # argument, constant: exact
        "    if a or b:\n"  # Boolean test: nothing
        "        pass\n"
        "    ok = a == b or flag\n"  # Boolean logic: nothing
        "    found = a in items or b in items\n"  # Boolean logic: nothing
        "    y = a or b or 'z'\n"  # chain, constant end: exact, reported once
        "    z = a if a else 'empty'\n"  # ternary spelling: exact
        "    both = a and b\n"  # 'and' is never a fallback
        "    return a or b\n"  # return, non-constant: approximate
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF003") == [
        (2, "review", "approximate"),
        (4, "review", "exact"),
        (9, "review", "exact"),
        (10, "review", "exact"),
        (12, "review", "approximate"),
    ]
    approximate = next(f for f in result.findings if f.rule_id == "DEF003")
    assert "may be a fallback or a legitimate alternative" in approximate.message
    chain = next(f for f in result.findings if f.span.line == 9)
    assert chain.message.startswith("a or b falls back to 'z' when falsy")
    facts = extract_python_facts(SourceText.from_text(text), "t.py")
    contexts = {f.span.line: f.context for f in facts.defaults if f.family == FAMILY_TRUTHINESS}
    assert contexts == {
        2: CONTEXT_ASSIGNMENT,
        4: CONTEXT_ARGUMENT,
        9: CONTEXT_ASSIGNMENT,
        10: CONTEXT_ASSIGNMENT,
        12: CONTEXT_RETURN,
    }


def test_def003_javascript_forms(strict_config: EffectiveConfig) -> None:
    text = (
        "function f(a, b, items) {\n"
        "  const list = items || [];\n"
        "  let total = a || b;\n"
        "  total ||= 1;\n"
        "  if (a || b) { step(); }\n"
        "  const ok = a === b || flag;\n"
        "  const done = !(a || b);\n"
        "  const t = a ? a : 'empty';\n"
        "  return a || b || 'z';\n"
        "}\n"
    )
    assert _rows(_run(strict_config, JS, text), "DEF003") == [
        (2, "review", "exact"),
        (3, "review", "approximate"),
        (4, "review", "exact"),
        (8, "review", "exact"),
        (9, "review", "exact"),
    ]


# --- DEF004: nullish fallbacks ------------------------------------------------------------------


def test_def004_python_conditional_expressions(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "def f(limit, rows, node, flag, other):\n"
        "    a = limit if limit is not None else 1\n"
        "    b = [] if rows is None else rows\n"
        "    c = limit if limit != None else other\n"
        "    d = None if node is None else node.strip()\n"  # propagation: nothing
        "    e = 'on' if flag is not None else 'off'\n"  # a choice: nothing
        "    if limit is None:\n        limit = 1\n"  # statement form: nothing
        "    return a, b, c, d, e\n"
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF004") == [
        (2, "error", "exact"),
        (3, "error", "exact"),
        (4, "error", "approximate"),
    ]
    assert result.findings[0].message.startswith("limit falls back to 1 when None")
    review = _defaults_config(make_config, 'nullish_fallbacks = "review"\n')
    assert {r[1] for r in _rows(_run(review, PY, text), "DEF004")} == {"review"}
    assert any("rules.defaults.nullish_fallbacks is 'review'" in d for d in review.deviations)


def test_def004_javascript_forms(strict_config: EffectiveConfig) -> None:
    text = (
        "function f(count, other, value) {\n"
        "  const n = count ?? 0;\n"
        "  const l = count ?? other;\n"
        "  let s = count;\n  s ??= {};\n"
        "  const a = value === undefined ? 1 : value;\n"
        "  const b = value != null ? value : [];\n"
        "  const c = typeof value === 'undefined' ? 0 : value;\n"
        "  const d = value == null ? null : value.name;\n"  # propagation: nothing
        "  const e = value === null ? 'on' : 'off';\n"  # a choice: nothing
        "  const g = count ?? null;\n"  # still a substitution
        "  if (count ?? other) {}\n"  # Boolean test: nothing
        "  return [n, l, s, a, b, c, d, e, g];\n"
        "}\n"
    )
    result = _run(strict_config, JS, text)
    assert _rows(result, "DEF004") == [
        (2, "error", "exact"),
        (3, "error", "approximate"),
        (5, "error", "exact"),
        (6, "error", "exact"),
        (7, "error", "exact"),
        (8, "error", "exact"),
        (11, "error", "exact"),
    ]
    first = next(f for f in result.findings if f.rule_id == "DEF004")
    assert first.message.startswith("count falls back to 0 when null or undefined")


# --- DEF005: exception-to-default ---------------------------------------------------------------


def test_def005_literal_returns_are_exact_and_traces_are_approximate(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "DEFAULT = {}\n"
        "def empty():\n    return []\n"
        "def a(p):\n    try:\n        return read(p)\n    except OSError:\n        return None\n"
        "def b(p):\n    try:\n        return read(p)\n    except OSError:\n        return DEFAULT\n"
        "def c(p):\n    try:\n        return read(p)\n    except OSError as exc:\n"
        "        print(exc)\n        return empty()\n"
        "def d(p):\n    try:\n        return read(p)\n    except OSError:\n        return dict()\n"
        "def e(p, default):\n    try:\n        return read(p)\n    except OSError:\n"
        "        return default\n"
        "def f(p):\n    try:\n        return read(p)\n    except OSError:\n"
        "        return IMPORTED\n"
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF005") == [
        (7, "error", "exact"),
        (12, "error", "approximate"),
        (17, "error", "approximate"),
        (23, "error", "exact"),
    ]
    messages = [f.message for f in result.findings if f.rule_id == "DEF005"]
    assert "return None (EXC002 classification return_fallback" in messages[0]
    assert "returns DEFAULT, bound at module level to {}" in messages[1]
    assert "delegates to empty(), a module-level helper whose body is 'return []'" in messages[2]
    assert "fabricates an empty value in place: return dict()" in messages[3]
    assert "EXC002" not in _ids(result)  # return_fallback is counted once, as DEF005
    assert _ids(result).count("EXC001") == 6


def test_def005_javascript_traces(strict_config: EffectiveConfig) -> None:
    text = (
        "const EMPTY = [];\nfunction rows() { return []; }\nconst obj = () => ({});\n"
        "function a(r) { try { return JSON.parse(r); } catch (e) { return EMPTY; } }\n"
        "function b(r) { try { return JSON.parse(r); } catch (e) { return rows(); } }\n"
        "function c(r) { try { return JSON.parse(r); } catch (e) { return obj(); } }\n"
        "function d(r) { try { return JSON.parse(r); } catch (e) { return new Map(); } }\n"
        "function e(r) { try { return JSON.parse(r); } catch (e) { return null; } }\n"
        "function f(r) { try { return JSON.parse(r); } catch (e) { return OTHER; } }\n"
        "const g = fetch(u).catch(() => null);\n"
    )
    result = _run(strict_config, JS, text)
    assert _rows(result, "DEF005") == [
        (4, "error", "approximate"),
        (5, "error", "approximate"),
        (6, "error", "approximate"),
        (7, "error", "exact"),
        (8, "error", "exact"),
        (10, "error", "exact"),
    ]


def test_def005_disabled_restores_exc002_return_fallback(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    text = "def a(p):\n    try:\n        return read(p)\n    except OSError:\n        return None\n"
    config = make_config("[tool.shockharness.rules.defaults]\nenabled = false\n")
    result = _run(config, PY, text)
    assert _ids(result) == ["EXC001", "EXC002"]
    assert [d.rule_id for d in result.rules_disabled] == [
        "DEF001",
        "DEF002",
        "DEF003",
        "DEF004",
        "DEF005",
        "DEF006",
    ]
    assert "rules.defaults is disabled" in config.deviations


# --- DEF006: configuration fallbacks ------------------------------------------------------------


def test_def006_python_forms_follow_every_import_spelling(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "import os\nimport os as o\nfrom os import environ, getenv as ge\n"
        "a = os.getenv('A', '1')\n"
        "b = os.environ.get('B', '1')\n"
        "c = os.getenv('C', default='1')\n"
        "d = os.environ.get('D') or '1'\n"
        "e = os.environ['E'] if 'E' in os.environ else '1'\n"
        "f = os.getenv('F')\n"
        "g = os.environ.setdefault('G', '1')\n"
        "h = o.getenv('H', '1')\n"
        "i = environ.get('I', '1')\n"
        "j = ge('J', '1')\n"
        "k = ge('K') if ge('K') is not None else '1'\n"
        "m = os.environ['M']\n"
        "n = os.getenv('N')\nif n is None:\n    raise RuntimeError('N')\n"
    )
    result = _run(strict_config, PY, text)
    assert _rows(result, "DEF006") == [
        (4, "error", "exact"),
        (5, "error", "exact"),
        (6, "error", "exact"),
        (7, "error", "exact"),
        (8, "error", "exact"),
        (9, "review", "exact"),
        (10, "error", "exact"),
        (11, "error", "exact"),
        (12, "error", "exact"),
        (13, "error", "exact"),
        (14, "error", "exact"),
        (16, "review", "exact"),
    ]
    assert {"DEF002", "DEF003", "DEF004"}.isdisjoint(_ids(result))  # DEF006 owns env reads
    assert result.findings[0].message.startswith("environment variable 'A' falls back to '1'")
    implicit = next(f for f in result.findings if f.span.line == 9)
    assert "yields None when the variable is unset" in implicit.message
    allowed = _defaults_config(make_config, 'configuration_fallbacks = "allow"\n')
    assert _rows(_run(allowed, PY, text), "DEF006") == []
    assert any("configuration_fallbacks is 'allow'" in d for d in allowed.deviations)


def test_def006_javascript_forms(strict_config: EffectiveConfig) -> None:
    text = (
        "const port = process.env.PORT || '3000';\n"
        "const host = process.env.HOST ?? 'localhost';\n"
        "const region = process.env['REGION'] || 'eu';\n"
        "const workers = Number(process.env.WORKERS || 1);\n"
        "const mode = process.env.MODE === undefined ? 'dev' : process.env.MODE;\n"
        "process.env.NODE_ENV ||= 'development';\n"
        "process.env.TZ ??= 'UTC';\n"
        "const { USER = 'me', HOME } = process.env;\n"
        "const token = process.env.TOKEN;\n"
        "const level = process.env.LEVEL ?? process.env.FALLBACK;\n"
    )
    result = _run(strict_config, JS, text)
    assert _rows(result, "DEF006") == [
        (1, "error", "exact"),
        (2, "error", "exact"),
        (3, "error", "exact"),
        (4, "error", "exact"),
        (5, "error", "exact"),
        (6, "error", "exact"),
        (7, "error", "exact"),
        (8, "error", "exact"),
        (10, "error", "exact"),  # process.env.FALLBACK is constant-shaped (UPPER_CASE)
    ]
    assert {"DEF002", "DEF003", "DEF004"}.isdisjoint(_ids(result))
    first = next(f for f in result.findings if f.rule_id == "DEF006")
    assert first.message.startswith("environment variable PORT falls back to '3000'")


# --- shared behaviour -------------------------------------------------------------------------


def test_default_findings_are_suggestions_only_and_carry_scope(
    strict_config: EffectiveConfig,
) -> None:
    text = "class C:\n    def m(self):\n        def inner(x=1):\n            return x or 0\n"
    result = _run(strict_config, PY, text)
    assert [(f.rule_id, f.scope) for f in result.findings] == [
        ("DEF001", "C.m.inner"),
        ("DEF003", "C.m.inner"),
    ]
    assert all(f.safe_autofix is False for f in result.findings)
    assert all(f.remediation != "" for f in result.findings)


def test_default_findings_can_be_suppressed_inline(strict_config: EffectiveConfig) -> None:
    text = (
        'def f(x=None):  # shockharness: ignore[DEF001] reason="public API compatibility"\n'
        "    return x\n"
    )
    result = _run(strict_config, PY, text)
    assert [(f.rule_id, f.is_suppressed) for f in result.findings] == [("DEF001", True)]


def test_overrides_can_disable_one_default_rule(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        '[[tool.shockharness.overrides]]\npaths = ["tests/**"]\ndisable = ["DEF001"]\n'
        'reason = "fixture signatures"\n'
    )
    text = "def f(x=1):\n    return x or 0\n"
    inside = analyze_text("tests/t.py", PY, text + "\n\ndef test_f():\n    f()\n", config, OPTIONS)
    assert _ids(inside) == ["DEF003"]
    assert [d.rule_id for d in inside.rules_disabled] == ["DEF001"]
    outside = analyze_text("src/t.py", PY, text, config, OPTIONS)
    assert _ids(outside) == ["DEF001", "DEF003"]


def test_new_mode_keys_are_validated(make_config: Callable[[str], EffectiveConfig]) -> None:
    for key in ("dataclass_fields", "nullish_fallbacks", "configuration_fallbacks"):
        with pytest.raises(ConfigError) as info:
            _defaults_config(make_config, f'{key} = "maybe"\n')
        assert f"rules.defaults.{key}" in str(info.value)
        assert "'forbid', 'review', 'allow'" in str(info.value)
    with pytest.raises(ConfigError) as unknown:
        _defaults_config(make_config, 'exception_fallbacks = "forbid"\n')
    assert "unknown key" in str(unknown.value)


def test_strict_defaults_report_no_deviation_and_loosening_is_listed(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    assert not any("rules.defaults." in d for d in strict_config.deviations)
    loosened = _defaults_config(
        make_config,
        'function_parameters = "review"\nmissing_value_fallbacks = "allow"\n'
        'truthiness_fallbacks = "forbid"\n',
    )
    listed = [d for d in loosened.deviations if d.startswith("rules.defaults.")]
    assert listed == [
        "rules.defaults.function_parameters is 'review' (strict profile: 'forbid'); DEF001 "
        "findings of that kind are reported as review",
        "rules.defaults.missing_value_fallbacks is 'allow' (strict profile: 'forbid'); DEF002 "
        "findings of that kind are not reported",
    ]


def test_every_fixture_finding_is_a_suggestion(empty_root: Path) -> None:
    expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for name in sorted(expected):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        config = fixture_config(name, expected[name], empty_root)
        result = analyze_text(name, language_for_fixture(name), text, config, OPTIONS)
        for finding in result.findings:
            seen.add(finding.rule_id)
            assert finding.safe_autofix is False, (name, finding)
            assert finding.confidence in ("exact", "approximate", "unresolved"), (name, finding)
    assert {"DEF001", "DEF002", "DEF003", "DEF004", "DEF005", "DEF006"} <= seen


def test_javascript_facts_record_kind_and_context() -> None:
    text = "function f(a = 1) { const m = o.get(k); return a ?? 0; }\n"
    facts = extract_javascript_facts(SourceText.from_text(text), "t.js")
    assert [(f.kind, f.context) for f in facts.defaults] == [
        (KIND_PARAMETER, "declaration"),
        ("coalesce", CONTEXT_RETURN),
    ]
    assert all(f.kind != KIND_MAPPING_GET_IMPLICIT for f in facts.defaults)


def test_def001_dataclass_fields_only_on_decorated_classes(strict_config: EffectiveConfig) -> None:
    """Item 7 of the 0.2.0 feedback round: annotated class attributes of an undecorated
    class or an ORM-style model are not dataclass fields and are not reported."""
    text = (
        "import dataclasses\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Optional\n\n\n"
        "class Plain:\n"
        "    id: int = 1\n"
        "    encryption_nonce: Optional[bytes] = None\n"
        "    tags: list = []\n\n\n"
        "class User(Base):\n"
        "    __tablename__ = 'users'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    name: Mapped[str] = mapped_column(String(50), default='anon')\n"
        "    created: datetime = Column(DateTime, default=datetime.utcnow)\n\n\n"
        "@dataclasses.dataclass\n"
        "class Qualified:\n"
        "    id: int = 1\n\n\n"
        "@dataclasses.dataclass(frozen=True)\n"
        "class QualifiedWithArguments:\n"
        "    nonce: Optional[bytes] = None\n\n\n"
        "@dataclass\n"
        "class Bare:\n"
        "    tags: list = field(default_factory=list)\n"
    )
    result = _run(strict_config, PY, text)
    def001 = [(f.span.line, f.message) for f in result.findings if f.rule_id == "DEF001"]
    assert def001 == [
        (21, "dataclass field 'id' of Qualified has a default value: 1"),
        (26, "dataclass field 'nonce' of QualifiedWithArguments has a default value: None"),
        (31, "dataclass field 'tags' of Bare has a default_factory: list"),
    ]
    # the ORM model's keyword defaults are DEF001 territory only through a decorator;
    # nothing else in the module is a parameter default either
    assert not any(f.rule_id == "DEF001" and f.span.line < 19 for f in result.findings)


# --- 0.2.0 second brief, item 2: the missing default forms ---------------------------------


def _def(result: FileResult, rule_id: str) -> list[tuple[int, str]]:
    return [(f.span.line, f.message) for f in result.findings if f.rule_id == rule_id]


def test_pop_setdefault_and_next_with_defaults(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "d = {}\n"
        "a = d.pop('k', 1)\n"
        "b = d.setdefault('k', 1)\n"
        "c = next(it, 1)\n"
        "e = d.pop('k')\n"
        "f = next(it)\n"
        "g = next(it, default=1)\n"
    )
    result = _run(strict_config, PY, text)
    key_note = "substitutes the fallback for a missing key"
    assert _def(result, "DEF002") == [
        (2, f"d['k'] falls back to 1 when the key is missing; .pop(key, fallback) {key_note}"),
        (
            3,
            "d['k'] falls back to 1 when the key is missing; .setdefault(key, fallback) "
            f"{key_note}",
        ),
        (
            4,
            "next(it) falls back to 1 when the iterator is exhausted; next(iterator, default) "
            "substitutes the default for an exhausted iterator; an empty sequence and a "
            "sequence that ends with the default look the same",
        ),
    ]
    assert all(
        f.severity == "error" and f.confidence == "exact"
        for f in result.findings
        if f.rule_id == "DEF002"
    )
    review = _defaults_config(make_config, 'missing_value_fallbacks = "review"\n')
    assert {r[1] for r in _rows(_run(review, PY, text), "DEF002")} == {"review"}
    allowed = _defaults_config(make_config, 'missing_value_fallbacks = "allow"\n')
    assert _rows(_run(allowed, PY, text), "DEF002") == []


def test_defaultdict_under_every_import_spelling(strict_config: EffectiveConfig) -> None:
    text = (
        "import collections\n"
        "import collections as c\n"
        "from collections import defaultdict\n"
        "from collections import defaultdict as dd\n"
        "a = collections.defaultdict(list)\n"
        "b = c.defaultdict(int)\n"
        "c2 = defaultdict(lambda: 1)\n"
        "d = dd(set)\n"
        "e = defaultdict()\n"
        "f = other.defaultdict(list)\n"
    )
    result = _run(strict_config, PY, text)
    assert [(f.span.line, f.evidence) for f in result.findings if f.rule_id == "DEF002"] == [
        (5, "a = collections.defaultdict(list)"),
        (6, "b = c.defaultdict(int)"),
        (7, "c2 = defaultdict(lambda: 1)"),
        (8, "d = dd(set)"),
    ]
    assert _def(result, "DEF002")[1][1] == (
        "c.defaultdict(int) falls back to int() for every missing key; defaultdict(factory) "
        "creates factory() for every missing key, so a lookup never fails and a missing key is "
        "indistinguishable from an empty value"
    )
    assert result.findings[0].to_json_dict()["evidence"] == "a = collections.defaultdict(list)"
    # DEF001 is not involved and the lambda factory is not a parameter default
    assert _def(result, "DEF001") == []


def test_pydantic_model_fields_are_dataclass_fields(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "import pydantic\n"
        "from pydantic import BaseModel, Field\n"
        "from typing import ClassVar\n\n\n"
        "class Settings(BaseModel):\n"
        "    host: str\n"
        "    port: int = 5432\n"
        "    retries: int = Field(default=3)\n"
        "    tags: list = Field(default_factory=list)\n"
        "    name: str = Field(..., min_length=1)\n"
        "    required: str = Field()\n"
        "    legacy: int = Field(7)\n"
        "    version: ClassVar[int] = 2\n"
        "    optional: int = ...\n\n\n"
        "class Other(pydantic.BaseModel):\n"
        "    limit: int = 10\n\n\n"
        "class Plain(SomethingElse):\n"
        "    limit: int = 10\n"
    )
    result = _run(strict_config, PY, text)
    assert _def(result, "DEF001") == [
        (8, "pydantic field 'port' of Settings has a default value: 5432"),
        (9, "pydantic field 'retries' of Settings has Field(default=...): 3"),
        (10, "pydantic field 'tags' of Settings has a default_factory: list"),
        (13, "pydantic field 'legacy' of Settings has Field(default=...): 7"),
        (19, "pydantic field 'limit' of Other has a default value: 10"),
    ]
    assert all(f.severity == "error" for f in result.findings if f.rule_id == "DEF001")
    allowed = _defaults_config(make_config, 'dataclass_fields = "allow"\n')
    assert _rows(_run(allowed, PY, text), "DEF001") == []


# --- DEF002: statement forms and fallback helpers (decision 34) --------------------------------

STATEMENT_FORMS = (
    "import os\n\n\n"
    "def lookup(table, key):\n"
    "    if key in table:\n"  # 5: the membership form, error
    "        return table[key]\n"
    "    return 0\n\n\n"
    "def inverted(table, key):\n"
    "    if key not in table:\n"  # 11: the inverted order
    "        return None\n"
    "    return table[key]\n\n\n"
    "def setting(name):\n"
    "    if name in os.environ:\n"  # 17: an environment variable: DEF006
    "        return os.environ[name]\n"
    "    return 'dev'\n\n\n"
    "def distinct(table, key):\n"
    "    if key in table:\n"  # the absent case does its own work: not a fallback
    "        return table[key]\n"
    "    raise KeyError(key)\n"
)


def test_def002_statement_forms(strict_config: EffectiveConfig) -> None:
    result = _run(strict_config, PY, STATEMENT_FORMS)
    assert _rows(result, "DEF002") == [(5, "error", "exact"), (11, "error", "exact")]
    assert _rows(result, "DEF006") == [(17, "error", "exact")]
    message = next(f.message for f in result.findings if f.rule_id == "DEF002")
    assert message == (
        "table[key] falls back to 0 when the key is missing; 'if k in m: return m[k]' followed "
        "by 'return v' is m.get(k, v) spelled out; it substitutes a value for a missing key"
    )


HELPERS = (
    "def value_or(mapping, key, default_value):\n"  # 1: MetaList's _mapping_value_or
    '    """The value, or the default."""\n'
    "    if not isinstance(key, str):\n"
    "        raise TypeError(key)\n"
    "    if key in mapping:\n"  # 5: the helper's own body
    "        return mapping[key]\n"
    "    return default_value\n\n\n"
    "def attribute_or(obj, name, fallback):\n"
    "    return getattr(obj, name, fallback)\n\n\n"  # 11
    "def item_or(items, index, fallback):\n"
    "    try:\n        return items[index]\n    except IndexError:\n        return fallback\n\n\n"
    "def posting_or_empty(index, tag):\n"  # a fixed default: not a helper
    "    if tag in index:\n"  # 22: still the fallback, whatever the helper is called
    "        return index[tag]\n"
    "    return ()\n\n\n"
    "class Store:\n"
    "    def value_or(self, key, default):\n"
    "        return self.data.get(key, default)\n\n\n"  # 29: a method
    "def edit(raw, rule, obj, items, store):\n"
    "    count = value_or(raw, 'occurrence_count', 0)\n"  # 33
    "    days = value_or(raw, key='weekdays', default_value=[])\n"  # 34
    "    title = attribute_or(obj, 'title', '')\n"  # 35
    "    first = item_or(items, 0, None)\n"  # 36
    "    other = store.value_or('x', 1)\n"  # a method, not followed by name
    "    return count, days, title, first, other, posting_or_empty(rule, 'a')\n"
)


def test_def002_fallback_helpers_at_review(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    result = _run(strict_config, PY, HELPERS)
    rows = _rows(result, "DEF002")
    helper_calls = [(line, severity) for line, severity, _c in rows if line > 30]
    assert helper_calls == [(33, "review"), (34, "review"), (35, "review"), (36, "review")]
    bodies = [line for line, severity, _c in rows if severity == "error"]
    assert bodies == [5, 11, 22, 29]  # the lookups themselves; the try form is EXC001's
    message = next(f.message for f in result.findings if f.span.line == 34)
    assert message == (
        "value_or(raw, key='weekdays') falls back to [] when the value is missing; value_or "
        "(line 1) returns its default_value argument when the value is missing: it is "
        "m.get(k, default_value) under another name, so the default is chosen at each call"
    )
    forbid = _defaults_config(make_config, 'fallback_helpers = "forbid"\n')
    assert [r[1] for r in _rows(_run(forbid, PY, HELPERS), "DEF002") if r[0] > 30] == ["error"] * 4
    allow = _defaults_config(make_config, 'fallback_helpers = "allow"\n')
    assert [r for r in _rows(_run(allow, PY, HELPERS), "DEF002") if r[0] > 30] == []
    assert any("rules.defaults.fallback_helpers is 'allow'" in d for d in allow.deviations)
