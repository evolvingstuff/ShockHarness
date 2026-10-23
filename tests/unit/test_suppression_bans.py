"""suppressions.forbidden: paths where no inline suppression counts."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import ConfigError, load_config
from shockharness.loosening import loosenings
from shockharness.report import Report

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
HEADER = '[tool.shockharness]\nprofile = "strict"\ninclude = ["**/*.py"]\n'
BAN = (
    "[[tool.shockharness.suppressions.forbidden]]\n"
    'paths = ["tests/regression/adversarial/**"]\n'
    'reason = "a regression case is resolved by a code change"\n'
)
SUPPRESSED = 'TIMEOUT_SECONDS = 30\nwait = 7  # shockharness: ignore[MAGIC001] reason="as found"\n'
CASE = "tests/regression/adversarial/case_1.py"
ELSEWHERE = "app/settings.py"
# The rules these tests are about (ROLE001 also judges the case file: it holds no test).
JUDGED = ("MAGIC001", "SUPP001")


def write(root: Path, config: str, files: dict[str, str]) -> None:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def analyze(root: Path, options: AnalysisOptions = OPTIONS) -> Report:
    return analyze_paths([root], root, load_config(root, None), options)


def findings(report: Report, path: str) -> list[tuple[str, int, bool, str]]:
    return sorted(
        (f.rule_id, f.span.line, f.suppression is not None, f.message)
        for f in report.findings
        if f.path == path and f.rule_id in JUDGED
    )


def test_a_suppression_under_a_banned_path_counts_for_nothing(tmp_path: Path) -> None:
    # The test exemption in the strict profile's overrides is not in this short config,
    # so MAGIC001 applies to the case file as it does to app code.
    write(tmp_path, HEADER + BAN, {CASE: SUPPRESSED, ELSEWHERE: SUPPRESSED})
    report = analyze(tmp_path)
    case = findings(report, CASE)
    assert [(rule, line, suppressed) for rule, line, suppressed, _m in case] == [
        ("MAGIC001", 2, False),
        ("SUPP001", 2, False),
    ]
    assert case[1][3] == (
        "inline suppressions are not allowed in tests/regression/adversarial/** "
        "(suppressions.forbidden): a regression case is resolved by a code change"
    )
    elsewhere = findings(report, ELSEWHERE)
    assert [(rule, suppressed) for rule, _line, suppressed, _m in elsewhere] == [("MAGIC001", True)]
    assert report.gate.status == "fail"


def test_a_malformed_suppression_there_is_still_reported_as_malformed(tmp_path: Path) -> None:
    write(tmp_path, HEADER + BAN, {CASE: "wait = 7  # shockharness: ignore[MAGIC001]\n"})
    messages = [m for rule, _l, _s, m in findings(analyze(tmp_path), CASE) if rule == "SUPP001"]
    assert len(messages) == 1 and "reason" in messages[0]


def test_the_ban_holds_on_a_cached_run(tmp_path: Path) -> None:
    cached = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
    write(tmp_path, HEADER, {CASE: SUPPRESSED})
    assert [r for r, _l, s, _m in findings(analyze(tmp_path, cached), CASE) if not s] == []
    write(tmp_path, HEADER + BAN, {})
    unsuppressed = [r for r, _l, s, _m in findings(analyze(tmp_path, cached), CASE) if not s]
    assert unsuppressed == ["MAGIC001", "SUPP001"]


def test_the_command_line_switch_keeps_its_own_message(tmp_path: Path) -> None:
    write(tmp_path, HEADER + BAN, {CASE: SUPPRESSED})
    options = AnalysisOptions(inline_suppressions=False, cache=CACHE_BYPASSED)
    messages = [
        m for rule, _l, _s, m in findings(analyze(tmp_path, options), CASE) if rule == "SUPP001"
    ]
    assert messages == ["inline suppressions are disabled by policy (--no-inline-suppressions)"]


def _invalid(root: Path, entry: str) -> str:
    (root / ".shockharness.toml").write_text(HEADER + entry, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_config(root, None)
    return str(raised.value)


def test_an_entry_needs_valid_paths_and_a_reason(tmp_path: Path) -> None:
    table = "[[tool.shockharness.suppressions.forbidden]]\n"
    assert "suppressions.forbidden[0].reason: required key is missing" in _invalid(
        tmp_path, table + 'paths = ["tests/**"]\n'
    )
    empty = table + 'paths = []\nreason = "r"\n'
    assert "suppressions.forbidden[0].paths: must list at least one path glob" in _invalid(
        tmp_path, empty
    )
    bad = table + 'paths = ["tests/a**"]\nreason = "r"\n'
    assert "suppressions.forbidden[0].paths[0]" in _invalid(tmp_path, bad)


def _ban(paths: str) -> str:
    return (
        "[[tool.shockharness.suppressions.forbidden]]\n"
        f"paths = [{paths}]\n"
        'reason = "a regression case is resolved by a code change"\n'
    )


def test_removing_or_narrowing_a_ban_is_a_loosening(tmp_path: Path) -> None:
    def keys(after: str) -> list[str]:
        config = tmp_path / ".shockharness.toml"
        config.write_text(HEADER + _ban('"tests/regression/**", "tests/fuzz/**"'), encoding="utf-8")
        before = load_config(tmp_path, None)
        config.write_text(HEADER + after, encoding="utf-8")
        later = load_config(tmp_path, None)
        found = loosenings(before.values, before.deviations, later.values, later.deviations)
        return [item.key for item in found]

    loosened = ["suppressions.forbidden"]
    assert keys("") == loosened
    assert keys(_ban('"tests/regression/**"')) == loosened
    assert keys(_ban('"tests/regression/**", "tests/fuzz/**", "app/crypto/**"')) == []
    split = _ban('"tests/fuzz/**"') + _ban('"tests/regression/**", "tests/fuzz/**"')
    assert keys(split) == []


def test_a_ban_is_not_a_deviation(tmp_path: Path) -> None:
    (tmp_path / ".shockharness.toml").write_text(HEADER + BAN, encoding="utf-8")
    assert not any("suppressions" in line for line in load_config(tmp_path, None).deviations)
