"""H2: VERIFY001, VERIFY002, VERIFY004 comparing a base and a head revision's facts.

The facts come from the real extractors so the comparison is tested on what the
adapters actually produce; samples are strings (see test_verification_facts.py).
"""

from collections.abc import Mapping
from typing import Any

from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import NO_VERIFICATION
from shockharness.ir.python import extract_python_facts
from shockharness.roles import ROLE_GENERATED, ROLE_PRODUCTION, ROLE_TEST
from shockharness.rules.verification import (
    COVERAGE_ANALYZED,
    COVERAGE_DISABLED,
    FileVerification,
    Renames,
    compare_revisions,
)
from shockharness.source import SourceText

BASE_COMMIT = "a" * 40
NO_RENAMES = Renames(available=True, error=None, head_to_base={})
SETTINGS: dict[str, Any] = {
    "enabled": True,
    "severity": "warning",
    "fail_on_unknown": False,
    "allowed_skip_reasons": [],
    "report_narrow_suppressions": False,
}


def file(path: str, text: str, role: str) -> FileVerification:
    if path.endswith(".py"):
        facts = extract_python_facts(SourceText.from_text(text), path)
    else:
        facts = extract_javascript_facts(SourceText.from_text(text), path)
    assert facts.parse_failure is None, facts.parse_failure
    return FileVerification(
        path=path, role=role, failure=None, disabled=frozenset(), facts=facts.verification
    )


def failed(path: str, role: str) -> FileVerification:
    return FileVerification(
        path=path,
        role=role,
        failure="parse_error: SyntaxError",
        disabled=frozenset(),
        facts=NO_VERIFICATION,
    )


def compare(
    base: list[FileVerification],
    head: list[FileVerification],
    settings: Mapping[str, Any] = SETTINGS,
    renames: Renames = NO_RENAMES,
) -> list[Finding]:
    result = compare_revisions(
        {f.path: f for f in base}, {f.path: f for f in head}, renames, settings, BASE_COMMIT
    )
    return list(result.findings)


def rules(findings: list[Finding]) -> list[tuple[str, str, int]]:
    return [(f.rule_id, f.path, f.span.line) for f in findings]


BASE_TEST = """\
import pytest

@pytest.mark.skip(reason="old debt")
def test_old():
    assert run() == expected()

def test_add():
    assert add(one, one) == two

def test_sub():
    assert sub(two, one) == one
"""


# --- VERIFY001 --------------------------------------------------------------------------


def test_added_skip_is_reported_and_existing_skip_is_debt() -> None:
    head = BASE_TEST.replace("def test_add", '@pytest.mark.skip(reason="flaky")\ndef test_add')
    found = compare(
        [file("tests/test_a.py", BASE_TEST, ROLE_TEST)], [file("tests/test_a.py", head, ROLE_TEST)]
    )
    assert rules(found) == [("VERIFY001", "tests/test_a.py", 7)]
    (finding,) = found
    assert finding.status == STATUS_VIOLATION
    assert finding.severity == "warning"
    assert finding.scope == "test_add"
    assert "skip marker pytest.mark.skip(reason='flaky') added to test_add" in finding.message
    assert "not present at base aaaaaaaaaaaa" in finding.message


def test_moving_an_existing_skip_down_the_file_is_not_added() -> None:
    head = "\n\n# a comment\n" + BASE_TEST
    assert (
        compare(
            [file("tests/test_a.py", BASE_TEST, ROLE_TEST)],
            [file("tests/test_a.py", head, ROLE_TEST)],
        )
        == []
    )


def test_allowed_skip_reason_is_not_reported() -> None:
    head = BASE_TEST.replace("def test_add", '@pytest.mark.skip(reason="POSIX only")\ndef test_add')
    settings = {**SETTINGS, "allowed_skip_reasons": ["POSIX only"]}
    assert (
        compare(
            [file("tests/test_a.py", BASE_TEST, ROLE_TEST)],
            [file("tests/test_a.py", head, ROLE_TEST)],
            settings,
        )
        == []
    )


def test_javascript_focus_marker_is_reported() -> None:
    base = 'describe("m", () => { it("a", () => { expect(f()).toBe(g); }); });\n'
    head = base.replace('it("a"', 'it.only("a"')
    found = compare(
        [file("tests/m.test.js", base, ROLE_TEST)], [file("tests/m.test.js", head, ROLE_TEST)]
    )
    assert [(f.rule_id, f.scope) for f in found] == [("VERIFY001", "m > a")]
    assert "every other test in the run is skipped" in found[0].message


def test_markers_outside_test_role_are_not_checked() -> None:
    head = BASE_TEST.replace("def test_add", "@pytest.mark.skip\ndef test_add")
    found = compare(
        [file("src/a.py", BASE_TEST, ROLE_PRODUCTION)], [file("src/a.py", head, ROLE_PRODUCTION)]
    )
    assert [f.rule_id for f in found] == []


