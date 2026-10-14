import pytest

from shockharness.ir.javascript import extract_javascript_facts, parse_js_number
from shockharness.source import SourceText


def facts(text: str):
    return extract_javascript_facts(SourceText.from_text(text), "<t>")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("1", 1),
        ("42", 42),
        ("1_000_000", 1000000),
        ("0x1F", 31),
        ("0X1f", 31),
        ("0o17", 15),
        ("0b101", 5),
        ("017", 15),
        ("019", 19),
        ("09", 9),
        ("10n", 10),
        ("0x10n", 16),
        ("1.5", 1.5),
        (".5", 0.5),
        ("1.", 1.0),
        ("1e3", 1000.0),
        ("1E-3", 0.001),
        ("1_0.5_0", 10.5),
        ("0.0", 0.0),
        ("1e0", 1.0),
    ],
)
def test_parse_js_number(raw: str, expected: object) -> None:
    value = parse_js_number(raw)
    assert value == expected
    assert type(value) is type(expected)


def test_number_kinds_and_values() -> None:
    collected = facts("const a = 7, b = 2.5, c = 0x10, d = 1_000, e = 10n;")
    assert collected.parse_failure is None
    assert [(lit.raw, lit.value) for lit in collected.numeric_literals] == [
        ("7", 7),
        ("2.5", 2.5),
        ("0x10", 16),
        ("1_000", 1000),
        ("10n", 10),
    ]


def test_unary_sign_chain_is_folded() -> None:
    collected = facts("const a = -1, b = - -1, c = -+2, d = +3, e = -0, f = -1n;")
    assert [(lit.raw, lit.value, lit.negated) for lit in collected.numeric_literals] == [
        ("-1", -1, True),
        ("- -1", 1, False),
        ("-+2", -2, True),
        ("+3", 3, False),
        ("-0", 0, True),
        ("-1n", -1, True),
    ]


def test_strings_regex_and_identifiers_are_not_numbers() -> None:
    collected = facts('const s = "30", r = /\\d{3}/g, t = `x7`, n = NaN, i = Infinity;')
    assert collected.numeric_literals == ()


def test_template_substitution_is_executable() -> None:
    collected = facts("const t = `${5}`;")
    assert [lit.raw for lit in collected.numeric_literals] == ["5"]


def test_jsx_attribute_expressions_are_scanned() -> None:
    collected = facts('const el = <A count={2} label="3" />;')
    assert [lit.raw for lit in collected.numeric_literals] == ["2"]


def test_scopes() -> None:
    text = (
        "const top = 2;\n"
        "function named() { return 3; }\n"
        "const arrow = () => 4;\n"
        "class Widget {\n  static SIDES = 5;\n  area() { return 6; }\n}\n"
        "const obj = { method: function () { return 7; }, key: () => 8 };\n"
        "async function* gen() { yield 9; }\n"
        "x = () => 10;\n"
        "[].map(() => 11);\n"
    )
    scopes = {lit.raw: lit.scope for lit in facts(text).numeric_literals}
    assert scopes == {
        "2": "<module>",
        "3": "named",
        "4": "arrow",
        "5": "Widget",
        "6": "Widget.area",
        "7": "method",
        "8": "key",
        "9": "gen",
        "10": "x",
        "11": "<anonymous>",
    }


def test_comments_line_and_block() -> None:
    collected = facts("const a = 1; // one\n/* two\n   lines */\nconst b = '// not';\n")
    assert [(c.text.split("\n")[0], c.span.line, c.span.column) for c in collected.comments] == [
        ("// one", 1, 14),
        ("/* two", 2, 1),
    ]


def test_syntax_error_is_a_parse_failure() -> None:
    collected = facts("function broken( {\n  return 1;\n}\n")
    assert collected.parse_failure is not None
    assert collected.parse_failure.span is not None
    assert "syntax error" in collected.parse_failure.message
    assert collected.numeric_literals == ()


def test_missing_token_is_a_parse_failure() -> None:
    collected = facts("const x = (1 + 2;\n")
    assert collected.parse_failure is not None
    assert collected.numeric_literals == ()


def test_parse_failure_message_is_bounded() -> None:
    collected = facts("function broken( {\n" + "x".ljust(500, "x") + "\n")
    assert collected.parse_failure is not None
    assert len(collected.parse_failure.message) < 200


def test_unicode_columns() -> None:
    collected = facts('const name = "héllo"; const width = 30;\n')
    (lit,) = collected.numeric_literals
    assert (lit.span.column, lit.span.end_column) == (37, 39)


def test_crlf_sources_keep_line_numbers() -> None:
    collected = facts("const a = 1;\r\nconst b = 2;\r\nconst c = 3;\r\n")
    assert [(lit.raw, lit.span.line) for lit in collected.numeric_literals] == [
        ("1", 1),
        ("2", 2),
        ("3", 3),
    ]


def test_deep_nesting_does_not_recurse() -> None:
    depth = 300
    text = "const x = " + "[" * depth + "7" + "]" * depth + ";\n"
    collected = facts(text)
    assert collected.parse_failure is None
    assert [lit.raw for lit in collected.numeric_literals] == ["7"]


# --- catch facts -----------------------------------------------------------------------------


def js_catches(text: str):
    collected = extract_javascript_facts(SourceText.from_text(text), "t.js")
    assert collected.parse_failure is None
    return collected.catches


def test_catch_clause_without_guard_is_bare() -> None:
    (fact,) = js_catches("try { f(); } catch (err) { log.warn(err); }\n")
    assert (fact.kind, fact.bare, fact.identities, fact.bound_name) == ("catch", True, (), "err")
    assert fact.body.classification == "logging_only"
    (no_binding,) = js_catches("try { f(); } catch { }\n")
    assert no_binding.bound_name is None
    assert no_binding.body.classification == "empty"


