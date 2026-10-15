"""Hypothesis: random programs from a small grammar, rendered to both languages, never
make the extractors or the metrics raise, and give the same numbers in Python and
JavaScript (parity is a property, not a table)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from shockharness.complexity.metrics import measure_units
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.python import extract_python_facts
from shockharness.source import SourceText

SETTINGS = {"cyclomatic_counts_boolean_operators": True, "npath_cap": 500}


def _cond(depth: int) -> st.SearchStrategy:
    # a boolean chain: operands joined by and/or
    return st.lists(st.sampled_from(["and", "or"]), min_size=0, max_size=3)


@st.composite
def _program(draw: st.DrawFn, depth: int = 0) -> list:
    """A list of abstract statements. Each is a tuple; nested lists are bodies."""
    if depth > 3:
        choices = ["expr", "ret"]
    else:
        choices = ["expr", "ret", "if", "ifelse", "while", "for", "try", "ternary", "nested"]
    count = draw(st.integers(min_value=0, max_value=3))
    statements = []
    for _ in range(count):
        kind = draw(st.sampled_from(choices))
        if kind in ("expr", "ret") or kind == "ternary":
            statements.append((kind, draw(_cond(depth))))
        elif kind == "try":
            statements.append((kind, draw(_program(depth + 1)), draw(_program(depth + 1))))
        elif kind == "ifelse":
            statements.append(
                (kind, draw(_cond(depth)), draw(_program(depth + 1)), draw(_program(depth + 1)))
            )
        elif kind == "nested":
            statements.append((kind, draw(_program(depth + 1))))
        else:
            statements.append((kind, draw(_cond(depth)), draw(_program(depth + 1))))
    return statements


def _chain(ops: list[str], language: str) -> str:
    symbols = {"and": "&&", "or": "||"} if language == "js" else {"and": "and", "or": "or"}
    text = "a"
    for index, op in enumerate(ops):
        text += f" {symbols[op]} b{index}"
    return text


def _render(statements: list, language: str, indent: int, counter: list[int]) -> list[str]:
    pad = "    " * indent
    lines: list[str] = []
    for statement in statements:
        kind = statement[0]
        if kind == "expr":
            lines.append(
                pad
                + (
                    f"x = {_chain(statement[1], language)};"
                    if language == "js"
                    else f"x = {_chain(statement[1], language)}"
                )
            )
        elif kind == "ret":
            lines.append(
                pad
                + (
                    f"return {_chain(statement[1], language)};"
                    if language == "js"
                    else f"return {_chain(statement[1], language)}"
                )
            )
        elif kind == "ternary":
            c = _chain(statement[1], language)
            lines.append(
                pad + (f"x = ({c}) ? 1 : 0;" if language == "js" else f"x = 1 if ({c}) else 0")
            )
        elif kind == "if" or kind == "while":
            c = _chain(statement[1], language)
            body = _render(statement[2], language, indent + 1, counter)
            if language == "js":
                lines.append(pad + f"{kind} ({c}) {{")
                lines.extend(body)
                lines.append(pad + "}")
            else:
                lines.append(pad + f"{kind} {c}:")
                lines.extend(body if body else [pad + "    pass"])
        elif kind == "for":
            body = _render(statement[2], language, indent + 1, counter)
            if language == "js":
                lines.append(pad + "for (const i of items) {")
                lines.extend(body)
                lines.append(pad + "}")
            else:
                lines.append(pad + "for i in items:")
                lines.extend(body if body else [pad + "    pass"])
        elif kind == "ifelse":
            c = _chain(statement[1], language)
            then = _render(statement[2], language, indent + 1, counter)
            other = _render(statement[3], language, indent + 1, counter)
            if language == "js":
                lines.append(pad + f"if ({c}) {{")
                lines.extend(then)
                lines.append(pad + "} else {")
                lines.extend(other)
                lines.append(pad + "}")
            else:
                lines.append(pad + f"if {c}:")
                lines.extend(then if then else [pad + "    pass"])
                lines.append(pad + "else:")
                lines.extend(other if other else [pad + "    pass"])
        elif kind == "try":
            body = _render(statement[1], language, indent + 1, counter)
            handler = _render(statement[2], language, indent + 1, counter)
            if language == "js":
                lines.append(pad + "try {")
                lines.extend(body)
                lines.append(pad + "} catch (e) {")
                lines.extend(handler)
                lines.append(pad + "}")
            else:
                lines.append(pad + "try:")
                lines.extend(body if body else [pad + "    pass"])
                lines.append(pad + "except ValueError:")
                lines.extend(handler if handler else [pad + "    pass"])
        else:
            assert kind == "nested"
            counter[0] += 1
            name = f"inner{counter[0]}"
            body = _render(statement[1], language, indent + 1, counter)
            if language == "js":
                lines.append(pad + f"function {name}() {{")
                lines.extend(body)
                lines.append(pad + "}")
            else:
                lines.append(pad + f"def {name}():")
                lines.extend(body if body else [pad + "    pass"])
    return lines


def render(statements: list, language: str) -> str:
    counter = [0]
    body = _render(statements, language, 1, counter)
    if language == "js":
        return "function f(a, b0, b1, b2, items) {\n" + "\n".join(body) + "\n}\n"
    return "def f(a, b0, b1, b2, items):\n" + "\n".join(body if body else ["    pass"]) + "\n"


@given(program=_program())
@settings(max_examples=150, deadline=None)
def test_random_programs_never_raise_and_match_across_languages(program: list) -> None:
    py_source = render(program, "py")
    js_source = render(program, "js")
    py_facts = extract_python_facts(SourceText.from_text(py_source), "f.py")
    js_facts = extract_javascript_facts(SourceText.from_text(js_source), "f.js")
    assert py_facts.parse_failure is None, py_source
    assert js_facts.parse_failure is None, js_source
    py_units = {u.name: u for u in measure_units("f", py_facts.functions, SETTINGS)}
    js_units = {u.name: u for u in measure_units("f", js_facts.functions, SETTINGS)}
    assert set(py_units) == set(js_units)
    for name, py_unit in py_units.items():
        js_unit = js_units[name]
        numbers = ("cyclomatic", "cognitive", "nesting", "npath", "npath_saturated")
        assert [getattr(py_unit, n) for n in numbers] == [getattr(js_unit, n) for n in numbers], (
            name
        )
        assert py_unit.cyclomatic >= 1 and py_unit.cognitive >= 0 and py_unit.nesting >= 0
        assert 1 <= py_unit.npath <= SETTINGS["npath_cap"]
        assert py_unit.npath_saturated == (py_unit.npath >= SETTINGS["npath_cap"])
        assert py_unit.fact.control == js_unit.fact.control