# --- VERIFY002 --------------------------------------------------------------------------


def test_added_blanket_suppression_is_reported_narrow_is_not_by_default() -> None:
    base = "def run():\n    return compute()\n"
    head = (
        "def run():\n    return compute()  # noqa\n\n\ndef other():\n    return x  # noqa: E501\n"
    )
    found = compare(
        [file("src/a.py", base, ROLE_PRODUCTION)], [file("src/a.py", head, ROLE_PRODUCTION)]
    )
    assert rules(found) == [("VERIFY002", "src/a.py", 2)]
    assert "blanket suppression # noqa added" in found[0].message
    narrow = compare(
        [file("src/a.py", base, ROLE_PRODUCTION)],
        [file("src/a.py", head, ROLE_PRODUCTION)],
        {**SETTINGS, "report_narrow_suppressions": True},
    )
    assert rules(narrow) == [("VERIFY002", "src/a.py", 2), ("VERIFY002", "src/a.py", 6)]
    assert "added for E501" in narrow[1].message


def test_existing_suppression_and_a_reworded_reason_are_not_added() -> None:
    base = 'x = run()  # noqa\ny = run()  # shockharness: ignore[EXC001] reason="old wording"\n'
    head = (
        'z = 1\nx = run()  # noqa\ny = run()  # shockharness: ignore[EXC001] reason="new wording"\n'
    )
    settings = {**SETTINGS, "report_narrow_suppressions": True}
    assert (
        compare(
            [file("src/a.py", base, ROLE_PRODUCTION)],
            [file("src/a.py", head, ROLE_PRODUCTION)],
            settings,
        )
        == []
    )


def test_a_second_identical_suppression_is_added() -> None:
    base = "x = run()  # noqa\n"
    head = "x = run()  # noqa\ny = run()  # noqa\n"
    found = compare(
        [file("src/a.py", base, ROLE_PRODUCTION)], [file("src/a.py", head, ROLE_PRODUCTION)]
    )
    assert len(found) == 1 and found[0].rule_id == "VERIFY002"


def test_generated_files_are_not_checked_for_suppressions() -> None:
    head = "/* eslint-disable */\nconst x = run();\n"
    found = compare([], [file("gen/out.js", head, ROLE_GENERATED)])
    assert found == []


def test_javascript_ts_ignore_and_eslint() -> None:
    base = "const x = run();\n"
    head = "// @ts-ignore\nconst x = run(); // eslint-disable-line\n"
    found = compare(
        [file("src/a.js", base, ROLE_PRODUCTION)], [file("src/a.js", head, ROLE_PRODUCTION)]
    )
    assert [(f.rule_id, f.evidence) for f in found] == [
        ("VERIFY002", "@ts-ignore"),
        ("VERIFY002", "eslint-disable-line"),
    ]


# --- VERIFY004 --------------------------------------------------------------------------


def test_tautology_zeroed_and_emptied_tests() -> None:
    head = BASE_TEST.replace("    assert add(one, one) == two\n", "    assert True\n").replace(
        "    assert sub(two, one) == one\n", "    pass\n"
    )
    found = compare(
        [file("tests/test_a.py", BASE_TEST, ROLE_TEST)], [file("tests/test_a.py", head, ROLE_TEST)]
    )
    assert [(f.rule_id, f.scope, f.evidence) for f in found] == [
        ("VERIFY004", "test_add", "assert True"),
        ("VERIFY004", "test_sub", "test_sub: 1 -> 0 assertion(s)"),
    ]
    assert "can never fail" in found[0].message
    assert "the body of test_sub is now empty" in found[1].message


def test_assertions_removed_but_body_kept_is_reported() -> None:
    head = BASE_TEST.replace("    assert sub(two, one) == one\n", "    sub(two, one)\n")
    found = compare(
        [file("tests/test_a.py", BASE_TEST, ROLE_TEST)], [file("tests/test_a.py", head, ROLE_TEST)]
    )
    assert [(f.rule_id, f.scope) for f in found] == [("VERIFY004", "test_sub")]
    assert "had 1 assertion(s) at base aaaaaaaaaaaa and has none now" in found[0].message


def test_new_test_without_assertions_is_not_a_regression() -> None:
    head = BASE_TEST + "\ndef test_new():\n    run()\n"
    assert (
        compare(
            [file("tests/test_a.py", BASE_TEST, ROLE_TEST)],
            [file("tests/test_a.py", head, ROLE_TEST)],
        )
        == []
    )


def test_javascript_tautology_added() -> None:
    base = 'it("a", () => { expect(f()).toBe(g); });\n'
    head = 'it("a", () => { expect(1).toBe(1); });\n'
    found = compare(
        [file("tests/a.test.js", base, ROLE_TEST)], [file("tests/a.test.js", head, ROLE_TEST)]
    )
    assert [(f.rule_id, f.evidence) for f in found] == [("VERIFY004", "expect(1).toBe(1)")]


