"""Milestone H1 regression: the golden corpus keeps its 0.3.0 verdicts under every profile.

``tests/fixtures/profile_verdicts_0.3.0.json`` was written by :func:`snapshot` running
against the 0.3.0 code (commit 68fa69a, before H1 changed anything); the command is
recorded in STATUS.md. Every fixture is analyzed alone (with its own ``exceptions``
settings, as the golden test does) and the whole corpus once as a tree, under each
built-in profile. The finding sets (rule, span, severity, confidence, a digest of the
message, suppression) and the gate verdict, exit code and counts must be unchanged; fields
added after 0.3.0 (``status``, ``role``, ``gate.unknown`` ...) are deliberately not
compared, so the defaults of ``fail_on_unknown`` are what this test pins down.
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


def _write_config(root: Path, profile: str, extra: str) -> None:
    cache = "[tool.shockharness.cache]\nenabled = false\n"
    body = f'[tool.shockharness]\nprofile = "{profile}"\n{cache}{extra}'
    (root / ".shockharness.toml").write_text(body, encoding="utf-8")


def fixture_outcome(name: str, profile: str, root: Path) -> dict[str, Any]:
    extra = ""
    if "exceptions" in EXPECTED[name]:
        extra = exceptions_config_toml(EXPECTED[name]["exceptions"])
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


def corpus_outcome(profile: str, root: Path) -> dict[str, Any]:
    for directory in CORPUS_DIRECTORIES:
        shutil.copytree(FIXTURES / directory, root / directory)
    _write_config(root, profile, "")
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
            fixtures[name] = fixture_outcome(name, profile, root)
        corpus_root = scratch / profile / "corpus"
        corpus_root.mkdir(parents=True)
        document[profile] = {"fixtures": fixtures, "corpus": corpus_outcome(profile, corpus_root)}
    return document


@functools.cache
def snapshot_document() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return loaded


def test_snapshot_covers_every_profile_and_fixture() -> None:
    assert sorted(snapshot_document()) == sorted(PROFILES)
    for profile in PROFILES:
        assert sorted(snapshot_document()[profile]["fixtures"]) == sorted(EXPECTED)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_verdict_unchanged_since_0_3_0(name: str, profile: str, tmp_path: Path) -> None:
    expected = snapshot_document()[profile]["fixtures"][name]
    assert fixture_outcome(name, profile, tmp_path) == expected


@pytest.mark.parametrize("profile", PROFILES)
def test_corpus_verdict_unchanged_since_0_3_0(profile: str, tmp_path: Path) -> None:
    assert corpus_outcome(profile, tmp_path) == snapshot_document()[profile]["corpus"]


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
