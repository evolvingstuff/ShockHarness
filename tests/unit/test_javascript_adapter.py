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
