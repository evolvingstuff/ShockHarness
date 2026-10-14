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


# --- catch facts and exception identity resolution ---------------------------------------


def catches(text: str, path: str = "src/pkg/mod.py"):
    collected = extract_python_facts(SourceText.from_text(text), path)
    assert collected.parse_failure is None
    return collected.catches


def identity_rows(text: str) -> list[tuple[str, str | None, str, bool]]:
    rows = []
    for catch in catches(text):
        for identity in catch.identities:
            rows.append((identity.source, identity.qualified, identity.confidence, identity.broad))
    return rows


def test_builtin_identity_is_exact_unless_shadowed() -> None:
    assert identity_rows("try:\n    f()\nexcept OSError:\n    raise\n") == [
        ("OSError", "OSError", "exact", False)
    ]
    shadowed = "from compat import OSError\ntry:\n    f()\nexcept OSError:\n    raise\n"
    assert identity_rows(shadowed) == [("OSError", "compat.OSError", "exact", False)]
    rebound = "OSError = MyError\ntry:\n    f()\nexcept OSError:\n    raise\n"
    assert identity_rows(rebound) == [("OSError", None, "unresolved", False)]


def test_broad_identities_are_marked() -> None:
    text = (
        "import builtins\ntry:\n    f()\nexcept Exception:\n    raise\n"
        "except BaseException:\n    raise\nexcept builtins.Exception:\n    raise\n"
    )
    assert [(r[1], r[3]) for r in identity_rows(text)] == [
        ("Exception", True),
        ("BaseException", True),
        ("Exception", True),
    ]


def test_import_forms_resolve_exactly() -> None:
    text = (
        "import tomllib\n"
        "import requests.exceptions\n"
        "import pkg.errors as perr\n"
        "from requests.exceptions import Timeout\n"
        "from requests.exceptions import Timeout as T\n"
        "try:\n    f()\n"
        "except tomllib.TOMLDecodeError:\n    raise\n"
        "except requests.exceptions.Timeout:\n    raise\n"
        "except perr.Third:\n    raise\n"
        "except (Timeout, T):\n    raise\n"
    )
    assert identity_rows(text) == [
        ("tomllib.TOMLDecodeError", "tomllib.TOMLDecodeError", "exact", False),
        ("requests.exceptions.Timeout", "requests.exceptions.Timeout", "exact", False),
        ("perr.Third", "pkg.errors.Third", "exact", False),
        ("Timeout", "requests.exceptions.Timeout", "exact", False),
        ("T", "requests.exceptions.Timeout", "exact", False),
    ]


def test_relative_local_and_nested_bindings_are_approximate() -> None:
    text = (
        "from .errors import RelErr\n"
        "from .. import errors\n"
        "class LocalErr(Exception):\n    pass\n"
        "def f():\n"
        "    from pkg.nested import NestedErr\n"
        "    try:\n        g()\n"
        "    except RelErr:\n        raise\n"
        "    except errors.Other:\n        raise\n"
        "    except LocalErr:\n        raise\n"
        "    except NestedErr:\n        raise\n"
    )
    assert identity_rows(text) == [
        ("RelErr", ".errors.RelErr", "approximate", False),
        ("errors.Other", "..errors.Other", "approximate", False),
        ("LocalErr", "src.pkg.mod.LocalErr", "approximate", False),
        ("NestedErr", "pkg.nested.NestedErr", "approximate", False),
    ]


def test_module_level_guarded_imports_are_approximate() -> None:
    text = (
        "try:\n    from fast import Err\nexcept ImportError:\n    from slow import Err\n"
        "try:\n    f()\nexcept Err:\n    raise\n"
    )
    rows = identity_rows(text)
    assert rows[0] == ("ImportError", "ImportError", "exact", False)
    assert rows[1] == ("Err", "slow.Err", "approximate", False)


def test_dynamic_handler_types_are_unresolved() -> None:
    text = (
        "def f(kinds):\n    try:\n        g()\n"
        "    except kinds[0]:\n        raise\n"
        "    except make():\n        raise\n"
        "    except (OSError, *kinds):\n        raise\n"
    )
    rows = identity_rows(text)
    assert rows[0] == ("kinds[0]", None, "unresolved", False)
    assert rows[1] == ("make()", None, "unresolved", False)
    assert rows[2] == ("OSError", "OSError", "exact", False)
    assert rows[3] == ("*kinds", None, "unresolved", False)


def test_star_import_binds_nothing() -> None:
    text = "from errors import *\ntry:\n    f()\nexcept Mystery:\n    raise\n"
    assert identity_rows(text) == [("Mystery", None, "unresolved", False)]


def test_catch_fact_shape_for_bare_and_star() -> None:
    text = "try:\n    f()\nexcept:\n    pass\n"
    (bare,) = catches(text)
    assert (bare.kind, bare.bare, bare.identities, bare.bound_name) == ("except", True, (), None)
    assert bare.body.classification == "empty"
    star = (
        "async def g():\n    try:\n        await h()\n    except* OSError as grp:\n        raise\n"
    )
    (fact,) = catches(star)
    assert (fact.kind, fact.bound_name, fact.scope) == ("except*", "grp", "g")
    assert fact.try_statements[0].operation == "h"


def test_module_dotted_name_derivation() -> None:
    from shockharness.ir.python_catches import module_dotted_name

    assert module_dotted_name("src/pkg/mod.py") == "src.pkg.mod"
    assert module_dotted_name("pkg/__init__.py") == "pkg"
    assert module_dotted_name("mod.py") == "mod"
    assert module_dotted_name("<test>") == "<test>"
