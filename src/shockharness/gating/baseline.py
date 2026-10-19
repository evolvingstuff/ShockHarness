"""Baseline fingerprints and baseline files.

A fingerprint identifies a finding by what it is, not where it is: rule ID, the
file's root-relative path, the enclosing scope, and the evidence line with all
whitespace removed. Findings in one file that agree on all four get an occurrence
index in source order. Moving a line, inserting lines above it, or reformatting
whitespace therefore keeps the fingerprint; changing the construct, the rule, the
scope, or the file does not.

A baseline is a reviewed JSON file of fingerprints produced by
``shockharness baseline create``. Nothing in the tool ever rewrites one.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.constants import BASELINE_SCHEMA_VERSION, FINGERPRINT_VERSION, JSON_INDENT
from shockharness.errors import UsageError
from shockharness.findings import Finding

FINGERPRINT_KEY = f"shockharness/v{FINGERPRINT_VERSION}"
# The baseline document's list of entries (read by VERIFY003 too).
FINGERPRINTS_FIELD = "fingerprints"

IdentityKey = tuple[str, str, str | None, str]


def normalize_evidence(evidence: str) -> str:
    """Evidence with every whitespace character removed (formatting-invariant)."""
    return "".join(evidence.split())


def identity_key(finding: Finding) -> IdentityKey:
    """(rule ID, path, enclosing scope or None, whitespace-free evidence)."""
    return (finding.rule_id, finding.path, finding.scope, normalize_evidence(finding.evidence))


def _digest(key: IdentityKey, occurrence: int) -> str:
    # JSON encoding keeps an absent scope (null) distinct from any string scope.
    material = json.dumps([FINGERPRINT_VERSION, *key, occurrence], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def assign_fingerprints(findings: Sequence[Finding]) -> list[Finding]:
    """Return ``findings`` (one file, already sorted) each carrying its fingerprint."""
    seen: dict[IdentityKey, int] = {}
    assigned: list[Finding] = []
    for finding in findings:
        key = identity_key(finding)
        if key not in seen:
            seen[key] = 0
        occurrence = seen[key]
        seen[key] = occurrence + 1
        assigned.append(finding.with_fingerprint(_digest(key, occurrence)))
    return assigned


@dataclass(frozen=True)
class BaselineEntry:
    fingerprint: str
    rule_id: str
    path: str
    scope: str | None
    evidence: str
    occurrence: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "rule_id": self.rule_id,
            "path": self.path,
            "scope": self.scope,
            "evidence": self.evidence,
            "occurrence": self.occurrence,
        }

    def sort_key(self) -> tuple[str, str, str, str, int]:
        return (self.path, self.rule_id, json.dumps(self.scope), self.evidence, self.occurrence)


@dataclass(frozen=True)
class Baseline:
    schema_version: str
    tool_version: str
    config_digest: str
    fingerprint_version: str
    entries: tuple[BaselineEntry, ...]
    origin: str

    @property
    def fingerprints(self) -> frozenset[str]:
        return frozenset(e.fingerprint for e in self.entries)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "config_digest": self.config_digest,
            "fingerprint_version": self.fingerprint_version,
            FINGERPRINTS_FIELD: [e.to_json_dict() for e in sorted(self.entries, key=_entry_sort)],
        }


def _entry_sort(entry: BaselineEntry) -> tuple[str, str, str, str, int]:
    return entry.sort_key()


def build_baseline(findings: Sequence[Finding], tool_version: str, config_digest: str) -> Baseline:
    """A baseline of every unsuppressed finding (any severity) with its fingerprint."""
    occurrences: dict[IdentityKey, int] = {}
    entries: list[BaselineEntry] = []
    for finding in findings:
        key = identity_key(finding)
        rule_id, path, scope, _normalized = key
        if key not in occurrences:
            occurrences[key] = 0
        occurrence = occurrences[key]
        occurrences[key] = occurrence + 1
        if finding.is_suppressed:
            continue
        assert finding.fingerprint is not None, "findings must be fingerprinted before baselining"
        entries.append(
            BaselineEntry(
                fingerprint=finding.fingerprint,
                rule_id=rule_id,
                path=path,
                scope=scope,
                evidence=finding.evidence,
                occurrence=occurrence,
            )
        )
    return Baseline(
        schema_version=BASELINE_SCHEMA_VERSION,
        tool_version=tool_version,
        config_digest=config_digest,
        fingerprint_version=FINGERPRINT_VERSION,
        entries=tuple(sorted(entries, key=_entry_sort)),
        origin="<new>",
    )


def render_baseline(baseline: Baseline) -> str:
    return json.dumps(baseline.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"


def _require_str(document: Mapping[str, Any], key: str, origin: str) -> str:
    if key not in document:
        raise UsageError(f"baseline is missing the string field {key!r}", origin)
    value = document[key]
    if not isinstance(value, str):
        raise UsageError(f"baseline is missing the string field {key!r}", origin)
    return value


def _optional_str(document: Mapping[str, Any], key: str, origin: str) -> str | None:
    if key not in document:
        raise UsageError(f"baseline entry is missing the string-or-null field {key!r}", origin)
    value = document[key]
    if value is not None and not isinstance(value, str):
        raise UsageError(f"baseline entry is missing the string-or-null field {key!r}", origin)
    return value


def _require_int(document: Mapping[str, Any], key: str, origin: str) -> int:
    if key not in document:
        raise UsageError(f"baseline entry is missing the integer field {key!r}", origin)
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageError(f"baseline entry is missing the integer field {key!r}", origin)
    return value


def parse_baseline(document: Any, origin: str) -> Baseline:
    """Validate a decoded baseline document. Every problem is a typed ``UsageError``."""
    if not isinstance(document, dict):
        raise UsageError("baseline must be a JSON object", origin)
    schema_version = _require_str(document, "schema_version", origin)
    if schema_version != BASELINE_SCHEMA_VERSION:
        raise UsageError(
            f"baseline schema_version {schema_version!r} is not supported "
            f"(this version reads {BASELINE_SCHEMA_VERSION!r})",
            origin,
        )
    fingerprint_version = _require_str(document, "fingerprint_version", origin)
    if fingerprint_version != FINGERPRINT_VERSION:
        raise UsageError(
            f"baseline fingerprint_version {fingerprint_version!r} does not match this "
            f"version's {FINGERPRINT_VERSION!r}; recreate the baseline",
            origin,
        )
    tool_version = _require_str(document, "tool_version", origin)
    config_digest = _require_str(document, "config_digest", origin)
    if FINGERPRINTS_FIELD not in document or not isinstance(document[FINGERPRINTS_FIELD], list):
        raise UsageError("baseline is missing the list field 'fingerprints'", origin)
    entries: list[BaselineEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(document[FINGERPRINTS_FIELD]):
        where = f"{origin} fingerprints[{index}]"
        if not isinstance(raw, dict):
            raise UsageError("baseline entry must be a JSON object", where)
        entry = BaselineEntry(
            fingerprint=_require_str(raw, "fingerprint", where),
            rule_id=_require_str(raw, "rule_id", where),
            path=_require_str(raw, "path", where),
            scope=_optional_str(raw, "scope", where),
            evidence=_require_str(raw, "evidence", where),
            occurrence=_require_int(raw, "occurrence", where),
        )
        if entry.fingerprint in seen:
            raise UsageError(f"duplicate fingerprint {entry.fingerprint}", where)
        seen.add(entry.fingerprint)
        entries.append(entry)
    return Baseline(
        schema_version=schema_version,
        tool_version=tool_version,
        config_digest=config_digest,
        fingerprint_version=fingerprint_version,
        entries=tuple(sorted(entries, key=_entry_sort)),
        origin=origin,
    )


def load_baseline(path: Path) -> Baseline:
    """Read and validate a baseline file. Unreadable or malformed input is a ``UsageError``."""
    # Boundary (declared in .shockharness.toml): reading a user-supplied baseline file.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read baseline: {exc}", str(path)) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"baseline is not valid UTF-8: {exc}", str(path)) from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsageError(f"baseline is not valid JSON: {exc}", str(path)) from exc
    return parse_baseline(document, str(path))


@dataclass(frozen=True)
class BaselineApplication:
    """What applying a baseline (or a base revision) to a set of findings did."""

    source: str  # "file" or "base_revision"
    origin: str  # file path, or the base commit hash
    mode: str  # gates.legacy
    applied: bool  # false under gates.legacy = "fail"
    matched: int
    stale: tuple[BaselineEntry, ...]
    tool_version: str | None
    config_digest_matches: bool | None
    notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "origin": self.origin,
            "mode": self.mode,
            "applied": self.applied,
            "matched": self.matched,
            "stale": [e.to_json_dict() for e in self.stale],
            "tool_version": self.tool_version,
            "config_digest_matches": self.config_digest_matches,
            "notes": list(self.notes),
        }


LEGACY_BASELINE = "baseline"
LEGACY_FAIL = "fail"
LEGACY_IGNORE = "ignore"
MARKER_MATCHED = "matched"
MARKER_IGNORED = "ignored"

SOURCE_FILE = "file"
SOURCE_BASE_REVISION = "base_revision"


def apply_fingerprints(
    findings: Sequence[Finding],
    known: frozenset[str],
    mode: str,
    source: str,
    origin: str,
    tool_version: str | None,
    config_digest_matches: bool | None,
    stale: tuple[BaselineEntry, ...],
) -> tuple[list[Finding], BaselineApplication]:
    """Mark findings whose fingerprint is in ``known`` according to ``mode``.

    ``baseline``: marked ``matched``; the gate counts them but does not fail on them.
    ``ignore``: marked ``ignored``; the gate neither counts nor fails on them.
    ``fail``: nothing is marked; every finding counts.
    """
    notes: list[str] = []
    if config_digest_matches is False:
        notes.append(
            "the baseline was created under a different configuration (config_digest differs); "
            "fingerprints are still compared, but findings the old policy did not produce are new"
        )
    if mode == LEGACY_FAIL:
        notes.append(
            f'gates.legacy = "fail": the {source.replace("_", " ")} is recorded but not applied; '
            "every finding counts"
        )
        return list(findings), BaselineApplication(
            source=source,
            origin=origin,
            mode=mode,
            applied=False,
            matched=0,
            stale=stale,
            tool_version=tool_version,
            config_digest_matches=config_digest_matches,
            notes=tuple(notes),
        )
    marker = MARKER_IGNORED if mode == LEGACY_IGNORE else MARKER_MATCHED
    marked: list[Finding] = []
    matched = 0
    for finding in findings:
        if finding.fingerprint is not None and finding.fingerprint in known:
            marked.append(finding.with_baseline(marker))
            matched += 1
        else:
            marked.append(finding)
    return marked, BaselineApplication(
        source=source,
        origin=origin,
        mode=mode,
        applied=True,
        matched=matched,
        stale=stale,
        tool_version=tool_version,
        config_digest_matches=config_digest_matches,
        notes=tuple(notes),
    )


def apply_baseline(
    findings: Sequence[Finding], baseline: Baseline, mode: str, config_digest: str
) -> tuple[list[Finding], BaselineApplication]:
    produced = {f.fingerprint for f in findings if f.fingerprint is not None}
    stale = tuple(e for e in baseline.entries if e.fingerprint not in produced)
    return apply_fingerprints(
        findings,
        baseline.fingerprints,
        mode,
        SOURCE_FILE,
        baseline.origin,
        baseline.tool_version,
        baseline.config_digest == config_digest,
        stale,
    )
