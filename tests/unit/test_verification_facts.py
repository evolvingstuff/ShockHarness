"""H2: verification facts extracted from Python and JavaScript sources.

Every sample is a string: the repository's own tests never carry a real skip marker,
tautology or blanket suppression (they would be VERIFY findings against this repo).
"""

import pytest

from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import (
    DIRECTIVE_SCOPE_FILE,
    DIRECTIVE_SCOPE_LINE,
    DIRECTIVE_SCOPE_NEXT_LINE,
    DIRECTIVE_SCOPE_REGION,
    MARKER_FOCUS,
    MARKER_SKIP,
    MARKER_XFAIL,
    Comment,
    Span,
    VerificationFacts,
)
from shockharness.ir.python import extract_python_facts
from shockharness.ir.suppression_directives import javascript_directives, python_directives
from shockharness.source import SourceText

SPAN = Span(1, 1, 1, 2)


def python_facts(text: str) -> VerificationFacts:
    facts = extract_python_facts(SourceText.from_text(text), "t.py")
    assert facts.parse_failure is None
    return facts.verification


def javascript_facts(text: str) -> VerificationFacts:
    facts = extract_javascript_facts(SourceText.from_text(text), "t.js")
    assert facts.parse_failure is None
    return facts.verification


# --- Python markers -----------------------------------------------------------------------

PYTHON_MARKERS = """\
import pytest
import unittest
from unittest import skip as skipit, expectedFailure
from pytest import mark

pytestmark = [pytest.mark.skipif(True, reason="module wide"), pytest.mark.slow]

@pytest.mark.skip(reason="flaky")
def test_a():
    assert compute()

@mark.xfail(strict=True, reason="known bug")
def test_b():
    pytest.skip("not today")
    assert compute()

@unittest.skipIf(True, "windows")
def test_c():
    pytest.xfail("later")

@skipit("broken")
def test_d():
    if flag:
        pytest.skip("conditional skips are not top level")
    assert compute()

@expectedFailure
def test_e():
    assert compute()

@pytest.mark.parametrize("x", [one, two])
def test_param(x):
    assert x

@unittest.skip("whole class")
class TestThing(unittest.TestCase):
    pytestmark = pytest.mark.xfail(reason="class wide")

    def test_x(self):
        self.skipTest("inside")

    @pytest.mark.skip
    def helper_not_a_test(self):
        assert compute()

@pytest.mark.skip(reason="not a test function")
def helper():
    assert compute()
"""


def test_python_markers_cover_every_documented_form() -> None:
    markers = python_facts(PYTHON_MARKERS).markers
    found = [(m.kind, m.test, m.reason) for m in markers]
    assert found == [
        (MARKER_SKIP, "<module>", "module wide"),
        (MARKER_SKIP, "test_a", "flaky"),
        (MARKER_XFAIL, "test_b", "known bug"),
        (MARKER_SKIP, "test_b", "not today"),
        (MARKER_SKIP, "test_c", "windows"),
        (MARKER_XFAIL, "test_c", "later"),
        (MARKER_SKIP, "test_d", "broken"),
        (MARKER_XFAIL, "test_e", None),
        (MARKER_SKIP, "TestThing", "whole class"),
        (MARKER_XFAIL, "TestThing", "class wide"),
        (MARKER_SKIP, "TestThing.test_x", "inside"),
    ]


def test_python_marker_text_is_the_marker_as_written() -> None:
    markers = python_facts(PYTHON_MARKERS).markers
    texts = {m.test: m.text for m in markers if m.test in ("test_a", "test_e")}
    assert texts == {
        "test_a": "pytest.mark.skip(reason='flaky')",
        "test_e": "expectedFailure",
    }


def test_python_markers_on_non_tests_and_other_marks_are_ignored() -> None:
    facts = python_facts(
        "import pytest\n\n@pytest.mark.skip\ndef helper():\n    pass\n\n"
        "@pytest.mark.parametrize('x', [a])\ndef test_ok(x):\n    assert x\n"
    )
    assert facts.markers == ()


def test_unrelated_skip_name_is_not_a_unittest_marker() -> None:
    facts = python_facts("from mylib import skip\n\n@skip\ndef test_a():\n    assert run()\n")
    assert facts.markers == ()


# --- Python cases ---------------------------------------------------------------------------

PYTHON_CASES = """\
import pytest
import unittest

def test_counts():
    assert run() == expected()
    with pytest.raises(ValueError):
        parse("x")
    mock.assert_called_once()
    assert_frame_equal(left, right)

def test_tautologies():
    assert True
    assert "message"
    assert 1 == 1
    assert None is None
    assert run() == run()
    assert 0

def test_empty():
    "Only a docstring."

def test_pass():
    pass

def test_ellipsis():
    ...

class Checks(unittest.TestCase):
    def test_methods(self):
        self.assertEqual(1, 1)
        self.assertTrue(True)
        self.assertIs(None, None)
        self.assertEqual(run(), one)

class TestNested:
    class TestInner:
        def test_deep(self):
            assert run()

def helper_with_asserts():
    assert True
"""


