"""Property-based and metamorphic tests (Hypothesis)."""

import keyword
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from shockharness.analysis import AnalysisOptions, analyze_text
from shockharness.config import load_bundled_defaults, load_config
from shockharness.ir.javascript import extract_javascript_facts, parse_js_number
from shockharness.ir.python import extract_python_facts
from shockharness.source import SourceText

_ROOT = Path(tempfile.mkdtemp(prefix="shockharness-prop-"))
CONFIG = load_config(_ROOT, None)
OPTIONS = AnalysisOptions(inline_suppressions=True)

JS_RESERVED = frozenset(
    [
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "implements",
        "import",
        "in",
        "instanceof",
        "interface",
        "let",
        "new",
        "null",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
        "arguments",
        "eval",
        "undefined",
    ]
)
identifiers = st.from_regex(r"\A[a-z_][a-z0-9_]{0,11}\Z").filter(
    lambda s: (
        not keyword.iskeyword(s)
        and s not in JS_RESERVED
        and s not in {"print", "exec", "match", "case", "type"}
    )
)
not_zero_or_one = st.integers(min_value=2, max_value=10**15) | st.integers(
    min_value=-(10**15), max_value=-1
)


@given(value=not_zero_or_one, name=identifiers)
@settings(max_examples=200, deadline=None)
def test_any_other_integer_is_flagged_in_both_languages(value: int, name: str) -> None:
    py = analyze_text("p.py", "python", f"{name} = {value}\n", CONFIG, OPTIONS)
    js = analyze_text("j.js", "javascript", f"const {name} = {value};\n", CONFIG, OPTIONS)
    assert [f.rule_id for f in py.findings] == ["MAGIC001"]
    assert [f.rule_id for f in js.findings] == ["MAGIC001"]
    assert str(value) in py.findings[0].message
    assert str(value) in js.findings[0].message


@given(value=st.sampled_from([0, 1]), name=identifiers)
@settings(max_examples=50, deadline=None)
def test_zero_and_one_never_flagged(value: int, name: str) -> None:
    assert analyze_text("p.py", "python", f"{name} = {value}\n", CONFIG, OPTIONS).findings == ()
    assert (
        analyze_text("j.js", "javascript", f"let {name} = {value};\n", CONFIG, OPTIONS).findings
        == ()
    )


@given(n=st.integers(min_value=0, max_value=2**70))
@settings(max_examples=200, deadline=None)
def test_js_integer_encodings_round_trip(n: int) -> None:
    assert parse_js_number(str(n)) == n
    assert parse_js_number(hex(n)) == n
    assert parse_js_number(oct(n)) == n
    assert parse_js_number(bin(n)) == n
    assert parse_js_number(f"{n}n") == n
    assert parse_js_number(hex(n).upper().replace("0X", "0x")) == n


@given(x=st.floats(min_value=0, allow_nan=False, allow_infinity=False, width=64))
@settings(max_examples=200, deadline=None)
def test_js_float_repr_round_trips(x: float) -> None:
    assert parse_js_number(repr(x)) == x


@given(blank_lines=st.integers(min_value=0, max_value=20), value=not_zero_or_one)
@settings(max_examples=100, deadline=None)
def test_whitespace_shift_is_metamorphic(blank_lines: int, value: int) -> None:
    base = analyze_text("p.py", "python", f"x = {value}\n", CONFIG, OPTIONS)
    shifted = analyze_text("p.py", "python", "\n" * blank_lines + f"x = {value}\n", CONFIG, OPTIONS)
    assert [(f.rule_id, f.span.column) for f in base.findings] == [
        (f.rule_id, f.span.column) for f in shifted.findings
    ]
    assert shifted.findings[0].span.line == base.findings[0].span.line + blank_lines


@given(name=identifiers, other=identifiers, value=not_zero_or_one)
@settings(max_examples=100, deadline=None)
def test_identifier_rename_is_invariant(name: str, other: str, value: int) -> None:
    a = analyze_text(
        "p.py", "python", f"def {name}({other}):\n    return {other} + {value}\n", CONFIG, OPTIONS
    )
    b = analyze_text("p.py", "python", f"def q(r):\n    return r + {value}\n", CONFIG, OPTIONS)
    assert [f.message for f in a.findings] == [f.message for f in b.findings]


@given(text=st.text(max_size=300))
@settings(max_examples=300, deadline=None)
def test_python_adapter_never_raises(text: str) -> None:
    facts = extract_python_facts(SourceText.from_text(text), "<fuzz>")
    assert facts.parse_failure is not None or isinstance(facts.numeric_literals, tuple)


@given(text=st.text(max_size=300))
@settings(max_examples=300, deadline=None)
def test_javascript_adapter_never_raises(text: str) -> None:
    facts = extract_javascript_facts(SourceText.from_text(text), "<fuzz>")
    assert facts.parse_failure is not None or isinstance(facts.numeric_literals, tuple)


def test_bundled_defaults_are_the_strict_profile() -> None:
    assert load_bundled_defaults()["profile"] == "strict"
