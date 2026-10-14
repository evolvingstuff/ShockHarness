from shockharness.ir.python import extract_python_facts
from shockharness.source import SourceText


def facts(text: str):
    return extract_python_facts(SourceText.from_text(text), "<t>")


def literal_table(text: str) -> list[tuple[str, object, bool, str]]:
    collected = facts(text)
    assert collected.parse_failure is None
    return sorted(
        ((lit.raw, lit.value, lit.negated, lit.scope) for lit in collected.numeric_literals),
        key=lambda row: row[0],
    )


def test_booleans_and_none_are_not_numeric() -> None:
    assert facts("a = True\nb = False\nc = None\n").numeric_literals == ()


def test_all_numeric_kinds_are_collected() -> None:
    rows = literal_table("a = 7\nb = 2.5\nc = 3j\nd = 0x10\ne = 1_000\n")
    assert [(r[0], r[1]) for r in rows] == [
        ("0x10", 16),
        ("1_000", 1000),
        ("2.5", 2.5),
        ("3j", 3j),
        ("7", 7),
    ]


def test_unary_sign_chain_is_folded() -> None:
    rows = literal_table("a = -1\nb = --1\nc = -+2\nd = +3\ne = -0\n")
    by_raw = {r[0]: (r[1], r[2]) for r in rows}
    assert by_raw["-1"] == (-1, True)
    assert by_raw["--1"] == (1, False)
    assert by_raw["-+2"] == (-2, True)
    assert by_raw["+3"] == (3, False)
    assert by_raw["-0"] == (0, True)


def test_unary_minus_over_non_literal_descends_normally() -> None:
    rows = literal_table("x = 5\ny = -x\nz = -(x + 2)\n")
    assert [r[0] for r in rows] == ["2", "5"]


def test_scopes_are_qualified() -> None:
    text = (
        "top = 2\n"
        "def outer():\n"
        "    a = 3\n"
        "    def inner():\n"
        "        return 4\n"
        "class K:\n"
        "    S = 5\n"
        "    def m(self):\n"
        "        return 6\n"
        "    async def a(self):\n"
        "        return 7\n"
        "f = lambda: 8\n"
    )
    scopes = {lit.raw: lit.scope for lit in facts(text).numeric_literals}
    assert scopes == {
        "2": "<module>",
        "3": "outer",
        "4": "outer.inner",
        "5": "K",
        "6": "K.m",
        "7": "K.a",
        "8": "<lambda>",
    }


def test_annotation_literals_are_marked() -> None:
    text = "def f(x: L[2]) -> L[3]:\n    return 4\ny: L[5] = 6\n"
    flags = {lit.raw: lit.in_annotation for lit in facts(text).numeric_literals}
    assert flags == {"2": True, "3": True, "4": False, "5": True, "6": False}


def test_spans_are_one_based_character_columns() -> None:
    collected = facts('s = "é"; n = 42\n')
    (lit,) = collected.numeric_literals
    assert (lit.span.line, lit.span.column, lit.span.end_line, lit.span.end_column) == (
        1,
        14,
        1,
        16,
    )


def test_multiline_unary_span_covers_operator() -> None:
    collected = facts("x = -(\n    1\n)\n")
    (lit,) = collected.numeric_literals  # parentheses vanish in the AST; the chain still folds
    assert (lit.value, lit.negated, lit.span.line, lit.span.end_line) == (-1, True, 1, 3)
    collected = facts("x = -\\\n1\n")
    (lit,) = collected.numeric_literals
    assert lit.raw == "-\\\n1"
    assert (lit.span.line, lit.span.end_line) == (1, 2)


def test_comments_are_extracted_with_spans() -> None:
    collected = facts("a = 1  # first\n# second\nb = '# not a comment'\n")
    assert [(c.text, c.span.line, c.span.column) for c in collected.comments] == [
        ("# first", 1, 8),
        ("# second", 2, 1),
    ]


def test_syntax_error_is_a_parse_failure_with_position() -> None:
    collected = facts("def broken(:\n    pass\n")
    assert collected.parse_failure is not None
    assert collected.parse_failure.span is not None
    assert collected.parse_failure.span.line == 1
    assert collected.parse_failure.message.startswith("SyntaxError")
    assert collected.numeric_literals == ()


def test_null_byte_is_a_parse_failure_not_a_crash() -> None:
    collected = facts("x = 1\0\n")
    assert collected.parse_failure is not None
    assert collected.numeric_literals == ()


def test_crlf_sources_keep_line_numbers() -> None:
    collected = facts("a = 1\r\nb = 2\r\nc = 3\r\n")
    assert [(lit.raw, lit.span.line) for lit in collected.numeric_literals] == [
        ("1", 1),
        ("2", 2),
        ("3", 3),
    ]


def test_deeply_nested_expression_does_not_recurse() -> None:
    depth = 150
    text = "x = " + "[" * depth + "7" + "]" * depth + "\n"
    collected = facts(text)
    assert collected.parse_failure is None
    assert [lit.raw for lit in collected.numeric_literals] == ["7"]


def test_match_statement_patterns_are_covered() -> None:
    text = (
        "match v:\n    case 9:\n        pass\n"
        "    case -10:\n        pass\n    case 1 | 2:\n        pass\n"
    )
    assert sorted(lit.raw for lit in facts(text).numeric_literals) == ["-10", "1", "2", "9"]