def test_python_cases_count_assertions_and_find_tautologies() -> None:
    cases = {c.name: c for c in python_facts(PYTHON_CASES).cases}
    assert sorted(cases) == [
        "Checks.test_methods",
        "TestNested.TestInner.test_deep",
        "test_counts",
        "test_ellipsis",
        "test_empty",
        "test_pass",
        "test_tautologies",
    ]
    assert cases["test_counts"].assertions == 4  # assert, pytest.raises, mock.assert_*, assert_*
    assert cases["test_counts"].tautologies == ()
    assert [t.text for t in cases["test_tautologies"].tautologies] == [
        "assert True",
        "assert 'message'",
        "assert 1 == 1",
        "assert None is None",
    ]
    assert [t.text for t in cases["Checks.test_methods"].tautologies] == [
        "self.assertEqual(1, 1)",
        "self.assertTrue(True)",
        "self.assertIs(None, None)",
    ]
    for name in ("test_empty", "test_pass", "test_ellipsis"):
        assert cases[name].body_empty, name
        assert cases[name].assertions == 0, name
    assert not cases["test_counts"].body_empty
    assert cases["TestNested.TestInner.test_deep"].assertions == 1


def test_python_case_span_is_the_def_line_not_the_decorator() -> None:
    cases = python_facts(
        "import pytest\n\n@pytest.mark.slow\ndef test_a():\n    assert run()\n"
    ).cases
    assert [(c.name, c.span.line) for c in cases] == [("test_a", 4)]


# --- JavaScript markers and cases ----------------------------------------------------------

JAVASCRIPT_SAMPLE = """\
describe("math", () => {
  it.only("adds", () => { expect(add(one, one)).toBe(two); expect(1).toBe(1); });
  xit(`subs`, () => {});
  it("works", function () {
    assert.equal(1, 1);
    assert.ok(result);
    assert(true);
    expect(true).toBeTruthy();
    expect(0).toBeFalsy();
    expect(null).toBeFalsy();
    expect(value).toBe(value);
    expect.assertions(3);
  });
  describe.skip("nested", () => {
    test("deep", () => {
      // nothing here
    });
  });
  it(name, () => { expect(run()).toEqual(expected); });
});
fit("top", async () => { await go(); });
fdescribe("focused", () => {});
xdescribe("skipped", () => {});
test.skip("later", () => { expect("x").toBe("x"); });
something.only("not a test api", () => {});
"""


def test_javascript_markers() -> None:
    markers = javascript_facts(JAVASCRIPT_SAMPLE).markers
    assert [(m.kind, m.test, m.text) for m in markers] == [
        (MARKER_FOCUS, "math > adds", "it.only('adds')"),
        (MARKER_SKIP, "math > subs", "xit('subs')"),
        (MARKER_SKIP, "math > nested", "describe.skip('nested')"),
        (MARKER_FOCUS, "top", "fit('top')"),
        (MARKER_FOCUS, "focused", "fdescribe('focused')"),
        (MARKER_SKIP, "skipped", "xdescribe('skipped')"),
        (MARKER_SKIP, "later", "test.skip('later')"),
    ]
    assert all(m.reason is None for m in markers)


def test_javascript_cases() -> None:
    cases = {c.name: c for c in javascript_facts(JAVASCRIPT_SAMPLE).cases}
    assert sorted(cases) == [
        "later",
        "math > <dynamic>",
        "math > adds",
        "math > nested > deep",
        "math > subs",
        "math > works",
        "top",
    ]
    assert cases["math > adds"].assertions == 2
    assert cases["math > works"].assertions == 7  # expect.assertions(n) is not an assertion
    assert [t.text for t in cases["math > adds"].tautologies] == ["expect(1).toBe(1)"]
    assert [t.text for t in cases["math > works"].tautologies] == [
        "assert.equal(1, 1)",
        "assert(true)",
        "expect(true).toBeTruthy()",
        "expect(0).toBeFalsy()",
        "expect(null).toBeFalsy()",
    ]
    assert cases["math > subs"].body_empty
    assert cases["math > nested > deep"].body_empty  # a comment is not a statement
    assert not cases["top"].body_empty
    assert cases["top"].assertions == 0
    assert [t.text for t in cases["later"].tautologies] == ['expect("x").toBe("x")']


