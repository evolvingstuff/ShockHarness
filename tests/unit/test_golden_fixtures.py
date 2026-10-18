"""Golden fixture corpus: every file under tests/fixtures has reviewed expectations.

A fixture entry may carry an ``exceptions`` table (``rules.exceptions`` settings
such as boundaries or ``transparent_rethrow``); the fixture is then analyzed under
the strict profile plus exactly those settings. The fixture's own path is what the
boundary globs match against.
"""

import json
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, analyze_text
from tests.conftest import FIXTURES, fixture_config, language_for_fixture

EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def test_every_fixture_file_has_expectations() -> None:
    present = sorted(
        p.relative_to(FIXTURES).as_posix()
        for p in FIXTURES.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".js", ".mjs", ".cjs"}
        # Multi-file projects with their own catalog (tests/unit/test_property_contracts.py).
        and p.relative_to(FIXTURES).parts[0] != "property_contracts"
    )
    assert present == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_golden(name: str, empty_root: Path) -> None:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    expected = EXPECTED[name]
    config = fixture_config(name, expected, empty_root)
    result = analyze_text(
        name, language_for_fixture(name), text, config, AnalysisOptions(True, CACHE_CONFIGURED)
    )
    assert result.status == expected["status"]
    actual = [
        [f.rule_id, f.span.line, f.span.column, f.message, f.is_suppressed] for f in result.findings
    ]
    assert len(actual) == len(expected["findings"]), actual
    for got, want in zip(actual, expected["findings"], strict=True):
        rule_id, line, column, token, suppressed = want
        assert got[0] == rule_id
        assert (got[1], got[2]) == (line, column), (got, want)
        assert token in got[3], (got, want)
        assert got[4] is suppressed, (got, want)
    if "parse_failure_line" in expected:
        assert result.parse_failure is not None
        assert result.parse_failure.span is not None
        assert result.parse_failure.span.line == expected["parse_failure_line"]
