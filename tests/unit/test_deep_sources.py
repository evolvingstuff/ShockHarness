"""Deep and long sources never crash the tool: every collector walks with an explicit
stack, and a tree the host interpreter cannot build is a parse failure."""

import ast

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
# Long enough that a walk recursing once per level overflows (about 1000 frames), short
# enough that every supported CPython (3.11 included) parses it inside the test run.
LONG = 1500
NESTED = 90

PYTHON_SHAPES = {
    "binary": "def g(a):\n    return " + " + ".join(["a"] * LONG) + "\n",
    "boolean": "def g(a):\n    return " + " and ".join(["a"] * LONG) + "\n",
    "attributes": "def g(a):\n    return a" + ".b" * LONG + "\n",
    "subscripts": "def g(a):\n    return a" + "[0]" * LONG + "\n",
    "ternary": "def g(a):\n    return " + "a if a else " * LONG + "a\n",
    "unary": "X = " + "-" * LONG + "1\n",
    "lambdas": "f = " + "lambda: " * LONG + "1\n",
    "calls": "def g(a):\n    return " + "f(" * NESTED + "a" + ")" * NESTED + "\n",
    "lists": "X = " + "[" * NESTED + "]" * NESTED + "\n",
    "ifs": "def g(a):\n"
    + "".join("    " * (i + 1) + "if a:\n" for i in range(NESTED))
    + "    " * (NESTED + 1)
    + "return a\n",
}

JAVASCRIPT_DEPTH = 2000
JAVASCRIPT_SHAPES = {
    "binary": "export function g(a) { return " + " + ".join(["a"] * JAVASCRIPT_DEPTH) + "; }\n",
    "calls": "export const v = " + "f(" * JAVASCRIPT_DEPTH + "a" + ")" * JAVASCRIPT_DEPTH + ";\n",
    "ifs": "export function g(a) {\n"
    + "if (a) {\n" * JAVASCRIPT_DEPTH
    + "return a;\n"
    + "}\n" * JAVASCRIPT_DEPTH
    + "}\n",
    "arrows": "export const f = " + "() => " * JAVASCRIPT_DEPTH + "1;\n",
}

CSHARP_SHAPES = {
    "binary": "class C { int G(int a) { return " + " + ".join(["a"] * JAVASCRIPT_DEPTH) + "; } }\n",
    "calls": "class C { object V = "
    + "F(" * JAVASCRIPT_DEPTH
    + "1"
    + ")" * JAVASCRIPT_DEPTH
    + "; }\n",
    "ifs": "class C { int G(int a) {\n"
    + "if (a > 0) {\n" * JAVASCRIPT_DEPTH
    + "return a;\n"
    + "}\n" * JAVASCRIPT_DEPTH
    + "return 0; } }\n",
    "lambdas": "class C { object F = " + "() => " * JAVASCRIPT_DEPTH + "1; }\n",
    "switches": "class C { int G(int a) => "
    + "a switch { 0 => " * JAVASCRIPT_DEPTH
    + "0"
    + ", _ => 1 }" * JAVASCRIPT_DEPTH
    + "; }\n",
}


@pytest.mark.parametrize("shape", sorted(PYTHON_SHAPES))
def test_deep_python_is_analyzed(shape: str, strict_config: EffectiveConfig) -> None:
    result = analyze_text("src/deep.py", "python", PYTHON_SHAPES[shape], strict_config, OPTIONS)
    assert result.status == "analyzed"


@pytest.mark.parametrize("shape", sorted(JAVASCRIPT_SHAPES))
@pytest.mark.parametrize("language", ["javascript", "typescript"])
def test_deep_javascript_is_analyzed(
    shape: str, language: str, strict_config: EffectiveConfig
) -> None:
    path = "src/deep.ts" if language == "typescript" else "src/deep.js"
    result = analyze_text(path, language, JAVASCRIPT_SHAPES[shape], strict_config, OPTIONS)
    assert result.status == "analyzed"


def test_a_tree_the_parser_cannot_build_is_a_parse_failure(
    strict_config: EffectiveConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CPython 3.11 raises RecursionError from ast.parse for expressions a few thousand
    terms long; the file is then a parse failure, never an internal error."""

    def too_deep(*_args: object, **_kwargs: object) -> ast.Module:
        raise RecursionError("maximum recursion depth exceeded during ast construction")

    monkeypatch.setattr(ast, "parse", too_deep)
    result = analyze_text("src/deep.py", "python", "x = 1\n", strict_config, OPTIONS)
    assert result.status == "parse_error"
    assert result.parse_failure is not None
    assert result.parse_failure.message.startswith(
        "RecursionError: nested too deeply for this interpreter's parser"
    )


@pytest.mark.parametrize("shape", sorted(CSHARP_SHAPES))
def test_deep_csharp_is_analyzed(shape: str, strict_config: EffectiveConfig) -> None:
    result = analyze_text("Deep.cs", "csharp", CSHARP_SHAPES[shape], strict_config, OPTIONS)
    assert result.status == "analyzed"