# --- Files: new, renamed, unanalyzable base, rename detection unavailable --------------------


def test_new_file_counts_everything_as_added() -> None:
    head = "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert True\n"
    found = compare([], [file("tests/test_new.py", head, ROLE_TEST)])
    assert [(f.rule_id, f.status) for f in found] == [
        ("VERIFY001", STATUS_VIOLATION),
        ("VERIFY004", STATUS_VIOLATION),
    ]
    assert "in a file that does not exist at base" in found[0].message


def test_renamed_file_is_compared_with_its_base_version() -> None:
    renames = Renames(
        available=True, error=None, head_to_base={"tests/test_b.py": "tests/test_a.py"}
    )
    result = compare_revisions(
        {"tests/test_a.py": file("tests/test_a.py", BASE_TEST, ROLE_TEST)},
        {"tests/test_b.py": file("tests/test_b.py", BASE_TEST, ROLE_TEST)},
        renames,
        SETTINGS,
        BASE_COMMIT,
    )
    assert result.findings == ()
    assert result.coverage["renamed"] == 1
    assert result.coverage["files_new"] == 0


def test_unanalyzable_base_makes_findings_unknown() -> None:
    found = compare(
        [failed("tests/test_a.py", ROLE_TEST)], [file("tests/test_a.py", BASE_TEST, ROLE_TEST)]
    )
    assert [(f.rule_id, f.status, f.confidence) for f in found] == [
        ("VERIFY001", STATUS_UNKNOWN, "unresolved"),
    ]
    assert "could not be analyzed (parse_error: SyntaxError)" in found[0].message


def test_failed_rename_detection_makes_new_looking_files_unknown() -> None:
    renames = Renames(available=False, error="git diff failed", head_to_base={})
    found = compare([], [file("tests/test_a.py", BASE_TEST, ROLE_TEST)], SETTINGS, renames)
    assert [(f.rule_id, f.status) for f in found] == [("VERIFY001", STATUS_UNKNOWN)]
    assert "rename detection failed (git diff failed)" in found[0].message


def test_failed_head_file_is_not_compared() -> None:
    result = compare_revisions(
        {},
        {"tests/test_a.py": failed("tests/test_a.py", ROLE_TEST)},
        NO_RENAMES,
        SETTINGS,
        BASE_COMMIT,
    )
    assert result.findings == ()
    assert result.applied == {}


# --- Settings, disables, coverage, fingerprints -------------------------------------------------


def test_severity_comes_from_settings() -> None:
    found = compare(
        [],
        [file("src/a.py", "x = run()  # noqa\n", ROLE_PRODUCTION)],
        {**SETTINGS, "severity": "error"},
    )
    assert [f.severity for f in found] == ["error"]


def test_disabled_rules_and_family() -> None:
    head = file(
        "tests/test_a.py",
        "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert True  # noqa\n",
        ROLE_TEST,
    )
    partly = FileVerification(
        path=head.path,
        role=head.role,
        failure=None,
        disabled=frozenset({"VERIFY001"}),
        facts=head.facts,
    )
    found = compare([], [partly])
    assert sorted(f.rule_id for f in found) == ["VERIFY002", "VERIFY004"]
    result = compare_revisions(
        {}, {head.path: head}, NO_RENAMES, {**SETTINGS, "enabled": False}, BASE_COMMIT
    )
    assert result.findings == ()
    assert result.coverage["status"] == COVERAGE_DISABLED


def test_coverage_and_applied_rules_by_role() -> None:
    result = compare_revisions(
        {},
        {
            "tests/test_a.py": file("tests/test_a.py", BASE_TEST, ROLE_TEST),
            "src/a.py": file("src/a.py", "x = 1\n", ROLE_PRODUCTION),
            "gen/b.js": file("gen/b.js", "const y = 1;\n", ROLE_GENERATED),
        },
        NO_RENAMES,
        SETTINGS,
        BASE_COMMIT,
    )
    assert result.applied == {
        "src/a.py": ("VERIFY002",),
        "tests/test_a.py": ("VERIFY001", "VERIFY002", "VERIFY004"),
    }
    assert result.coverage["status"] == COVERAGE_ANALYZED
    assert result.coverage["files_compared"] == 2
    assert result.coverage["files_new"] == 2
    assert result.coverage["rules"] == ["VERIFY001", "VERIFY002", "VERIFY004"]


def test_fingerprints_are_unique_and_survive_line_moves() -> None:
    head = "x = run()  # noqa\ny = run()  # noqa\n"
    first = compare([], [file("src/a.py", head, ROLE_PRODUCTION)])
    moved = compare([], [file("src/a.py", "\n\n" + head, ROLE_PRODUCTION)])
    assert len({f.fingerprint for f in first}) == 2
    assert [f.fingerprint for f in first] == [f.fingerprint for f in moved]
