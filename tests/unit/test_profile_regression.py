"""Milestone H1 regression: the golden corpus keeps its 0.3.0 verdicts under every profile.

``tests/fixtures/profile_verdicts_0.3.0.json`` was written by :func:`snapshot` running
against the 0.3.0 code (commit 68fa69a, before H1 changed anything); the command is
recorded in STATUS.md. Every fixture is analyzed alone (with its own ``exceptions``
settings, as the golden test does) and the whole corpus once as a tree, under each
built-in profile. The finding sets (rule, span, severity, confidence, a digest of the
message, suppression) and the gate verdict, exit code and counts must be unchanged; fields
added after 0.3.0 (``status``, ``role``, ``gate.unknown`` ...) are deliberately not
compared, so the defaults of ``fail_on_unknown`` are what this test pins down.

Intended differences since 0.3.0 are listed below and applied to the snapshot before
comparing, so every other change still fails. 0.5.0 (docs/shockharness-suggestions-4.md):
item 2 removes the checked-then-raised ``table.get("raw")`` finding in every profile, and
item 6 (``recommended`` sets ``rules.defaults.fail_on_unknown = false``) moves two unknown
DEF002 findings out of the gate's hard and review counts under ``recommended``.

The H3 rules (EXC004, STUB*, ASSERT001, BOOL001, STATE001, IMPORT001) did not exist in
0.3.0: the snapshot comparison runs with them switched off, and
``test_h3_rules_never_change_a_gate_verdict`` checks that switching them on changes no
gate status, exit code or hard-violation count (they ship at warning and review).
"""

import functools
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from shockharness import gate as gate_module
from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.findings import Finding
from shockharness.gate import NO_REGRESSIONS, GateResult
from shockharness.schema import PROFILES
from tests.conftest import FIXTURES, exceptions_config_toml, language_for_fixture

SNAPSHOT = FIXTURES / "profile_verdicts_0.3.0.json"
CORPUS = "corpus"
# (fixture path, rule, line, column) of findings removed on purpose since 0.3.0.
REMOVED_SINCE_0_3_0 = frozenset({("python/def_mapping_get.py", "DEF002", 47, 11)})
# (profile, fixture path or CORPUS) -> gate counts changed on purpose since 0.3.0.
GATE_SINCE_0_3_0: dict[tuple[str, str], dict[str, int]] = {
    ("strict", "python/def_mapping_get.py"): {"review": 2},
    ("strict", CORPUS): {"review": 28},
    ("recommended", "python/def_mapping_get.py"): {"hard_violations": 10, "review": 1},
    ("recommended", CORPUS): {"hard_violations": 345, "review": 40},
    ("minimal", "python/def_mapping_get.py"): {"review": 14},
    ("minimal", CORPUS): {"review": 389},
}
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CORPUS_DIRECTORIES = ("python", "javascript")
# The message is compared by digest: the snapshot stays small, and any change to a
# message still fails the comparison.
MESSAGE_DIGEST_HEX = 16
# Arrays of scalars (one finding, one span) are written on one line each.
SCALAR_ARRAY = re.compile(r"\[\n\s*([^\[\]{}]*?)\n\s*\]")


def _finding(finding: Finding) -> list[Any]:
    return [
        finding.rule_id,
        finding.span.line,
        finding.span.column,
        finding.severity,
        finding.confidence,
        hashlib.sha256(finding.message.encode("utf-8")).hexdigest()[:MESSAGE_DIGEST_HEX],
        finding.is_suppressed,
    ]


def _verdict(gate: GateResult) -> dict[str, Any]:
    return {
        "status": gate.status,
        "exit_code": gate.exit_code,
        "hard_violations": gate.hard_violations,
        "warnings": gate.warnings,
        "review": gate.review,
        "suppressed": gate.suppressed,
        "analysis_failures": gate.analysis_failures,
    }


# The H3 rules switched off: their sections, and EXC004 (which shares rules.exceptions).
H3_OFF = (
    "".join(
        f"[tool.shockharness.rules.{section}]\nenabled = false\n"
        for section in (
            "stubs",
            "assertions",
            "boolean_arguments",
            "module_state",
            "import_effects",
        )
    )
    + '[[tool.shockharness.overrides]]\npaths = ["**"]\ndisable = ["EXC004"]\nreason = "0.3.0"\n'
)


def _write_config(root: Path, profile: str, extra: str) -> None:
    cache = "[tool.shockharness.cache]\nenabled = false\n"
    body = f'[tool.shockharness]\nprofile = "{profile}"\n{cache}{extra}'
    (root / ".shockharness.toml").write_text(body, encoding="utf-8")