# --- Suppression directives -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("# noqa", [("noqa", DIRECTIVE_SCOPE_LINE, (), False)]),
        ("# noqa: E501, F401 because", [("noqa", DIRECTIVE_SCOPE_LINE, ("E501", "F401"), True)]),
        ("# ruff: noqa", [("file-noqa", DIRECTIVE_SCOPE_FILE, (), False)]),
        ("# flake8: noqa: E501", [("file-noqa", DIRECTIVE_SCOPE_FILE, ("E501",), True)]),
        ("# type: ignore", [("type-ignore", DIRECTIVE_SCOPE_LINE, (), False)]),
        (
            "# type: ignore[attr-defined]",
            [("type-ignore", DIRECTIVE_SCOPE_LINE, ("attr-defined",), True)],
        ),
        (
            "# pylint: disable=no-member why",
            [("pylint", DIRECTIVE_SCOPE_LINE, ("no-member",), True)],
        ),
        ("# pylint: disable=all", [("pylint", DIRECTIVE_SCOPE_LINE, ("all",), False)]),
        ("# pylint: disable-next=x", [("pylint", DIRECTIVE_SCOPE_NEXT_LINE, ("x",), True)]),
        ("# pylint: skip-file", [("pylint", DIRECTIVE_SCOPE_FILE, (), False)]),
        ("# pragma: no cover", [("pragma-no-cover", DIRECTIVE_SCOPE_LINE, (), False)]),
        ("# mypy: ignore-errors", [("mypy-ignore-errors", DIRECTIVE_SCOPE_FILE, (), False)]),
        (
            '# shockharness: ignore[MAGIC001] reason="RFC"',
            [("shockharness", DIRECTIVE_SCOPE_LINE, ("MAGIC001",), True)],
        ),
        ("# talks about noqa and type checks", []),
        ("# first  # noqa", [("noqa", DIRECTIVE_SCOPE_LINE, (), False)]),
    ],
)
def test_python_directives(comment: str, expected: list[tuple[object, ...]]) -> None:
    found = python_directives([Comment(SPAN, comment)])
    assert [(d.tool, d.scope, d.codes, d.narrow) for d in found] == expected


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("// eslint-disable-next-line", [("eslint-disable", DIRECTIVE_SCOPE_NEXT_LINE, (), False)]),
        (
            "// eslint-disable-next-line no-console -- debug",
            [("eslint-disable", DIRECTIVE_SCOPE_NEXT_LINE, ("no-console",), True)],
        ),
        ("/* eslint-disable */", [("eslint-disable", DIRECTIVE_SCOPE_REGION, (), False)]),
        (
            "/* eslint-disable no-alert, no-console */",
            [("eslint-disable", DIRECTIVE_SCOPE_REGION, ("no-alert", "no-console"), True)],
        ),
        ("// eslint-disable-line x", [("eslint-disable", DIRECTIVE_SCOPE_LINE, ("x",), True)]),
        ("// @ts-ignore", [("ts-ignore", DIRECTIVE_SCOPE_NEXT_LINE, (), False)]),
        ("// @ts-expect-error", [("ts-expect-error", DIRECTIVE_SCOPE_NEXT_LINE, (), False)]),
        ("// @ts-nocheck", [("ts-nocheck", DIRECTIVE_SCOPE_FILE, (), False)]),
        ("/* istanbul ignore next */", [("istanbul-ignore", DIRECTIVE_SCOPE_REGION, (), False)]),
        ("/* c8 ignore start */", [("c8-ignore", DIRECTIVE_SCOPE_REGION, (), False)]),
        ("/* v8 ignore file */", [("c8-ignore", DIRECTIVE_SCOPE_FILE, (), False)]),
        ("/* c8 ignore stop */", []),
        ("// eslint-enable", []),
    ],
)
def test_javascript_directives(comment: str, expected: list[tuple[object, ...]]) -> None:
    found = javascript_directives([Comment(SPAN, comment)])
    assert [(d.tool, d.scope, d.codes, d.narrow) for d in found] == expected


def test_directive_identity_ignores_free_text() -> None:
    """Rewording an eslint description or a ShockHarness reason is not a new directive."""
    first = javascript_directives([Comment(SPAN, "// eslint-disable-line x -- one reason")])
    second = javascript_directives([Comment(SPAN, "// eslint-disable-line x -- reworded")])
    assert [d.text for d in first] == [d.text for d in second]
    one = python_directives([Comment(SPAN, '# shockharness: ignore[EXC001] reason="a"')])
    two = python_directives([Comment(SPAN, '# shockharness: ignore[EXC001] reason="b"')])
    assert [d.text for d in one] == [d.text for d in two] == ["shockharness: ignore[EXC001]"]


def test_directives_in_strings_are_not_comments() -> None:
    facts = python_facts('x = "# noqa"\ny = "# type: ignore"\n')
    assert facts.suppressions == ()
    js = javascript_facts('const s = "// eslint-disable-line";\n')
    assert js.suppressions == ()
