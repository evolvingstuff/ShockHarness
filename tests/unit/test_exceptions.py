"""EXC001-EXC003 rule semantics: boundaries, identities, handler bodies, try scope."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from shockharness.rules import registry
from tests.conftest import finding_tuples

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)

TIMEOUT_BOUNDARY = (
    "[[tool.shockharness.rules.exceptions.boundaries]]\n"
    'path = "src/net/**"\nlanguage = "python"\n'
    'exception = "requests.exceptions.Timeout"\nreason = "external HTTP call"\n'
)
JS_BOUNDARY = (
    "[[tool.shockharness.rules.exceptions.boundaries]]\n"
    'path = "web/**"\nlanguage = "javascript"\n'
    'exception = "TimeoutError"\nreason = "external HTTP call"\n'
)

NARROW_PY = (
    "from requests.exceptions import Timeout\n"
    "def fetch(session, url):\n"
    "    try:\n"
    "        response = session.get(url)\n"
    "    except Timeout as exc:\n"
    "        raise Upstream(url) from exc\n"
    "    return response\n"
)


def _run(config: EffectiveConfig, path: str, language: str, text: str) -> FileResult:
    """Analyze and keep the exception family plus DEF005, which co-owns return_fallback."""
    result = analyze_text(path, language, text, config, OPTIONS)
    kept = tuple(f for f in result.findings if f.rule_id.startswith("EXC") or f.rule_id == "DEF005")
    return replace(result, findings=kept)


def _messages(result: FileResult, rule_id: str) -> list[str]:
    return [f.message for f in result.findings if f.rule_id == rule_id]


# --- EXC001: approval requires file, language, and identity to match ------------------


def test_narrow_catch_passes_only_inside_its_boundary(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    inside = _run(config, "src/net/client.py", "python", NARROW_PY)
    assert inside.findings == ()
    outside = _run(config, "src/core/client.py", "python", NARROW_PY)
    assert finding_tuples(outside) == [("EXC001", 5, 5)]
    assert "'requests.exceptions.Timeout' is not approved" in outside.findings[0].message
    assert outside.findings[0].confidence == "exact"


def test_boundary_language_must_match(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(TIMEOUT_BOUNDARY.replace('language = "python"', 'language = "javascript"'))
    result = _run(config, "src/net/client.py", "python", NARROW_PY)
    assert [f.rule_id for f in result.findings] == ["EXC001"]


def test_bare_except_can_never_be_approved(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "**"\nlanguage = "python"\nexception = "BaseException"\nreason = "everything"\n'
    )
    result = _run(config, "a.py", "python", "try:\n    f()\nexcept:\n    raise\n")
    (finding,) = result.findings
    assert finding.rule_id == "EXC001"
    assert "bare except" in finding.message
    assert finding.confidence == "unresolved"


def test_broad_catch_fails_without_boundary_and_passes_with_exact_one(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = "def main():\n    try:\n        run()\n    except Exception as exc:\n        raise\n"
    result = _run(strict_config, "cli.py", "python", text)
    assert _messages(result, "EXC001") == [
        "except handler of 'Exception' is forbidden: broad catch of 'Exception' is not "
        "approved by any boundary for this file"
    ]
    config = make_config(
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "cli.py"\nlanguage = "python"\nexception = "Exception"\n'
        'reason = "process boundary"\n'
    )
    assert _run(config, "cli.py", "python", text).findings == ()


def test_unresolved_identity_is_an_explicit_diagnostic(strict_config: EffectiveConfig) -> None:
    text = "try:\n    f()\nexcept Mystery as exc:\n    raise Other() from exc\n"
    (finding,) = _run(strict_config, "a.py", "python", text).findings
    assert finding.rule_id == "EXC001"
    assert finding.confidence == "unresolved"
    assert "'Mystery' could not be resolved" in finding.message
    assert "strict mode fails closed" in finding.message


def test_unresolved_identity_fails_even_inside_a_boundary_naming_it(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "**"\nlanguage = "python"\nexception = "Mystery"\nreason = "typo-proof"\n'
    )
    text = "try:\n    f()\nexcept Mystery as exc:\n    raise Other() from exc\n"
    assert [f.rule_id for f in _run(config, "a.py", "python", text).findings] == ["EXC001"]


def test_tuple_handler_needs_every_member_approved(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "from requests.exceptions import Timeout, ConnectionError\n"
        "try:\n    f()\nexcept (Timeout, ConnectionError) as exc:\n    raise Up() from exc\n"
    )
    (finding,) = _run(config, "src/net/a.py", "python", text).findings
    assert "'requests.exceptions.ConnectionError' is not approved" in finding.message
    assert "Timeout" not in finding.message.split("forbidden:")[1]
    both = make_config(
        TIMEOUT_BOUNDARY
        + TIMEOUT_BOUNDARY.replace("Timeout", "ConnectionError").replace("HTTP call", "refused")
    )
    assert _run(both, "src/net/a.py", "python", text).findings == ()


def test_approximate_identities_match_by_dotted_suffix(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/**"\nlanguage = "python"\nexception = "pkg.errors.Upstream"\n'
        'reason = "typed error from our client"\n'
    )
    relative = "from .errors import Upstream\ntry:\n    f()\nexcept Upstream:\n    raise\n"
    assert _run(config, "src/pkg/a.py", "python", relative).findings == ()
    local = "class Upstream(Exception):\n    pass\ntry:\n    f()\nexcept Upstream:\n    raise\n"
    assert _run(config, "src/pkg/errors.py", "python", local).findings == ()
    exact_mismatch = (
        "from other.errors import Upstream\ntry:\n    f()\nexcept Upstream:\n    raise\n"
    )
    assert [f.rule_id for f in _run(config, "src/pkg/a.py", "python", exact_mismatch).findings] == [
        "EXC001"
    ]


def test_transparent_rethrow_policy(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config("[tool.shockharness.rules.exceptions]\ntransparent_rethrow = true\n")
    assert "transparent_rethrow is enabled" in "\n".join(config.deviations)
    passes = "try:\n    f()\nexcept ValueError:\n    raise\n"
    assert _run(config, "a.py", "python", passes).findings == ()
    bound = "try:\n    f()\nexcept ValueError as exc:\n    raise exc\n"
    assert _run(config, "a.py", "python", bound).findings == ()
    chained = "try:\n    f()\nexcept ValueError as exc:\n    raise Other() from exc\n"
    assert [f.rule_id for f in _run(config, "a.py", "python", chained).findings] == ["EXC001"]
    js = "try { f(); } catch (e) { throw e; }\n"
    assert _run(config, "a.js", "javascript", js).findings == ()
    js_other = "try { f(); } catch (e) { throw other; }\n"
    assert [f.rule_id for f in _run(config, "a.js", "javascript", js_other).findings] == [
        "EXC001",
        "EXC002",
    ]


# --- JavaScript convention: boundary + instanceof guard ----------------------------------


def test_javascript_catch_needs_boundary_and_guard(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    guarded = (
        "async function f(u) {\n  try {\n    return await fetch(u);\n  } catch (err) {\n"
        "    if (!(err instanceof TimeoutError)) throw err;\n"
        "    throw new Upstream(u, { cause: err });\n  }\n}\n"
    )
    unguarded = guarded.replace("    if (!(err instanceof TimeoutError)) throw err;\n", "")
    config = make_config(JS_BOUNDARY)
    assert _run(config, "web/client.js", "javascript", guarded).findings == ()
    (no_boundary,) = _run(strict_config, "web/client.js", "javascript", guarded).findings
    assert "catch clause of 'TimeoutError' is forbidden" in no_boundary.message
    assert no_boundary.confidence == "approximate"
    (no_guard,) = _run(config, "web/client.js", "javascript", unguarded).findings
    assert "untyped catch" in no_guard.message
    assert "instanceof" in no_guard.message
    assert no_guard.confidence == "unresolved"


def test_javascript_wildcard_boundary_is_rejected(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    with pytest.raises(ConfigError) as info:
        make_config(JS_BOUNDARY.replace('exception = "TimeoutError"', 'exception = "*"'))
    assert "boundaries[0].exception" in str(info.value)
    assert "wildcards" in str(info.value)


def test_javascript_opaque_rejection_handler_fails_closed(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(JS_BOUNDARY)
    (finding,) = _run(config, "web/a.js", "javascript", "fetch(u).catch(onError);\n").findings
    assert finding.rule_id == "EXC001"
    assert "'onError' is not an inline function" in finding.message
    assert finding.confidence == "unresolved"


# --- EXC002: handler behaviour, even inside a boundary --------------------------------------


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("pass", "swallows the exception"),
        ("...", "swallows the exception"),
        ("logging.error('x')", "only logs the exception"),
        ("print(exc)\n        pass", "only logs the exception"),
        ("return None", "converts the exception into a fallback value: return None"),
        ("return", "converts the exception into a fallback value: return"),
        ("return False", "fallback value: return False"),
        ("return 0", "fallback value: return 0"),
        ("return []", "fallback value: return []"),
        ("return {'a': (1, 'b')}", "fallback value"),
        ("raise Other('x')", "replaces the exception without preserving its cause"),
        ("raise Other('x') from None", "'from None' discards the cause"),
        ("raise Other('x') from unrelated", "cause is not the caught exception"),
    ],
)
def test_exc002_flags_suppression_shapes_inside_boundary(
    make_config: Callable[[str], EffectiveConfig], body: str, fragment: str
) -> None:
    """return_fallback is reported once, as DEF005, while DEF005 is active (Milestone D)."""
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "import logging\nfrom requests.exceptions import Timeout\n"
        "def f(session, url):\n    try:\n        return session.get(url)\n"
        f"    except Timeout as exc:\n        {body}\n"
    )
    result = _run(config, "src/net/a.py", "python", text)
    expected = "DEF005" if body.startswith("return") else "EXC002"
    assert [f.rule_id for f in result.findings] == [expected], result.findings
    assert fragment in result.findings[0].message
    assert result.findings[0].confidence == "exact"
    if expected == "DEF005":
        assert "EXC002 classification return_fallback" in result.findings[0].message
        without_def005 = make_config(
            TIMEOUT_BOUNDARY
            + '[[tool.shockharness.overrides]]\npaths = ["src/**"]\ndisable = ["DEF005"]\n'
            'reason = "exercise the EXC002 fallback path"\n'
        )
        again = _run(without_def005, "src/net/a.py", "python", text)
        assert [f.rule_id for f in again.findings] == ["EXC002"], again.findings
        assert fragment in again.findings[0].message


@pytest.mark.parametrize(
    "body",
    [
        "raise",
        "raise exc",
        "raise Other('x') from exc",
        "logging.error('x')\n        raise",
        "return compute_default()",
        "return (None, status)",
        "retry()\n        return None",
    ],
)
def test_exc002_does_not_flag_transparent_or_unclassified_handlers(
    make_config: Callable[[str], EffectiveConfig], body: str
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "import logging\nfrom requests.exceptions import Timeout\n"
        "def f(session, url):\n    try:\n        return session.get(url)\n"
        f"    except Timeout as exc:\n        {body}\n"
    )
    assert _run(config, "src/net/a.py", "python", text).findings == ()


def test_exc002_javascript_shapes(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(JS_BOUNDARY)
    guard = "if (!(e instanceof TimeoutError)) throw e;"
    cases = {
        "": ("EXC002", "swallows"),
        "console.error(e);": ("EXC002", "only logs"),
        "return null;": ("DEF005", "fallback value: return null"),
        "return undefined;": ("DEF005", "fallback value"),
        "return { items: [], n: 0 };": ("DEF005", "fallback value"),
        "throw new Error('x');": ("EXC002", "without preserving its cause"),
    }
    for body, (rule_id, fragment) in cases.items():
        text = f"try {{ f(); }} catch (e) {{ {guard} {body} }}\n"
        result = _run(config, "web/a.js", "javascript", text)
        assert [f.rule_id for f in result.findings] == [rule_id], (body, result.findings)
        assert fragment in result.findings[0].message, body
    for body in ("throw e;", "throw new Error('x', { cause: e });", "retry(); return null;"):
        text = f"try {{ f(); }} catch (e) {{ {guard} {body} }}\n"
        assert _run(config, "web/a.js", "javascript", text).findings == (), body


# --- EXC003: approved catch wraps only the sanctioned operation ------------------------------


def test_exc003_only_runs_on_approved_catches(strict_config: EffectiveConfig) -> None:
    text = "try:\n    a()\n    b()\nexcept ValueError:\n    raise\n"
    assert [f.rule_id for f in _run(strict_config, "a.py", "python", text).findings] == ["EXC001"]


@pytest.mark.parametrize(
    ("body", "fragment", "line"),
    [
        ("a = session.get(url)\n        b = parse(a)", "protects 2 statements", 5),
        ("with lock:\n            session.get(url)", "compound statement (with)", 4),
        ("value = table[key]", "statement value is not a call (subscript)", 4),
        ("data = parse(session.get(url))", "performs 2 operations", 4),
        ("rows = [session.get(u) for u in urls]", "not a call (listcomp)", 4),
        ("assert session.get(url)", "statement (assert) does not perform a call", 4),
    ],
)
def test_exc003_broad_or_unattributable_try_bodies(
    make_config: Callable[[str], EffectiveConfig], body: str, fragment: str, line: int
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "from requests.exceptions import Timeout\n"
        "def f(session, url):\n    try:\n"
        f"        {body}\n"
        "    except Timeout as exc:\n        raise Upstream(url) from exc\n"
    )
    result = _run(config, "src/net/a.py", "python", text)
    assert [(f.rule_id, f.span.line) for f in result.findings] == [("EXC003", line)]
    assert fragment in result.findings[0].message
    assert "approved by boundaries[0] (requests.exceptions.Timeout: external HTTP call)" in (
        result.findings[0].message
    )


def test_exc003_unattributable_statement_has_approximate_confidence(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "from requests.exceptions import Timeout\n"
        "try:\n    data = parse(session.get(url))\nexcept Timeout as exc:\n    raise\n"
    )
    (finding,) = _run(config, "src/net/a.py", "python", text).findings
    assert finding.confidence == "approximate"
    assert "static analysis cannot tell which part may raise" in finding.message
    broad = text.replace("    data = parse(session.get(url))\n", "    a = f()\n    b = g()\n")
    (finding,) = _run(config, "src/net/a.py", "python", broad).findings
    assert finding.confidence == "exact"


@pytest.mark.parametrize(
    "body",
    [
        "session.get(url)",
        "response = session.get(url)",
        "response: Response = session.get(url)",
        "total += session.get(url)",
        "return session.get(url)",
        "response = await session.get(url)",
        "import optional_dependency",
        "from optional import thing",
    ],
)
def test_exc003_accepts_single_call_shapes(
    make_config: Callable[[str], EffectiveConfig], body: str
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    text = (
        "from requests.exceptions import Timeout\n"
        "async def f(session, url, total):\n    try:\n"
        f"        {body}\n"
        "    except Timeout as exc:\n        raise Upstream(url) from exc\n"
    )
    assert _run(config, "src/net/a.py", "python", text).findings == ()


def test_exc003_javascript_shapes(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(JS_BOUNDARY)
    handler = (
        "catch (e) { if (!(e instanceof TimeoutError)) throw e; throw new U(u, { cause: e }); }"
    )
    for body in ("f(u);", "const r = f(u);", "return await f(u);", "x = new Client(u);"):
        text = f"async function g(u) {{ try {{ {body} }} {handler} }}\n"
        assert _run(config, "web/a.js", "javascript", text).findings == (), body
    for body, fragment in (
        ("f(u); g(u);", "protects 2 statements"),
        ("", "protects 0 statements"),
        ("const r = parse(f(u));", "performs 2 operations"),
        ("const r = f(u), s = g(u);", "binds more than one variable"),
        ("for (const x of y) f(x);", "compound statement (for_in_statement)"),
        ("const r = u.value;", "not a call (member_expression)"),
    ):
        text = f"async function g(u) {{ try {{ {body} }} {handler} }}\n"
        result = _run(config, "web/a.js", "javascript", text)
        assert [f.rule_id for f in result.findings] == ["EXC003"], body
        assert fragment in result.findings[0].message, body
    rejection = (
        "(e) => { if (!(e instanceof TimeoutError)) throw e; throw new U(u, { cause: e }); }"
    )
    assert _run(config, "web/a.js", "javascript", f"fetch(u).catch({rejection});\n").findings == ()
    chained = _run(config, "web/a.js", "javascript", f"fetch(u).then(p).catch({rejection});\n")
    assert "promise chain performs 2 operations" in chained.findings[0].message
    variable = _run(config, "web/a.js", "javascript", f"pending.catch({rejection});\n")
    assert "rejection source (identifier) is not a call" in variable.findings[0].message


# --- configuration surface ------------------------------------------------------------------


def test_exception_rules_share_one_enabled_switch(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config("[tool.shockharness.rules.exceptions]\nenabled = false\n")
    result = _run(config, "a.py", "python", "try:\n    f()\nexcept:\n    pass\n")
    assert result.findings == ()
    assert [d.rule_id for d in result.rules_disabled] == [
        "EXC001",
        "EXC002",
        "EXC003",
        "EXC004",
        "EXC005",
    ]
    assert "rules.exceptions is disabled" in config.deviations


# The rules expected, as one constant (the list grows with every rule).
OVERRIDE_APPLIED = (
    "ASSERT001",
    "ASSERT002",
    "ASYNC001",
    "ASYNC002",
    "ASYNC003",
    "BATCH001",
    "BOOL001",
    "CPLX001",
    "CPLX002",
    "CPLX003",
    "CPLX004",
    "CPLX005",
    "CPLX006",
    "DEF001",
    "DEF002",
    "DEF003",
    "DEF004",
    "DEF005",
    "DEF006",
    "EXC001",
    "EXC003",
    "EXC004",
    "GUARD001",
    "IMPORT001",
    "INPUT001",
    "INPUT002",
    "MAGIC001",
    "MAGIC002",
    "MAGIC003",
    "MAGIC004",
    "PROCESS001",
    "PROV001",
    "RESULT001",
    "RETRY001",
    "ROLE001",
    "SLEEP001",
    "STATE001",
    "STATE002",
    "STUB001",
    "STUB002",
    "STUB003",
    "SUPP001",
    "SUPP002",
    "TYPE001",
)


def test_single_exception_rule_can_be_disabled_by_override(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        '[[tool.shockharness.overrides]]\npaths = ["legacy/**"]\ndisable = ["EXC002"]\n'
        'reason = "legacy swallowing is tracked separately"\n'
    )
    result = _run(config, "legacy/a.py", "python", "try:\n    f()\nexcept:\n    pass\n")
    assert [f.rule_id for f in result.findings] == ["EXC001"]
    assert result.rules_applied == OVERRIDE_APPLIED


def test_boundaries_are_reported_as_deviations(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(TIMEOUT_BOUNDARY)
    assert config.deviations == (
        "rules.exceptions.boundaries[0] approves catching requests.exceptions.Timeout in "
        "src/net/** (python): external HTTP call",
    )


def test_registry_metadata_for_exception_rules() -> None:
    for rule in (registry.EXC001, registry.EXC002, registry.EXC003):
        assert rule.implemented
        assert rule.version == "1"
        assert rule.config_section == "rules.exceptions"
        assert rule.languages == ("python", "javascript", "typescript")


# --- 0.2.0 feedback round, item 3: transparent guards and multi-type boundaries ------------

GUARD_CONFIG = (
    '[tool.shockharness.rules.exceptions]\ntransparent_guards = ["rethrowUnexpectedError"]\n'
)
JS_GUARDED = (
    "async function load(url) {\n"
    "  try {\n    await fetch(url);\n  } catch (error) {\n"
    "    rethrowUnexpectedError(error);\n    showBanner(error.message);\n  }\n}\n"
)
JS_GUARD_ONLY = (
    "async function load(url) {\n"
    "  try {\n    await fetch(url);\n  } catch (error) {\n"
    "    rethrowUnexpectedError(error);\n  }\n}\n"
)
JS_GUARD_THEN_FALLBACK = (
    "async function load(url) {\n"
    "  try {\n    return await fetch(url);\n  } catch (error) {\n"
    "    rethrowUnexpectedError(error);\n    return null;\n  }\n}\n"
)


def test_transparent_guard_call_narrows_javascript_catch(
    strict_config: EffectiveConfig,
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    guarded = make_config(GUARD_CONFIG)
    assert _run(guarded, "web/a.js", "javascript", JS_GUARDED).findings == ()
    # the same handler without the guard configured is still a forbidden untyped catch
    without = _run(strict_config, "web/a.js", "javascript", JS_GUARDED)
    assert [f.rule_id for f in without.findings] == ["EXC001"]
    # a guard call with a different argument, or extra arguments, is not the guard
    other = JS_GUARDED.replace("rethrowUnexpectedError(error)", "rethrowUnexpectedError(error, 1)")
    assert [f.rule_id for f in _run(guarded, "web/a.js", "javascript", other).findings] == [
        "EXC001"
    ]
    # the guard is recognized when it is the first statement only
    later = JS_GUARDED.replace(
        "    rethrowUnexpectedError(error);\n    showBanner(error.message);\n",
        "    showBanner(error.message);\n    rethrowUnexpectedError(error);\n",
    )
    assert [f.rule_id for f in _run(guarded, "web/a.js", "javascript", later).findings] == [
        "EXC001"
    ]
    assert guarded.deviations == (
        "rules.exceptions.transparent_guards[0] treats a handler whose first statement is "
        "rethrowUnexpectedError(<caught exception>) as narrowed by that guard; EXC001 does "
        "not report the catch and EXC002 classifies the statements after the guard",
    )


def test_exc002_classifies_the_statements_after_a_transparent_guard(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    guarded = make_config(GUARD_CONFIG)
    swallow = _run(guarded, "web/a.js", "javascript", JS_GUARD_ONLY)
    assert [f.rule_id for f in swallow.findings] == ["EXC002"]
    # 0.3.0, item 5: a guard followed by nothing names the three remedies
    assert swallow.findings[0].message == (
        "catch clause after the transparent guard rethrowUnexpectedError(...) swallows the "
        "exception: handler body is empty; the failure vanishes; after the guard, handle the "
        "expected error, or log it and continue with a stated reason, or suppress this "
        "finding with a reason"
    )
    # a fallback returned after the guard is EXC002's (DEF005 reads the whole body), and a
    # handler with statements after the guard keeps the message without the remedies
    fallback = _run(guarded, "web/a.js", "javascript", JS_GUARD_THEN_FALLBACK)
    assert [(f.rule_id, f.message) for f in fallback.findings] == [
        (
            "EXC002",
            "catch clause after the transparent guard rethrowUnexpectedError(...) converts the "
            "exception into a fallback value: return null;",
        )
    ]
    logging_after = JS_GUARD_ONLY.replace(
        "rethrowUnexpectedError(error);", "rethrowUnexpectedError(error); console.log(error);"
    )
    logged = _run(guarded, "web/a.js", "javascript", logging_after)
    assert [f.rule_id for f in logged.findings] == ["EXC002"]
    assert "only logs the exception" in logged.findings[0].message
    assert "after the guard, handle" not in logged.findings[0].message
    # a plain swallow without a guard keeps its message too
    plain = _run(guarded, "web/a.js", "javascript", "try { go(); } catch (error) {}\n")
    assert all("after the guard, handle" not in f.message for f in plain.findings)


def test_python_isinstance_guard_narrows_the_catch_for_exc001(
    make_config: Callable[[str], EffectiveConfig], strict_config: EffectiveConfig
) -> None:
    os_boundary = (
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/io/**"\nlanguage = "python"\nexception = "OSError"\nreason = "disk"\n'
    )
    config = make_config(os_boundary)
    narrowed = (
        "def read(path):\n"
        "    try:\n        return open(path)\n"
        "    except Exception as exc:\n"
        "        if not isinstance(exc, OSError):\n            raise\n"
        "        raise Unreadable(path) from exc\n"
    )
    assert _run(config, "src/io/reader.py", "python", narrowed).findings == ()
    outside = _run(config, "src/core/reader.py", "python", narrowed)
    assert finding_tuples(outside) == [("EXC001", 4, 5)]
    assert outside.findings[0].message == (
        "except handler of 'OSError' (narrowed from 'Exception' by its isinstance guard) is "
        "forbidden: catch of 'OSError' is not approved by any boundary for this file"
    )
    # a tuple guard needs every member approved
    pair = narrowed.replace("isinstance(exc, OSError)", "isinstance(exc, (OSError, ValueError))")
    pair_result = _run(config, "src/io/reader.py", "python", pair)
    assert [f.rule_id for f in pair_result.findings] == ["EXC001"]
    assert "'ValueError' is not approved" in pair_result.findings[0].message
    # EXC002 judges what follows the guard: pass after the guard swallows OSError
    swallow = narrowed.replace("        raise Unreadable(path) from exc\n", "        pass\n")
    swallow_result = _run(config, "src/io/reader.py", "python", swallow)
    assert [f.rule_id for f in swallow_result.findings] == ["EXC002"]
    assert "swallows the exception" in swallow_result.findings[0].message
    # shapes that are not the guard leave the broad catch as written
    for variant in (
        "        if isinstance(exc, OSError):\n            raise\n",  # inverted
        "        if not isinstance(exc, OSError):\n            return None\n",  # not a re-raise
        "        if not isinstance(exc, OSError):\n            raise\n"
        "        else:\n            pass\n",
        "        if not isinstance(other, OSError):\n            raise\n",  # other subject
    ):
        text = narrowed.replace(
            "        if not isinstance(exc, OSError):\n            raise\n", variant
        )
        result = _run(strict_config, "src/io/reader.py", "python", text)
        assert any(
            f.rule_id == "EXC001" and "broad catch of 'Exception'" in f.message
            for f in result.findings
        ), variant


def test_python_transparent_guard_call(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        '[tool.shockharness.rules.exceptions]\ntransparent_guards = ["errors.rethrow_unexpected"]\n'
    )
    text = (
        "from app import errors\n\n"
        "def load(path):\n"
        "    try:\n        return read(path)\n"
        "    except Exception as exc:\n"
        "        errors.rethrow_unexpected(exc)\n"
        "        return recover(path)\n"
    )
    assert _run(config, "src/a.py", "python", text).findings == ()
    only = text.replace("        return recover(path)\n", "")
    result = _run(config, "src/a.py", "python", only)
    assert [f.rule_id for f in result.findings] == ["EXC002"]
    assert result.findings[0].message == (
        "except handler after the transparent guard errors.rethrow_unexpected(...) swallows "
        "the exception: handler body is pass/...; the failure vanishes; after the guard, "
        "handle the expected error, or log it and continue with a stated reason, or suppress "
        "this finding with a reason"
    )


def test_multi_type_boundary_approves_each_listed_type_once(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/proc/**"\nlanguage = "python"\n'
        'exceptions = ["OSError", "ProcessLookupError"]\nreason = "the child may be gone"\n'
    )
    assert config.deviations == (
        "rules.exceptions.boundaries[0] approves catching OSError, ProcessLookupError in "
        "src/proc/** (python): the child may be gone",
    )
    text = (
        "def stop(process):\n"
        "    try:\n        process.kill()\n"
        "    except (OSError, ProcessLookupError) as exc:\n"
        "        raise Gone(process) from exc\n"
        "    try:\n        process.wait()\n"
        "    except ProcessLookupError as exc:\n"
        "        raise Gone(process) from exc\n"
        "    try:\n        process.poll()\n"
        "    except ValueError as exc:\n"
        "        raise Gone(process) from exc\n"
    )
    result = _run(config, "src/proc/stop.py", "python", text)
    assert finding_tuples(result) == [("EXC001", 12, 5)]
    assert "'ValueError' is not approved" in result.findings[0].message
    # EXC003 is unchanged: an approved multi-type catch still protects one operation only
    wide = text.replace(
        "    try:\n        process.kill()\n",
        "    try:\n        prepare()\n        process.kill()\n",
    )
    wide_result = _run(config, "src/proc/stop.py", "python", wide)
    assert [(f.rule_id, f.span.line) for f in wide_result.findings] == [
        ("EXC003", 4),
        ("EXC001", 13),
    ]
    assert "(approved by boundaries[0] (OSError, ProcessLookupError: the child may be gone))" in (
        wide_result.findings[0].message
    )


def test_boundary_needs_exactly_one_of_exception_and_exceptions(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    head = (
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/**"\nlanguage = "python"\nreason = "r"\n'
    )
    with pytest.raises(ConfigError, match=r"boundaries\[0\]: needs exactly one of"):
        make_config(head)
    with pytest.raises(ConfigError, match=r"boundaries\[0\]: needs exactly one of"):
        make_config(head + 'exception = "OSError"\nexceptions = ["ValueError"]\n')
    with pytest.raises(ConfigError, match=r"boundaries\[0\]\.exceptions: must list at least one"):
        make_config(head + "exceptions = []\n")
    with pytest.raises(ConfigError, match=r"boundaries\[0\]\.exceptions\[1\]: must be a dotted"):
        make_config(head + 'exceptions = ["OSError", "*"]\n')
    with pytest.raises(ConfigError, match=r"transparent_guards\[0\]: must be the guard"):
        make_config('[tool.shockharness.rules.exceptions]\ntransparent_guards = ["not a name"]\n')


# --- 0.2.0 second brief, item 1: context managers as catches -------------------------------

SUPPRESS_PY = (
    "from contextlib import suppress\n"
    "def remove(path):\n"
    "    with suppress(FileNotFoundError):\n"
    "        path.unlink()\n"
)
FNF_BOUNDARY = (
    "[[tool.shockharness.rules.exceptions.boundaries]]\n"
    'path = "src/io/**"\nlanguage = "python"\nexception = "FileNotFoundError"\nreason = "race"\n'
)
MANAGER_CONFIG = (
    "[tool.shockharness.rules.exceptions]\n"
    'capture_managers = ["app.errors.CapturedExceptionContext"]\n'
)


def test_contextlib_suppress_is_a_swallowing_catch(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    result = _run(strict_config, "src/io/fs.py", "python", SUPPRESS_PY)
    assert finding_tuples(result) == [("EXC001", 3, 5), ("EXC002", 3, 5)]
    assert result.findings[0].message == (
        "context manager of 'FileNotFoundError' is forbidden: catch of 'FileNotFoundError' is "
        "not approved by any boundary for this file"
    )
    assert result.findings[0].confidence == "exact"
    assert result.findings[1].message.startswith(
        "context manager swallows the exception: suppress(...) discards the exception"
    )
    assert result.findings[0].scope == "remove"
    # approved by a boundary for that path: nothing; EXC003 still watches the body
    approved = make_config(FNF_BOUNDARY)
    assert _run(approved, "src/io/fs.py", "python", SUPPRESS_PY).findings == ()
    wide = SUPPRESS_PY.replace(
        "        path.unlink()\n", "        prepare(path)\n        path.unlink()\n"
    )
    wide_result = _run(approved, "src/io/fs.py", "python", wide)
    assert [f.rule_id for f in wide_result.findings] == ["EXC003"]
    assert "approved context manager protects 2 statements" in wide_result.findings[0].message
    # the module-import spelling and a tuple of types
    qualified = (
        "import contextlib\n"
        "with contextlib.suppress(FileNotFoundError, PermissionError):\n    cleanup()\n"
    )
    result = _run(approved, "src/io/fs.py", "python", qualified)
    assert [f.rule_id for f in result.findings] == ["EXC001", "EXC002"]  # not approved: both
    assert "'PermissionError' is not approved" in result.findings[0].message
    # broad
    broad = _run(
        strict_config,
        "src/a.py",
        "python",
        "from contextlib import suppress\nwith suppress(Exception):\n    go()\n",
    )
    assert "broad catch of 'Exception'" in broad.findings[0].message
    # no readable type: untyped, like a bare except
    untyped = _run(
        strict_config,
        "src/a.py",
        "python",
        "from contextlib import suppress\nwith suppress(*kinds):\n    go()\n",
    )
    assert untyped.findings[0].rule_id == "EXC001"
    assert "no positional argument names an exception type" in untyped.findings[0].message
    assert untyped.findings[0].confidence == "unresolved"
    # an ordinary context manager is not a catch
    assert (
        _run(strict_config, "src/a.py", "python", "with open(p) as f:\n    f.read()\n").findings
        == ()
    )


def test_capture_managers_are_catches_when_configured(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(MANAGER_CONFIG)
    assert config.deviations == (
        "rules.exceptions.capture_managers[0] treats `with "
        "app.errors.CapturedExceptionContext(T, ...):` as a catch of the exception types T "
        "passed to it; it is approved by boundaries like an except handler and reported by "
        "EXC001 otherwise",
    )
    resolved = (
        "from app.errors import CapturedExceptionContext\n"
        "def alive(pid):\n"
        "    capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n"
        "    with CapturedExceptionContext(ProcessLookupError, boundary='x') as capture:\n"
        "        os.kill(pid, 0)\n"
        "    return capture.captured_exception is None\n"
    )
    result = _run(config, "src/proc.py", "python", resolved)
    assert finding_tuples(result) == [("EXC001", 4, 5)]
    assert result.findings[0].message == (
        "context manager of 'ProcessLookupError' is forbidden: catch of 'ProcessLookupError' "
        "is not approved by any boundary for this file"
    )
    assert result.findings[0].confidence == "exact"
    # the same manager is not a swallow for EXC002: the exception is kept for inspection
    assert not any(f.rule_id == "EXC002" for f in result.findings)
    # approved like an except handler
    approved = make_config(
        MANAGER_CONFIG + "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/proc.py"\nlanguage = "python"\nexception = "ProcessLookupError"\n'
        'reason = "the process may be gone"\n'
    )
    assert _run(approved, "src/proc.py", "python", resolved).findings == ()
    # an unresolved import matches by bare name with approximate confidence
    unresolved = resolved.replace("from app.errors import CapturedExceptionContext\n", "")
    result = _run(config, "src/proc.py", "python", unresolved)
    assert [(f.rule_id, f.confidence) for f in result.findings] == [("EXC001", "approximate")]
    # an unlisted manager is an ordinary with
    assert _run(strict_config, "src/proc.py", "python", resolved).findings == ()
    # a listed manager without a readable type is an untyped catch
    untyped = resolved.replace(
        "CapturedExceptionContext(ProcessLookupError, boundary='x') as",
        "CapturedExceptionContext(boundary='x') as",
    )
    result = _run(config, "src/proc.py", "python", untyped)
    assert result.findings[0].confidence == "unresolved"
    assert "an untyped catch can never be approved" in result.findings[0].message
    with pytest.raises(ConfigError, match=r"capture_managers\[0\]: must be the manager"):
        make_config('[tool.shockharness.rules.exceptions]\ncapture_managers = ["not a name"]\n')


def test_manager_catch_fingerprints_survive_unrelated_edits(
    strict_config: EffectiveConfig,
) -> None:
    before = _run(strict_config, "src/io/fs.py", "python", SUPPRESS_PY)
    after = _run(strict_config, "src/io/fs.py", "python", "import os\n\n\n" + SUPPRESS_PY)
    assert [f.fingerprint for f in before.findings] == [f.fingerprint for f in after.findings]
    assert [f.span.line for f in after.findings] == [6, 6]


# --- 0.3.0 brief, item 1: capture managers bound to a name ---------------------------------

BOUND_PY = (
    "from app.errors import CapturedExceptionContext\n"
    "import os\n"
    "def alive(pid):\n"
    "    capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n"
    "    with capture:\n"
    "        os.kill(pid, 0)\n"
    "    return capture.captured_exception is None\n"
)
PROC_BOUNDARY = (
    "[[tool.shockharness.rules.exceptions.boundaries]]\n"
    'path = "src/proc.py"\nlanguage = "python"\nexception = "ProcessLookupError"\n'
    'reason = "the process may be gone"\n'
)


def test_bound_capture_manager_is_the_catch_with_exact_confidence(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(MANAGER_CONFIG)
    result = _run(config, "src/proc.py", "python", BOUND_PY)
    assert finding_tuples(result) == [("EXC001", 5, 5)]
    assert result.findings[0].confidence == "exact"
    assert result.findings[0].message == (
        "context manager of 'ProcessLookupError' is forbidden: catch of 'ProcessLookupError' "
        "is not approved by any boundary for this file"
    )
    assert result.findings[0].scope == "alive"
    # a boundary approving the type approves the bound form exactly like the inline one
    approved = make_config(MANAGER_CONFIG + PROC_BOUNDARY)
    assert _run(approved, "src/proc.py", "python", BOUND_PY).findings == ()
    # the same binding at module level, with the ``with`` at module level
    module_level = (
        "from app.errors import CapturedExceptionContext as M\n"
        "capture = M(ProcessLookupError)\n"
        "with capture:\n"
        "    go()\n"
    )
    result = _run(config, "src/proc.py", "python", module_level)
    assert [(f.rule_id, f.span.line, f.confidence) for f in result.findings] == [
        ("EXC001", 3, "exact")
    ]
    # bound in the same branch as the with: still exact
    same_block = BOUND_PY.replace(
        "    capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n"
        "    with capture:\n        os.kill(pid, 0)\n",
        "    if pid:\n        capture = CapturedExceptionContext(ProcessLookupError)\n"
        "        with capture:\n            os.kill(pid, 0)\n",
    )
    result = _run(config, "src/proc.py", "python", same_block)
    assert [(f.span.line, f.confidence) for f in result.findings] == [(6, "exact")]


def test_bound_capture_manager_in_a_branch_is_approximate(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(MANAGER_CONFIG)
    branched = BOUND_PY.replace(
        "    capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n",
        "    if pid > 0:\n"
        "        capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n",
    )
    result = _run(config, "src/proc.py", "python", branched)
    assert [(f.rule_id, f.span.line, f.confidence) for f in result.findings] == [
        ("EXC001", 6, "approximate")
    ]
    assert "catch of 'ProcessLookupError'" in result.findings[0].message
    # the exact identity is downgraded with the binding: it still matches a boundary
    approved = make_config(MANAGER_CONFIG + PROC_BOUNDARY)
    assert _run(approved, "src/proc.py", "python", branched).findings == ()
    # bound inside a loop body, used after the loop
    looped = BOUND_PY.replace(
        "    capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n",
        "    for _ in attempts:\n"
        "        capture = CapturedExceptionContext(ProcessLookupError, boundary='x')\n",
    )
    assert [f.confidence for f in _run(config, "src/proc.py", "python", looped).findings] == [
        "approximate"
    ]
    # the name is also a parameter or a comprehension target of the scope
    parameter = BOUND_PY.replace("def alive(pid):", "def alive(pid, capture):")
    assert [f.confidence for f in _run(config, "src/proc.py", "python", parameter).findings] == [
        "approximate"
    ]
    comprehension = BOUND_PY.replace(
        "    return capture.captured_exception is None\n",
        "    return [capture for capture in captures]\n",
    )
    result = _run(config, "src/proc.py", "python", comprehension)
    assert [f.confidence for f in result.findings] == ["approximate"]


def test_rebound_or_unassigned_capture_name_is_an_untyped_catch(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(MANAGER_CONFIG + PROC_BOUNDARY)
    rebound = BOUND_PY.replace("    with capture:\n", "    capture = other()\n    with capture:\n")
    result = _run(config, "src/proc.py", "python", rebound)
    assert [(f.rule_id, f.span.line, f.confidence) for f in result.findings] == [
        ("EXC001", 6, "unresolved")
    ]
    assert result.findings[0].message == (
        "context manager is forbidden: 'capture' was bound to CapturedExceptionContext(...) on "
        "line 4 and rebound on line 5 (other()) before this with; the manager this with enters "
        "cannot be established, so it is an untyped catch that no boundary can approve"
    )
    # never the older binding: the boundary for ProcessLookupError does not approve it,
    # and it is not an EXC002 swallow either (nothing is known about the handler)
    assert [f.rule_id for f in result.findings] == ["EXC001"]
    # bound by ``with ... as``: out of scope, unresolved
    with_as = (
        "from app.errors import CapturedExceptionContext as M\n"
        "def f():\n"
        "    with M(ProcessLookupError) as capture:\n"
        "        go()\n"
        "    with capture:\n"
        "        go()\n"
    )
    result = _run(config, "src/proc.py", "python", with_as)
    assert [(f.span.line, f.confidence) for f in result.findings] == [(5, "unresolved")]
    assert "binds what the manager's __enter__ returns" in result.findings[0].message
    # bound in another scope (module level, used in a function): unresolved
    other_scope = (
        "from app.errors import CapturedExceptionContext as M\n"
        "capture = M(ProcessLookupError)\n"
        "def f():\n"
        "    with capture:\n"
        "        go()\n"
    )
    result = _run(config, "src/proc.py", "python", other_scope)
    assert [(f.span.line, f.confidence) for f in result.findings] == [(4, "unresolved")]
    assert "is not assigned in this scope before the with" in result.findings[0].message
    # an imported name later rebound to a manager elsewhere: unresolved at the with
    imported = (
        "from app.errors import CapturedExceptionContext as M\n"
        "def f():\n"
        "    from app.captures import capture\n"
        "    with capture:\n"
        "        go()\n"
        "def g():\n"
        "    capture = M(ValueError)\n"
        "    return capture\n"
    )
    result = _run(config, "src/proc.py", "python", imported)
    assert [(f.span.line, f.confidence) for f in result.findings] == [(4, "unresolved")]
    assert "is last bound on line 3 (from app.captures import capture)" in (
        result.findings[0].message
    )
    # a name never bound to a listed manager anywhere is an ordinary with
    lock = "import threading\nlock = threading.Lock()\ndef f():\n    with lock:\n        go()\n"
    assert _run(config, "src/proc.py", "python", lock).findings == ()
    # an unlisted manager bound to a name is an ordinary with too
    assert _run(make_config(PROC_BOUNDARY), "src/proc.py", "python", BOUND_PY).findings == ()


def test_bound_suppress_behaves_like_the_inline_form(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    bound = (
        "from contextlib import suppress\n"
        "def remove(path):\n"
        "    s = suppress(FileNotFoundError)\n"
        "    with s:\n"
        "        path.unlink()\n"
    )
    result = _run(strict_config, "src/io/fs.py", "python", bound)
    assert finding_tuples(result) == [("EXC001", 4, 5), ("EXC002", 4, 5)]
    assert result.findings[0].confidence == "exact"
    assert result.findings[1].message.startswith(
        "context manager swallows the exception: suppress(...) discards the exception"
    )
    assert _run(make_config(FNF_BOUNDARY), "src/io/fs.py", "python", bound).findings == ()
    # the whole-module spelling
    qualified = bound.replace("from contextlib import suppress", "import contextlib").replace(
        "suppress(FileNotFoundError)", "contextlib.suppress(FileNotFoundError)"
    )
    assert [
        f.rule_id for f in _run(strict_config, "src/io/fs.py", "python", qualified).findings
    ] == [
        "EXC001",
        "EXC002",
    ]


def test_bound_manager_fingerprints_survive_unrelated_edits(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(MANAGER_CONFIG)
    before = _run(config, "src/proc.py", "python", BOUND_PY)
    after = _run(config, "src/proc.py", "python", "import sys\n\n\n" + BOUND_PY)
    assert [f.fingerprint for f in before.findings] == [f.fingerprint for f in after.findings]
    assert [f.span.line for f in after.findings] == [8]
    # ``with open(p) as fh:`` is still an ordinary with, and so is ``with fh:``
    ordinary = "def f(p):\n    with open(p) as fh:\n        fh.read()\n    with fh:\n        pass\n"
    assert _run(config, "src/proc.py", "python", ordinary).findings == ()


# --- 0.2.0 second brief, item 3: promise rejection handlers ---------------------------------


def _js(config: EffectiveConfig, text: str) -> list[tuple[str, int, str]]:
    result = _run(config, "web/a.js", "javascript", text)
    return [(f.rule_id, f.span.line, f.message) for f in result.findings]


def test_promise_rejection_handlers_acceptance(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    swallow = _js(strict_config, "fetchData().catch(() => {});\n")
    assert [(r[0], r[1]) for r in swallow] == [("EXC001", 1), ("EXC002", 1)]
    assert "promise .catch handler swallows the exception" in swallow[1][2]
    rethrow = "fetchData().catch((error) => { throw error; });\n"
    assert [(r[0], r[1]) for r in _js(strict_config, rethrow)] == [("EXC001", 1)]
    transparent = make_config("[tool.shockharness.rules.exceptions]\ntransparent_rethrow = true\n")
    assert _js(transparent, rethrow) == []
    logged = _js(strict_config, "fetchData().then(render, (error) => log(error));\n")
    assert [(r[0], r[1]) for r in logged] == [("EXC001", 1), ("EXC002", 1)]
    assert "promise .then rejection handler only logs the exception" in logged[1][2]
    assert _js(strict_config, "fetchData().finally(cleanup);\n") == []
    assert _js(strict_config, "fetchData().then(render);\n") == []
    # an async function's try/catch is a catch clause, unchanged
    clause = _js(
        strict_config,
        "async function load() {\n  try {\n    await fetchData();\n  } catch (error) {\n"
        "    return null;\n  }\n}\n",
    )
    assert [(r[0], r[1]) for r in clause] == [("DEF005", 4), ("EXC001", 4)]


def test_promise_handler_references_resolve_to_module_functions(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "function swallow(error) {}\n"
        "const rethrow = (error) => { throw error; };\n"
        "export function logOnly(error) { console.error(error); }\n"
        "fetchData().catch(swallow);\n"
        "fetchData().catch(rethrow);\n"
        "fetchData().then(ok, logOnly);\n"
        "fetchData().catch(imported);\n"
        "fetchData().catch(obj.method);\n"
    )
    result = _run(strict_config, "web/a.js", "javascript", text)
    rows = [(f.rule_id, f.span.line, f.confidence) for f in result.findings]
    assert rows == [
        ("EXC001", 4, "unresolved"),
        ("EXC002", 4, "exact"),
        ("EXC001", 5, "unresolved"),
        ("EXC001", 6, "unresolved"),
        ("EXC002", 6, "exact"),
        ("EXC001", 7, "unresolved"),
        ("EXC001", 8, "unresolved"),
    ]
    messages = {f.span.line: f.message for f in result.findings if f.rule_id == "EXC001"}
    assert "swallows" in [f.message for f in result.findings if f.span.line == 4][1]
    assert "only logs" in [f.message for f in result.findings if f.span.line == 6][1]
    assert "'imported' is not an inline function or a function defined" in messages[7]
    assert "'obj.method' is not an inline function" in messages[8]