def fixture_outcome(name: str, profile: str, root: Path, h3: bool) -> dict[str, Any]:
    extra = ""
    if "exceptions" in EXPECTED[name]:
        extra = exceptions_config_toml(EXPECTED[name]["exceptions"])
    if not h3:
        extra = H3_OFF + extra
    _write_config(root, profile, extra)
    config = load_config(root, None)
    text = (FIXTURES / name).read_text(encoding="utf-8")
    result = analyze_text(name, language_for_fixture(name), text, config, OPTIONS)
    verdict = gate_module.evaluate(result.findings, [result], config, None, NO_REGRESSIONS)
    return {
        "status": result.status,
        "findings": [_finding(f) for f in result.findings],
        "gate": _verdict(verdict),
    }


def corpus_outcome(profile: str, root: Path, h3: bool) -> dict[str, Any]:
    for directory in CORPUS_DIRECTORIES:
        shutil.copytree(FIXTURES / directory, root / directory)
    _write_config(root, profile, "" if h3 else H3_OFF)
    config = load_config(root, None)
    report = analyze_paths([root], root, config, OPTIONS)
    return {
        "files": {f.path: f.status for f in report.files},
        "findings": [[f.path, *_finding(f)] for f in report.findings],
        "gate": _verdict(report.gate),
    }


def snapshot(scratch: Path) -> dict[str, Any]:
    """The whole regression document: per profile, every fixture alone and the corpus."""
    document: dict[str, Any] = {}
    for profile in PROFILES:
        fixtures: dict[str, Any] = {}
        for name in sorted(EXPECTED):
            root = scratch / profile / "fixtures" / name.replace("/", "__")
            root.mkdir(parents=True)
            fixtures[name] = fixture_outcome(name, profile, root, False)
        corpus_root = scratch / profile / "corpus"
        corpus_root.mkdir(parents=True)
        document[profile] = {
            "fixtures": fixtures,
            "corpus": corpus_outcome(profile, corpus_root, False),
        }
    return document


@functools.cache
def snapshot_document() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return loaded


def _removed(path: str, finding: list[Any]) -> bool:
    rule, line, column = finding[0], finding[1], finding[2]
    return (path, rule, line, column) in REMOVED_SINCE_0_3_0


def expected_outcome(profile: str, name: str) -> dict[str, Any]:
    """The 0.3.0 snapshot for ``name`` (a fixture or CORPUS) with the intended changes."""
    document = snapshot_document()[profile]
    if name == CORPUS:
        outcome = json.loads(json.dumps(document["corpus"]))
        outcome["findings"] = [f for f in outcome["findings"] if not _removed(f[0], f[1:])]
    else:
        outcome = json.loads(json.dumps(document["fixtures"][name]))
        outcome["findings"] = [f for f in outcome["findings"] if not _removed(name, f)]
    if (profile, name) in GATE_SINCE_0_3_0:
        outcome["gate"].update(GATE_SINCE_0_3_0[(profile, name)])
    return outcome


def test_snapshot_covers_every_profile_and_fixture() -> None:
    assert sorted(snapshot_document()) == sorted(PROFILES)
    for profile in PROFILES:
        assert sorted(snapshot_document()[profile]["fixtures"]) == sorted(EXPECTED)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_verdict_unchanged_since_0_3_0(name: str, profile: str, tmp_path: Path) -> None:
    assert fixture_outcome(name, profile, tmp_path, False) == expected_outcome(profile, name)


@pytest.mark.parametrize("profile", PROFILES)
def test_corpus_verdict_unchanged_since_0_3_0(profile: str, tmp_path: Path) -> None:
    assert corpus_outcome(profile, tmp_path, False) == expected_outcome(profile, CORPUS)


VERDICT_KEYS = ("status", "exit_code", "hard_violations", "analysis_failures")


@pytest.mark.parametrize("profile", PROFILES)
def test_h3_rules_never_change_a_gate_verdict(profile: str, tmp_path: Path) -> None:
    expected = expected_outcome(profile, CORPUS)["gate"]
    actual = corpus_outcome(profile, tmp_path, True)["gate"]
    assert {k: actual[k] for k in VERDICT_KEYS} == {k: expected[k] for k in VERDICT_KEYS}


if __name__ == "__main__":
    # python -m tests.unit.test_profile_regression <scratch-dir>: rewrite the snapshot.
    # Only ever run against the release whose verdicts the snapshot names.
    written = snapshot(Path(sys.argv[1]))
    text = SCALAR_ARRAY.sub(
        lambda m: "[" + ", ".join(p.strip().rstrip(",") for p in m.group(1).split("\n")) + "]",
        json.dumps(written, indent=1, sort_keys=True),
    )
    assert json.loads(text) == written
    SNAPSHOT.write_text(text + "\n", encoding="utf-8")