@pytest.mark.parametrize(
    "guard",
    [
        "if (!(err instanceof TimeoutError)) throw err;",
        "if (!(err instanceof TimeoutError)) { throw err; }",
        "if (!(err instanceof errors.TimeoutError)) throw err;",
    ],
)
def test_negated_instanceof_guard_names_the_identity(guard: str) -> None:
    (fact,) = js_catches(f"try {{ f(); }} catch (err) {{ {guard} return null; }}\n")
    assert fact.bare is False
    (identity,) = fact.identities
    assert identity.qualified in ("TimeoutError", "errors.TimeoutError")
    assert identity.confidence == "approximate"
    assert fact.body.classification == "return_fallback"


def test_positive_guard_with_else_throw_classifies_consequence() -> None:
    text = (
        "try { f(); } catch (err) { if (err instanceof TimeoutError) { console.log(err); } "
        "else { throw err; } }\n"
    )
    (fact,) = js_catches(text)
    assert fact.identities[0].qualified == "TimeoutError"
    assert fact.body.classification == "logging_only"


@pytest.mark.parametrize(
    "guard",
    [
        "if (err.name !== 'TimeoutError') throw err;",
        "if (!(err instanceof TimeoutError || err instanceof AbortError)) throw err;",
        "if (!(err instanceof TimeoutError)) throw other;",
        "if (!(other instanceof TimeoutError)) throw err;",
        "if (!(err instanceof TimeoutError)) throw err; else { x(); }",
        "if (err instanceof TimeoutError) { x(); }",
    ],
)
def test_unrecognized_guards_leave_the_catch_bare(guard: str) -> None:
    (fact,) = js_catches(f"try {{ f(); }} catch (err) {{ {guard} }}\n")
    assert fact.bare is True
    assert fact.identities == ()


def test_throw_classification() -> None:
    cases = {
        "throw err;": "reraise",
        "throw new E('x', { cause: err });": "raise_chained",
        "throw new E('x', { cause });": "raise_other",
        "throw new E('x', { cause: other });": "raise_other",
        "throw new E('x');": "raise_other",
        "throw other;": "raise_other",
        "console.log(err); throw err;": "reraise",
    }
    for body, expected in cases.items():
        (fact,) = js_catches(f"try {{ f(); }} catch (err) {{ {body} }}\n")
        assert fact.body.classification == expected, body
    (shorthand,) = js_catches("try { f(); } catch (cause) { throw new E('x', { cause }); }\n")
    assert shorthand.body.classification == "raise_chained"


def test_return_fallback_classification() -> None:
    literal = [
        "return;",
        "return null;",
        "return undefined;",
        "return false;",
        "return 0;",
        "return -1;",
        "return 'x';",
        "return `x`;",
        "return [1, 'a'];",
        "return { a: 1, b: [null] };",
    ]
    for body in literal:
        (fact,) = js_catches(f"try {{ f(); }} catch (err) {{ {body} }}\n")
        assert fact.body.classification == "return_fallback", body
    for body in (
        "return fallback;",
        "return `${err}`;",
        "return { a };",
        "return [f()];",
        "return { ...x };",
    ):
        (fact,) = js_catches(f"try {{ f(); }} catch (err) {{ {body} }}\n")
        assert fact.body.classification == "other", body


def test_promise_rejection_handlers() -> None:
    text = (
        "fetch(u).catch((e) => null);\n"
        "fetch(u).then(ok, function (e) { throw e; });\n"
        "fetch(u).catch(handle);\n"
        "fetch(u).then(ok);\n"
        "fetch(u).finally(done);\n"
        "fetch(u).then((r) => r.json()).catch((e) => { throw e; });\n"
    )
    facts = js_catches(text)
    assert [(f.kind, f.span.line, f.body.classification) for f in facts] == [
        ("promise.catch", 1, "return_fallback"),
        ("promise.then", 2, "reraise"),
        ("promise.catch", 3, "opaque"),
        ("promise.catch", 6, "reraise"),
    ]
    assert facts[0].try_statements[0].operation == "fetch"
    assert facts[3].try_statements[0].operation is None
    assert "promise chain performs 4 operations" in str(facts[3].try_statements[0].reason)


def test_try_statement_attribution_in_javascript() -> None:
    text = (
        "async function g(u) {\n"
        "  try { await fetch(u); } catch (e) { throw e; }\n"
        "  try { const r = await api.get(u); } catch (e) { throw e; }\n"
        "  try { x = new Client(u); } catch (e) { throw e; }\n"
        "  try { return parse(fetch(u)); } catch (e) { throw e; }\n"
        "  try { if (u) f(u); } catch (e) { throw e; }\n"
        "  try { items.map((i) => f(i)); } catch (e) { throw e; }\n"
        "}\n"
    )
    rows = [(f.try_statements[0].operation, f.try_statements[0].reason) for f in js_catches(text)]
    assert rows[0] == ("fetch", None)
    assert rows[1] == ("api.get", None)
    assert rows[2] == ("new Client", None)
    assert rows[3][0] is None and "2 operations" in str(rows[3][1])
    assert rows[4][0] is None and "compound statement (if_statement)" in str(rows[4][1])
    assert rows[5][0] is None and "3 operations" in str(rows[5][1])


def test_catch_scope_names() -> None:
    text = (
        "class K { m() { try { f(); } catch (e) { throw e; } } }\n"
        "const h = () => { try { f(); } catch (e) { throw e; } };\n"
    )
    assert [f.scope for f in js_catches(text)] == ["K.m", "h"]
