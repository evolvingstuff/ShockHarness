"""Property contracts, milestone P1a (docs/shockharness_property_contracts_spec.md):
PROP001, PROP003, PROP006, PROP007 on Python, the catalog and its configuration checks,
and the VERIFY003 loosenings of the section."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig, load_config
from shockharness.errors import ConfigError
from shockharness.loosening import loosenings
from tests.conftest import FIXTURES

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CASES = FIXTURES / "property_contracts"
CASE_NAMES = sorted(
    f"{language.name}/{case.name}"
    for language in CASES.iterdir()
    if language.is_dir()
    for case in language.iterdir()
    if case.is_dir()
)

CATALOG = """\
[tool.shockharness]
include = ["app/**/*.py", "tests/**/*.py"]

[tool.shockharness.rules.property_contracts]
enabled = true
runtime_module = ["app/contracts.py"]
{extra}

[[tool.shockharness.rules.property_contracts.properties]]
name = "redacted"
description = "text with addresses masked"
producers = ["app.text.redact"]
runtime = "static"
"""
TEXT = (
    "from app.contracts import produces\n\n\n"
    'def redact(text):\n    return produces(text, "redacted")\n'
)
DELIVER = (
    "from app.contracts import requires\n\n\n"
    'def deliver(text):\n    requires(text, "redacted")\n    return text\n'
)


def prop_rows(report: Any) -> list[dict[str, Any]]:
    return [
        {
            "path": f.path,
            "rule": f.rule_id,
            "line": f.span.line,
            "column": f.span.column,
            "status": f.status,
            "severity": f.severity,
            "message": f.message,
        }
        for f in report.findings
        if f.rule_id.startswith("PROP")
    ]


def write_project(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def run(root: Path, files: dict[str, str], extra: str) -> Any:
    write_project(root, {".shockharness.toml": CATALOG.format(extra=extra), **files})
    return analyze_paths([root], root, load_config(root, None), OPTIONS)


@pytest.mark.parametrize("case", CASE_NAMES)
def test_fixture_yields_exactly_its_expected_findings(case: str, tmp_path: Path) -> None:
    root = tmp_path / case.replace("/", "-")
    shutil.copytree(CASES / case, root)
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    expected = json.loads((CASES / case / "expected.json").read_text(encoding="utf-8"))
    assert prop_rows(report) == expected


def test_every_fixture_case_has_a_catalog_expectations_and_a_rationale() -> None:
    assert CASE_NAMES == [
        "javascript/calls",
        "javascript/innerhtml",
        "python/callee_sink",
        "python/declarations",
        "python/flow",
        "python/fstring",
        "python/generators",
        "python/stats",
        "python/transitive",
        "typescript/stats",
    ]
    for case in CASE_NAMES:
        for name in (".shockharness.toml", "expected.json", "rationale.md"):
            assert (CASES / case / name).is_file(), (case, name)


def test_an_excluded_runtime_module_resolves_and_is_not_analyzed(tmp_path: Path) -> None:
    root = tmp_path / "callee_sink"
    shutil.copytree(CASES / "python" / "callee_sink", root)
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    assert not any(f.path.startswith("app/vendor/") for f in report.files)
    assert any(row["path"] == "app/chat.py" for row in prop_rows(report))


def test_the_producer_is_read_from_disk_when_only_the_caller_is_analyzed(tmp_path: Path) -> None:
    root = tmp_path / "callee_sink"
    shutil.copytree(CASES / "python" / "callee_sink", root)
    config = load_config(root, None)
    alone = analyze_paths([root / "app" / "chat.py"], root, config, OPTIONS)
    together = analyze_paths([root], root, config, OPTIONS)
    assert [f.path for f in alone.files] == ["app/chat.py"]
    assert prop_rows(alone) == prop_rows(together)


def test_off_by_default_applies_nothing_and_is_not_a_deviation(
    strict_config: EffectiveConfig,
) -> None:
    code = 'from app.contracts import requires\n\n\ndef f(x):\n    requires(x, "nope")\n'
    result = analyze_text("app/f.py", "python", code, strict_config, OPTIONS)
    assert not any(rule.startswith("PROP") for rule in result.rules_applied)
    assert not any(d.rule_id.startswith("PROP") for d in result.rules_disabled)
    assert not any("property_contracts" in line for line in strict_config.deviations)


def test_a_project_callee_keyword_maps_to_its_parameter(empty_root: Path) -> None:
    caller = (
        "from app.deliver import deliver\nfrom app.text import redact\n\n\n"
        "def ok(raw):\n    return deliver(text=redact(raw))\n\n\n"
        "def bad(raw):\n    return deliver(text=raw)\n\n\n"
        "def spread(raw, options):\n    return deliver(**options)\n"
    )
    report = run(
        empty_root,
        {"app/__init__.py": "", "app/text.py": TEXT, "app/deliver.py": DELIVER, "app/c.py": caller},
        "",
    )
    rows = [(r["line"], r["status"]) for r in prop_rows(report)]
    assert rows == [(10, "violation"), (14, "unknown")]


def test_relative_imports_resolve_the_runtime_and_the_callee(empty_root: Path) -> None:
    caller = (
        "from .contracts import requires\nfrom .deliver import deliver\n\n\n"
        'def check(raw):\n    requires(raw, "redacted")\n    return deliver(raw)\n\n\n'
        "def bad(raw):\n    return deliver(raw)\n"
    )
    report = run(
        empty_root,
        {"app/__init__.py": "", "app/text.py": TEXT, "app/deliver.py": DELIVER, "app/c.py": caller},
        "",
    )
    assert [(r["path"], r["line"]) for r in prop_rows(report)] == [("app/c.py", 11)]


def test_roles_limit_the_files_checked(empty_root: Path) -> None:
    test_file = "from app.deliver import deliver\n\n\ndef test_raw():\n    deliver('x')\n"
    files = {
        "app/__init__.py": "",
        "app/text.py": TEXT,
        "app/deliver.py": DELIVER,
        "tests/test_raw.py": test_file,
    }
    assert prop_rows(run(empty_root, files, "")) == []
    widened = run(empty_root, files, 'roles = ["production", "test"]')
    assert [r["path"] for r in prop_rows(widened)] == ["tests/test_raw.py"]


def test_allow_undeclared_makes_prop003_review_and_counts_the_name(empty_root: Path) -> None:
    code = (
        "from app.contracts import produces, requires\n\n\n"
        'def make(x):\n    return produces(x, "extra")\n\n\n'
        'def use(x):\n    requires(x, "extra")\n    return x\n\n\n'
        "def flow(raw):\n    return use(make(raw))\n"
    )
    files = {"app/__init__.py": "", "app/text.py": TEXT, "app/m.py": code}
    strict = prop_rows(run(empty_root, files, ""))
    assert [(r["rule"], r["severity"]) for r in strict] == [
        ("PROP003", "error"),
        ("PROP003", "error"),
    ]
    allowed = prop_rows(run(empty_root, files, "allow_undeclared = true"))
    assert [(r["rule"], r["severity"]) for r in allowed] == [
        ("PROP003", "review"),
        ("PROP003", "review"),
    ]


def test_fail_on_unknown_makes_unknown_prop001_gate(empty_root: Path) -> None:
    caller = (
        "from app.deliver import deliver\n\n\ndef f(raw, ops):\n    return deliver(ops[0](raw))\n"
    )
    files = {
        "app/__init__.py": "",
        "app/text.py": TEXT,
        "app/deliver.py": DELIVER,
        "app/c.py": caller,
    }
    severity = '\n[tool.shockharness.rules.property_contracts.severities]\nPROP001 = "error"\n'
    advisory = run(empty_root, files, "fail_on_unknown = false" + severity)
    assert [(r["status"], r["severity"]) for r in prop_rows(advisory)] == [("unknown", "error")]
    assert advisory.gate.status == "pass"
    gating = run(empty_root, files, "fail_on_unknown = true" + severity)
    assert gating.gate.status == "fail"


def test_reordering_independent_statements_changes_no_finding(empty_root: Path) -> None:
    first = (
        "from app.deliver import deliver\nfrom app.text import redact\n\n\n"
        "def f(raw, other):\n    a = redact(raw)\n    b = other + 1\n"
        "    deliver(b)\n    return deliver(a)\n"
    )
    second = first.replace(
        "    a = redact(raw)\n    b = other + 1\n", "    b = other + 1\n    a = redact(raw)\n"
    )
    files = {"app/__init__.py": "", "app/text.py": TEXT, "app/deliver.py": DELIVER}
    one = prop_rows(run(empty_root, {**files, "app/c.py": first}, ""))
    two = prop_rows(run(empty_root, {**files, "app/c.py": second}, ""))
    assert [(r["line"], r["message"]) for r in one] == [(8, r["message"]) for r in two]


def test_result001_permits_the_runtime_declarations_only_when_they_resolve(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    code = 'from app.contracts import produces\n\n\ndef f(x):\n    produces(x, "redacted")\n'
    must_use = '[tool.shockharness.rules.results]\npython_must_use = ["app.contracts.produces"]\n'
    off = make_config(must_use)
    reported = analyze_text("app/f.py", "python", code, off, OPTIONS)
    assert [f.rule_id for f in reported.findings if f.rule_id == "RESULT001"] == ["RESULT001"]
    on = make_config(
        "\n" + must_use + "\n[tool.shockharness.rules.property_contracts]\nenabled = true\n"
        'runtime_module = ["app/contracts.py"]\n'
        "[[tool.shockharness.rules.property_contracts.properties]]\n"
        'name = "redacted"\ndescription = "d"\nproducers = []\nruntime = "static"\n'
    )
    permitted = analyze_text("app/f.py", "python", code, on, OPTIONS)
    assert [f.rule_id for f in permitted.findings if f.rule_id == "RESULT001"] == []


# -- configuration ----------------------------------------------------------------------


def contracts_config(root: Path, body: str) -> EffectiveConfig:
    (root / ".shockharness.toml").write_text(
        "[tool.shockharness.rules.property_contracts]\n" + body, encoding="utf-8"
    )
    return load_config(root, None)


def config_error(root: Path, body: str) -> str:
    with pytest.raises(ConfigError) as caught:
        contracts_config(root, body)
    return str(caught.value)


PROPERTY = (
    "[[tool.shockharness.rules.property_contracts.properties]]\n"
    'name = "{name}"\ndescription = "d"\nproducers = []\nruntime = "static"\n'
)


def test_catalog_shape_errors_are_configuration_errors(empty_root: Path) -> None:
    assert "lower_snake_case" in config_error(empty_root, "\n" + PROPERTY.format(name="Bad-Name"))
    twice = PROPERTY.format(name="p") + PROPERTY.format(name="p")
    assert "listed twice" in config_error(empty_root, "\n" + twice)
    sink = (
        '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "python"\n'
        'callee = "{callee}"\nrequires = ["{required}"]\nreason = "r"\n'
    )
    malformed = sink.format(callee="app.cloud.send", required="p")
    assert "callee:N" in config_error(empty_root, "\n" + PROPERTY.format(name="p") + malformed)
    unknown = sink.format(callee="app.cloud.send:0", required="q")
    assert "not a catalog property" in config_error(
        empty_root, "\n" + PROPERTY.format(name="p") + unknown
    )
    assert "names no runtime module" in config_error(empty_root, "enabled = true\n")
    runtime = PROPERTY.format(name="p").replace('"static"', '"sometimes"')
    assert "runtime" in config_error(empty_root, "\n" + runtime)


def test_unresolved_references_are_errors_before_an_analysis(empty_root: Path) -> None:
    write_project(empty_root, {"app/__init__.py": "", "app/text.py": TEXT})
    body = (
        'enabled = true\nruntime_module = ["app/contracts.py"]\n\n'
        '[[tool.shockharness.rules.property_contracts.properties]]\nname = "p"\n'
        'description = "d"\nproducers = ["app.text.missing", "json.dumps", "app.text.redact"]\n'
        'runtime = "static"\n\n'
        '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "python"\n'
        'callee = "app.text.Nothing.method:0"\nrequires = ["p"]\nreason = "r"\n'
    )
    config = contracts_config(empty_root, body)  # loading does not resolve references
    with pytest.raises(ConfigError) as caught:
        analyze_paths([empty_root], empty_root, config, OPTIONS)
    message = str(caught.value)
    assert "producers[0]" in message and "app.text.missing" in message
    assert "producers[1]" in message and "not a function of this project" in message
    assert "producers[2]" not in message
    assert "sinks[0].callee" in message


# -- VERIFY003 ----------------------------------------------------------------------------

ENABLED = (
    'enabled = true\nfail_on_unknown = true\nruntime_module = ["app/contracts.py"]\n\n'
    '[tool.shockharness.rules.property_contracts.severities]\nPROP001 = "error"\n\n'
    '[[tool.shockharness.rules.property_contracts.properties]]\nname = "p"\ndescription = "d"\n'
    'producers = ["app.text.redact"]\nruntime = "check"\n\n'
    '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "python"\n'
    'callee = "json.dumps:0"\nrequires = ["p"]\nreason = "r"\n'
)


def changed(root: Path, old: str, new: str) -> list[str]:
    before = contracts_config(root, ENABLED)
    assert old in ENABLED
    after = contracts_config(root, ENABLED.replace(old, new))
    found = loosenings(before.values, before.deviations, after.values, after.deviations)
    return [item.message for item in found]


@pytest.mark.parametrize(
    ("old", "new", "needle"),
    [
        ("enabled = true", "enabled = false", "the property-contracts family is off"),
        ("fail_on_unknown = true", "fail_on_unknown = false", "no longer gate"),
        ("enabled = true\n", "enabled = true\nallow_undeclared = true\n", "no longer an error"),
        (
            'callee = "json.dumps:0"',
            'callee = "json.loads:0"',
            "no longer lists the sink python json.dumps:0",
        ),
        ('runtime = "check"', 'runtime = "static"', "runtime lowered from 'check' to 'static'"),
        ('producers = ["app.text.redact"]', "producers = []", "producers dropped"),
        (
            'producers = ["app.text.redact"]',
            'producers = ["app.text.redact", "app.x.y"]',
            "widened with app.x.y",
        ),
        (
            'PROP001 = "error"',
            'PROP001 = "review"',
            "severities.PROP001 changed from 'error' to 'review'",
        ),
        (
            "enabled = true\n",
            'enabled = true\nroles = ["test"]\n',
            "roles no longer lists 'production'",
        ),
        (
            'runtime_module = ["app/contracts.py"]',
            'runtime_module = ["app/c2.py"]',
            "runtime_module no longer lists",
        ),
    ],
)
def test_each_loosening_of_the_section_is_reported(
    empty_root: Path, old: str, new: str, needle: str
) -> None:
    messages = changed(empty_root, old, new)
    assert any(needle in m for m in messages), messages


def test_a_sink_requiring_less_is_reported_and_tightenings_are_not(empty_root: Path) -> None:
    extra = PROPERTY.format(name="q")
    wider = ENABLED.replace('requires = ["p"]', 'requires = ["p", "q"]') + extra
    before = contracts_config(empty_root, wider)
    after = contracts_config(empty_root, ENABLED + extra)
    narrowed = loosenings(before.values, before.deviations, after.values, after.deviations)
    assert [i.message for i in narrowed] == [
        "rules.property_contracts.sinks: the sink python json.dumps:0 no longer requires q"
    ]
    tightened = loosenings(after.values, after.deviations, before.values, before.deviations)
    assert tightened == []


def test_prop005_compares_a_test_bootstrap_enable_with_the_catalog(empty_root: Path) -> None:
    bootstrap = (
        "from app.contracts import enable\n\n"
        'enable("check", ["redacted"])\n'
        'enable("check", ["redacted", "other"])\n'
        'enable("check", [])\n'
        'enable("check", STATIC)\n'
        'enable("check")\n'
    )
    production = 'from app.contracts import enable\n\nenable("check", [])\n'
    files = {
        "app/__init__.py": "",
        "app/text.py": TEXT,
        "app/start.py": production,
        "tests/conftest.py": bootstrap,
        "tests/test_boot.py": bootstrap,
    }
    rows = [(r["path"], r["line"], r["rule"]) for r in prop_rows(run(empty_root, files, ""))]
    expected = [(4, "PROP005"), (5, "PROP005"), (6, "PROP006"), (7, "PROP006")]
    assert rows == [("tests/conftest.py", *e) for e in expected] + [
        ("tests/test_boot.py", *e) for e in expected
    ]
    messages = [r["message"] for r in prop_rows(run(empty_root, files, "")) if r["line"] == 4]
    assert "lists 'other', which the catalog does not mark static" in messages[0]
    assert "contracts static-properties" in messages[0]


def test_javascript_references_resolve_or_are_errors(empty_root: Path) -> None:
    write_project(
        empty_root,
        {"static/js/html.js": "export function escapeHtml(t) { return t; }\n"},
    )
    body = (
        'enabled = true\nruntime_module = ["static/js/vendor/c.js"]\n\n'
        '[[tool.shockharness.rules.property_contracts.properties]]\nname = "p"\n'
        'description = "d"\nproducers = ["static/js/html.js:escapeHtml", '
        '"static/js/html.js:missing", "dompurify:sanitize", "static/js/gone.js:f"]\n'
        'runtime = "static"\n\n'
        '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "javascript"\n'
        'callee = "static/js/html.js:nothing:0"\nrequires = ["p"]\nreason = "r"\n\n'
        '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "javascript"\n'
        'callee = "fetch:1"\nrequires = ["p"]\nreason = "r"\n'
    )
    config = contracts_config(empty_root, body)
    with pytest.raises(ConfigError) as caught:
        analyze_paths([empty_root], empty_root, config, OPTIONS)
    message = str(caught.value)
    assert "producers[0]" not in message
    assert "producers[1]" in message and "exports no missing" in message
    assert "producers[2]" in message and "not a function of this project" in message
    assert "producers[3]" in message and "cannot be read" in message
    assert "sinks[0].callee" in message and "sinks[1]" not in message


def test_sink_forms_and_compositions_are_checked_at_load(empty_root: Path) -> None:
    both = (
        '[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "javascript"\n'
        'callee = "fetch:0"\ntarget = "innerHTML"\nrequires = ["p"]\nreason = "r"\n'
    )
    assert "exactly one of callee" in config_error(
        empty_root, "\n" + PROPERTY.format(name="p") + both
    )
    target = both.replace('callee = "fetch:0"\n', "").replace("innerHTML", "inner HTML")
    assert "not an attribute" in config_error(empty_root, "\n" + PROPERTY.format(name="p") + target)
    rule = (
        '[[tool.shockharness.rules.property_contracts.compositions]]\nlanguage = "javascript"\n'
        'operation = "fstring"\ninputs_require = ["q"]\nproduces = "p"\nreason = "r"\n'
    )
    message = config_error(empty_root, "\n" + PROPERTY.format(name="p") + rule)
    assert "javascript has template_literal, concat, not 'fstring'" in message
    assert "'q' is not a catalog property" in message


COMPOSED = (
    ENABLED
    + PROPERTY.format(name="q")
    + '\n[[tool.shockharness.rules.property_contracts.compositions]]\nlanguage = "python"\n'
    'operation = "fstring"\ninputs_require = ["q", "p"]\nproduces = "p"\nreason = "r"\n'
    '\n[[tool.shockharness.rules.property_contracts.sinks]]\nlanguage = "python"\n'
    'target = "body"\nrequires = ["p"]\nreason = "r"\n'
)


@pytest.mark.parametrize(
    ("old", "new", "needle"),
    [
        ('inputs_require = ["q", "p"]', 'inputs_require = ["p"]', "now accepts parts that carry p"),
        ('produces = "p"', 'produces = "q"', "python fstring -> q now accepts"),
        ('target = "body"', 'target = "html"', "no longer lists the sink python target body"),
        (
            'runtime = "check"\n',
            'runtime = "check"\nliteral_satisfies = true\n',
            "literal_satisfies set",
        ),
    ],
)
def test_each_loosening_of_the_p1b_keys_is_reported(
    empty_root: Path, old: str, new: str, needle: str
) -> None:
    before = contracts_config(empty_root, COMPOSED)
    assert old in COMPOSED
    after = contracts_config(empty_root, COMPOSED.replace(old, new, 1))
    found = loosenings(before.values, before.deviations, after.values, after.deviations)
    assert any(needle in item.message for item in found), [i.message for i in found]


@pytest.mark.parametrize(
    ("old", "new", "needle"),
    [
        ("enabled = true\n", "enabled = true\nmax_depth = 5\n", "max_depth raised from 3 to 5"),
        (
            "enabled = true\n",
            'enabled = true\nruntime_mode_required = "off"\n',
            "runtime_mode_required changed from 'check' to 'off'",
        ),
    ],
)
def test_p2_keys_loosen(empty_root: Path, old: str, new: str, needle: str) -> None:
    before = contracts_config(empty_root, ENABLED)
    after = contracts_config(empty_root, ENABLED.replace(old, new, 1))
    found = loosenings(before.values, before.deviations, after.values, after.deviations)
    assert any(needle in item.message for item in found), [i.message for i in found]


def test_prop005_reports_properties_verify_mode_has_no_predicate_for(empty_root: Path) -> None:
    registrations = (
        "from app.contracts import register\n\n"
        'register("redacted", lambda text: "@" not in text, "no addresses")\n'
    )
    files = {"app/__init__.py": "", "app/text.py": TEXT, "app/predicates.py": registrations}
    extra = (
        'runtime_mode_required = "verify"\nregistration_module = "app.predicates"\n'
        + "\n"
        + PROPERTY.format(name="other").replace('"static"', '"check"')
        + PROPERTY.format(name="third").replace('"static"', '"verify"')
        + '\n[tool.shockharness.rules.property_contracts.severities]\nPROP005 = "review"\n'
    )
    report = run(empty_root, files, extra)
    found = [f for f in report.findings if f.rule_id == "PROP005"]
    assert [f.path for f in found] == [".shockharness.toml", ".shockharness.toml"]
    assert ["'other'" in found[0].message, "'third'" in found[1].message] == [True, True]
    assert found[0].span.line == 8  # the registration_module line
    with pytest.raises(ConfigError, match="needs the module that registers"):
        contracts_config(empty_root, 'runtime_mode_required = "verify"\n')
