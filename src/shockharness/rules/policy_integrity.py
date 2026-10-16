"""VERIFY003: a change loosening the policy that judges it (H2 part 2).

Two sources of findings:

* **Policy attempts** (any run with ``--policy FILE``): a repository key that would
  loosen a key the organization's policy file sets. The configuration loader keeps the
  policy's value (``config.PolicyAttempt``); this module reports each attempt at the
  repository configuration file. No base revision is needed.
* **Revision comparison** (``diff`` / ``gate --base --head``): a snapshot of each
  revision's committed policy (its ShockHarness configuration, baselines, workflows and
  tool configuration) taken while the revision's tree is exported, and compared:
  every new deviation or otherwise looser setting (``loosening.py``), files the base
  configuration analyzes that the head configuration does not, baselines that gained
  fingerprints, workflow jobs that stopped running or started excusing ShockHarness
  (``workflows.py``), and loosened ruff / flake8 / pytest / coverage / ESLint settings
  (``tool_configs.py``).

Findings are policy_integrity, carry ``rules.verification.severity`` (the strictest of
the run's configuration and the base revision's, so a change cannot lower the severity
of the rule that reports it lowering it), are never suppressible inline, and ignore
per-path ``[[overrides]]``: only ``rules.verification.enabled`` turns the rule off.
"""

import fnmatch
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.config import (
    DEDICATED_FILENAMES,
    PYPROJECT_FILENAME,
    TIER_CLI,
    TIER_DEDICATED,
    TIER_PYPROJECT,
    EffectiveConfig,
    load_config,
)
from shockharness.constants import COMMIT_SHORT_HEX, VERIFY003_LISTED_FILES
from shockharness.discovery import discover
from shockharness.errors import ConfigError
from shockharness.findings import (
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    STATUS_UNKNOWN,
    STATUS_VIOLATION,
    Finding,
)
from shockharness.gating.baseline import assign_fingerprints
from shockharness.ir.model import Span
from shockharness.loosening import loosenings
from shockharness.rules.registry import VERIFY003
from shockharness.rules.tool_configs import TOOL_CONFIG_FILES, read_tool_settings, tool_loosenings
from shockharness.rules.workflows import (
    WORKFLOW_DIRECTORY,
    WORKFLOW_SUFFIXES,
    workflow_loosenings,
)

USER_TIERS = frozenset({TIER_CLI, TIER_DEDICATED, TIER_PYPROJECT})
CONFIG_CANDIDATES = (*DEDICATED_FILENAMES, PYPROJECT_FILENAME)
TOOL_TABLE_PREFIX = "tool.shockharness"
BASELINE_GLOB = "*baseline*.json"
SKIPPED_DIRECTORIES = frozenset(
    {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".shockharness-cache"}
)
TABLE_HEADER = re.compile(r"\[\[?\s*(?P<name>[^\]]+?)\s*\]\]?")
KEY_ASSIGNMENT = re.compile(r"(?P<key>[A-Za-z0-9_\-\"']+)\s*=")
VERIFICATION_SEVERITY_ORDER = ("error", "warning", "review")
FIRST_LINE = 1


@dataclass(frozen=True)
class PolicySnapshot:
    """One revision's committed policy, read while its tree was exported.

    ``texts`` maps root-relative POSIX paths to file text (the configuration file, tool
    configuration files, workflows); ``baselines`` maps baseline files to their
    fingerprint -> rule ID; ``scope_*`` are filled for the head revision only: the files
    the base configuration and the head configuration would analyze in the head tree.
    """

    config: EffectiveConfig | None
    config_error: str | None
    config_file: str | None
    texts: Mapping[str, str]
    workflows_checked: bool
    baselines: Mapping[str, Mapping[str, str]]
    errors: Mapping[str, str]
    scope_under_base: frozenset[str] | None
    scope_under_own: frozenset[str] | None


@dataclass(frozen=True)
class PolicyResult:
    findings: tuple[Finding, ...]  # without fingerprints (see fingerprinted)
    coverage: dict[str, Any]


def read_text(path: Path) -> tuple[str | None, str | None]:
    """(text, error); exactly one is set."""
    # Boundary (declared in .shockharness.toml): reading a file of an exported revision.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read {path.name}: {exc}"
    # Boundary (declared in .shockharness.toml): the file's bytes are external input.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, f"{path.name} is not valid UTF-8: {exc}"
    return text, None


def _load_committed_config(root: Path) -> tuple[EffectiveConfig | None, str | None]:
    """The revision's own ShockHarness configuration (no --config, no --policy)."""
    # Boundary (declared in .shockharness.toml): a committed configuration is external
    # input; an invalid one makes the comparison unknown, never a crash or a pass.
    try:
        config = load_config(root, None)
    except ConfigError as exc:
        return None, str(exc)
    return config, None


def _config_file(root: Path, config: EffectiveConfig | None) -> str | None:
    if config is not None:
        if config.source.tier not in USER_TIERS:
            return None
        source = Path(config.source.path)
        if source.resolve().is_relative_to(root.resolve()):
            return source.resolve().relative_to(root.resolve()).as_posix()
        return None
    for name in CONFIG_CANDIDATES:
        if (root / name).is_file():
            return name
    return None


def _json_document(text: str) -> tuple[Any, str | None]:
    """(document, error); the error is set when ``text`` is not JSON."""
    # Boundary (declared in .shockharness.toml): a JSON file of the analyzed tree.
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"not JSON: {exc}"
    return document, None


def _baseline_fingerprints(text: str) -> dict[str, str] | None:
    """fingerprint -> rule ID when ``text`` is a ShockHarness baseline, else None."""
    document, error = _json_document(text)
    if error is not None or not isinstance(document, dict):
        return None
    if "fingerprint_version" not in document or "fingerprints" not in document:
        return None
    entries = document["fingerprints"]
    if not isinstance(entries, list):
        return None
    found: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "fingerprint" not in entry or "rule_id" not in entry:
            continue
        found[str(entry["fingerprint"])] = str(entry["rule_id"])
    return found


def _text_at(texts: Mapping[str, str], path: str) -> str | None:
    """The text of ``path`` in a snapshot, ``None`` when the revision has no such file."""
    if path in texts:
        return texts[path]
    return None


def _base_path(renames: Mapping[str, str], path: str) -> str:
    """The base revision's path of a head file (git rename detection)."""
    if path in renames:
        return renames[path]
    return path


def _baselines(root: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    baselines: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}
    for current, directories, files in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in SKIPPED_DIRECTORIES)
        for name in sorted(files):
            if not fnmatch.fnmatch(name, BASELINE_GLOB):
                continue
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            text, error = read_text(path)
            if text is None:
                assert error is not None
                errors[relative] = error
                continue
            fingerprints = _baseline_fingerprints(text)
            if fingerprints is not None:
                baselines[relative] = fingerprints
    return baselines, errors


def _read_into(path: Path, relative: str, texts: dict[str, str], errors: dict[str, str]) -> None:
    text, error = read_text(path)
    if text is None:
        assert error is not None
        errors[relative] = error
        return
    texts[relative] = text


def _workflow_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix in WORKFLOW_SUFFIXES
    ]


def _scope(export_root: Path, config: EffectiveConfig) -> frozenset[str]:
    """The files ``config`` analyzes in the exported tree."""
    found = discover(export_root, [export_root], config)
    return frozenset(f.relative for f in found.files)


def take_snapshot(
    export_root: Path,
    toplevel: Path,
    prefix: str,
    base_config: EffectiveConfig | None,
    is_head: bool,
) -> PolicySnapshot:
    """Read one exported revision's policy files (call while the export exists)."""
    config, config_error = _load_committed_config(export_root)
    config_file = _config_file(export_root, config)
    texts: dict[str, str] = {}
    errors: dict[str, str] = {}
    names = list(TOOL_CONFIG_FILES)
    if config_file is not None and config_file not in names:
        names.append(config_file)
    for name in names:
        path = export_root / name
        if path.is_file():
            _read_into(path, name, texts, errors)
    workflows_checked = prefix == ""
    if workflows_checked:
        for path in _workflow_files(toplevel / WORKFLOW_DIRECTORY):
            _read_into(path, f"{WORKFLOW_DIRECTORY}/{path.name}", texts, errors)
    baselines, baseline_errors = _baselines(export_root)
    errors.update(baseline_errors)
    scope_under_base: frozenset[str] | None = None
    scope_under_own: frozenset[str] | None = None
    if is_head and base_config is not None and config is not None:
        scope_under_base = _scope(export_root, base_config)
        scope_under_own = _scope(export_root, config)
    return PolicySnapshot(
        config=config,
        config_error=config_error,
        config_file=config_file,
        texts=texts,
        workflows_checked=workflows_checked,
        baselines=baselines,
        errors=errors,
        scope_under_base=scope_under_base,
        scope_under_own=scope_under_own,
    )


def toml_key_line(text: str, dotted: str) -> int:
    """The line of ``dotted`` (a key under [tool.shockharness]) in a TOML file: its
    assignment, its table header, else the first line mentioning its last part."""
    parts = dotted.split(".")
    leaf = parts[len(parts) - 1]
    table = ".".join([TOOL_TABLE_PREFIX, *parts[: len(parts) - 1]])
    current = ""
    lines = text.splitlines()
    for number, line in enumerate(lines, start=FIRST_LINE):
        stripped = line.strip()
        header = TABLE_HEADER.fullmatch(stripped)
        if header is not None:
            current = header.group("name").replace('"', "").replace(" ", "")
            if current == f"{TOOL_TABLE_PREFIX}.{dotted}":
                return number
            continue
        key = KEY_ASSIGNMENT.match(stripped)
        if key is not None and key.group("key").strip("\"'") == leaf and current == table:
            return number
    return _first_line_mentioning(text, (leaf,))


def _first_line_mentioning(text: str, needles: Sequence[str]) -> int:
    for needle in needles:
        if needle == "":
            continue
        for number, line in enumerate(text.splitlines(), start=FIRST_LINE):
            if needle in line:
                return number
    return FIRST_LINE


def strictest_verification(
    current: Mapping[str, Any], base: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The stricter of the run's ``rules.verification`` and the base revision's: a
    change cannot switch off or lower the rules that report it doing so."""
    if base is None:
        return dict(current)
    severity = min(
        (str(current["severity"]), str(base["severity"])),
        key=VERIFICATION_SEVERITY_ORDER.index,
    )
    return {
        "enabled": any((current["enabled"] is True, base["enabled"] is True)),
        "severity": severity,
        "fail_on_unknown": any(
            (current["fail_on_unknown"] is True, base["fail_on_unknown"] is True)
        ),
        "allowed_skip_reasons": [
            r for r in current["allowed_skip_reasons"] if r in base["allowed_skip_reasons"]
        ],
        "report_narrow_suppressions": any(
            (
                current["report_narrow_suppressions"] is True,
                base["report_narrow_suppressions"] is True,
            )
        ),
    }


def _finding(
    path: str,
    line: int,
    message: str,
    evidence: str,
    scope: str,
    unknown: str | None,
    severity: str,
) -> Finding:
    status, confidence = STATUS_VIOLATION, CONFIDENCE_EXACT
    if unknown is not None:
        status, confidence = STATUS_UNKNOWN, CONFIDENCE_UNRESOLVED
        message = f"{message}; unknown: {unknown}"
    return Finding(
        rule_id=VERIFY003.rule_id,
        rule_version=VERIFY003.version,
        severity=severity,
        path=path,
        span=Span(line, FIRST_LINE, line, FIRST_LINE),
        message=message,
        evidence=evidence,
        confidence=confidence,
        status=status,
        remediation=VERIFY003.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def fingerprinted(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    by_path: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.path not in by_path:
            by_path[finding.path] = []
        by_path[finding.path].append(finding)
    result: list[Finding] = []
    for path in sorted(by_path):
        result.extend(assign_fingerprints(sorted(by_path[path], key=lambda f: f.sort_key())))
    return tuple(result)


def policy_attempt_findings(
    config: EffectiveConfig, root: Path, settings: Mapping[str, Any]
) -> list[Finding]:
    """VERIFY003 for every repository key that tried to loosen a ``--policy`` key."""
    if config.policy is None or len(config.policy_attempts) == 0 or settings["enabled"] is not True:
        return []
    source = Path(config.source.path)
    path = source.name
    if source.resolve().is_relative_to(root.resolve()):
        path = source.resolve().relative_to(root.resolve()).as_posix()
    text, _ = read_text(source)
    policy_name = Path(config.policy.path).name
    findings: list[Finding] = []
    for attempt in config.policy_attempts:
        line = FIRST_LINE
        if text is not None:
            line = toml_key_line(text, attempt.key)
        message = (
            f"{path} sets {attempt.key} = {attempt.attempted_value!r}, looser than the policy "
            f"file {policy_name}'s {attempt.policy_value!r} ({'; '.join(attempt.reasons)}); "
            "the policy's value applies"
        )
        findings.append(
            _finding(
                path,
                line,
                message,
                f"policy: {attempt.key} = {attempt.attempted_value!r}",
                "policy",
                None,
                str(settings["severity"]),
            )
        )
    return findings


def _listed(paths: Sequence[str]) -> str:
    shown = ", ".join(paths[:VERIFY003_LISTED_FILES])
    if len(paths) > VERIFY003_LISTED_FILES:
        shown += f" and {len(paths) - VERIFY003_LISTED_FILES} more"
    return shown


def _config_findings(
    base: PolicySnapshot, head: PolicySnapshot, short: str, severity: str
) -> list[Finding]:
    findings: list[Finding] = []
    anchor = head.config_file
    if anchor is None:
        anchor = base.config_file
    if anchor is None:
        return findings  # neither revision configures ShockHarness: bundled defaults on both
    head_text = _text_at(head.texts, anchor)
    if base.config is None or head.config is None:
        if head_text == _text_at(base.texts, anchor):
            return findings
        findings.append(_unloadable_config(base, head, anchor, short, severity))
        return findings
    for item in loosenings(
        base.config.values, base.config.deviations, head.config.values, head.config.deviations
    ):
        line = FIRST_LINE
        if head_text is not None:
            line = toml_key_line(head_text, item.key)
        findings.append(
            _finding(
                anchor,
                line,
                f"configuration loosened since base {short}: {item.message}",
                item.message,
                "configuration",
                None,
                severity,
            )
        )
    findings.extend(_dropped_files(head, anchor, head_text, severity))
    return findings


def _unloadable_config(
    base: PolicySnapshot, head: PolicySnapshot, anchor: str, short: str, severity: str
) -> Finding:
    side = "base" if base.config is None else "head"
    error = base.config_error if base.config is None else head.config_error
    return _finding(
        anchor,
        FIRST_LINE,
        f"the ShockHarness configuration changed between base {short} and head",
        "configuration changed",
        "configuration",
        f"the {side} configuration could not be loaded ({error}), so whether it was "
        "loosened cannot be established",
        severity,
    )


def _dropped_files(
    head: PolicySnapshot, anchor: str, head_text: str | None, severity: str
) -> list[Finding]:
    """Files the base configuration analyzes in the head tree that the head's does not."""
    if head.scope_under_base is None or head.scope_under_own is None:
        return []
    dropped = sorted(head.scope_under_base - head.scope_under_own)
    if len(dropped) == 0:
        return []
    line = FIRST_LINE
    if head_text is not None:
        line = toml_key_line(head_text, "exclude")
    return [
        _finding(
            anchor,
            line,
            f"{len(dropped)} file(s) the base configuration analyzes are not analyzed "
            f"under the head configuration: {_listed(dropped)}",
            f"{len(dropped)} file(s) dropped from analysis",
            "configuration",
            None,
            severity,
        )
    ]


def _tool_findings(
    base: PolicySnapshot, head: PolicySnapshot, short: str, severity: str
) -> list[Finding]:
    findings: list[Finding] = []
    for name in TOOL_CONFIG_FILES:
        base_text = _text_at(base.texts, name)
        head_text = _text_at(head.texts, name)
        if base_text == head_text or base_text is None:
            continue  # unchanged, or a new file (nothing to have loosened)
        anchor_text = ""  # a deleted file compares as empty: its settings are gone
        if head_text is not None:
            anchor_text = head_text
        before, before_error = read_tool_settings(name, base_text)
        after, after_error = read_tool_settings(name, anchor_text)
        if before is None or after is None:
            findings.append(
                _finding(
                    name,
                    FIRST_LINE,
                    f"{name} changed since base {short}",
                    f"{name} changed",
                    "tool configuration",
                    f"{before_error if before is None else after_error}",
                    severity,
                )
            )
            continue
        for item in tool_loosenings(before, after):
            line = _first_line_mentioning(
                anchor_text,
                (item.item, item.category.split(".")[len(item.category.split(".")) - 1]),
            )
            findings.append(
                _finding(
                    name,
                    line,
                    f"{item.message} in {name} (looser than at base {short})",
                    f"{item.category}: {item.item}",
                    "tool configuration",
                    None,
                    severity,
                )
            )
    return findings


def _workflow_findings(
    base: PolicySnapshot,
    head: PolicySnapshot,
    renames: Mapping[str, str],
    short: str,
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    head_paths = {p for p in head.texts if p.startswith(WORKFLOW_DIRECTORY + "/")}
    base_paths = {p for p in base.texts if p.startswith(WORKFLOW_DIRECTORY + "/")}
    renamed_from = {renames[p] for p in head_paths if p in renames}
    for path in sorted(head_paths | (base_paths - renamed_from)):
        base_text = _text_at(base.texts, _base_path(renames, path))
        head_text = _text_at(head.texts, path)
        if base_text == head_text:
            continue
        for item in workflow_loosenings(base_text, head_text):
            findings.append(
                _finding(
                    path,
                    item.line,
                    f"{item.message} (since base {short})",
                    item.item,
                    "workflow",
                    None,
                    severity,
                )
            )
    return findings


def _baseline_findings(
    base: PolicySnapshot,
    head: PolicySnapshot,
    renames: Mapping[str, str],
    short: str,
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(head.baselines):
        base_path = _base_path(renames, path)
        before: Mapping[str, str] = {}
        if base_path in base.baselines:
            before = base.baselines[base_path]
        after = head.baselines[path]
        added = sorted(set(after) - set(before))
        if len(added) == 0:
            continue
        rules: dict[str, int] = {}
        for fingerprint in added:
            rule = after[fingerprint]
            if rule not in rules:
                rules[rule] = 0
            rules[rule] += 1
        summary = ", ".join(f"{rule}: {count}" for rule, count in sorted(rules.items()))
        findings.append(
            _finding(
                path,
                FIRST_LINE,
                f"baseline {path} gained {len(added)} fingerprint(s) since base {short} "
                f"({summary}); each is a finding that no longer fails the gate",
                f"baseline gained {len(added)} fingerprint(s): {summary}",
                "baseline",
                None,
                severity,
            )
        )
    return findings


def compare_policy(
    base: PolicySnapshot,
    head: PolicySnapshot,
    renames: Mapping[str, str],
    settings: Mapping[str, Any],
    base_commit: str,
) -> PolicyResult:
    """Every VERIFY003 finding of a revision comparison (not yet fingerprinted)."""
    coverage: dict[str, Any] = {
        "configuration": "compared",
        "workflows_checked": head.workflows_checked,
        "files_compared": sorted(set(base.texts) | set(head.texts)),
        "baselines": sorted(set(base.baselines) | set(head.baselines)),
        "read_errors": dict(sorted({**base.errors, **head.errors}.items())),
    }
    if not head.workflows_checked:
        coverage["workflows_note"] = (
            "workflows are checked only when the analysis root is the repository's top level"
        )
    if settings["enabled"] is not True:
        coverage["configuration"] = "disabled"
        return PolicyResult(findings=(), coverage=coverage)
    if base.config is None or head.config is None:
        coverage["configuration"] = "unknown"
    short = base_commit[:COMMIT_SHORT_HEX]
    severity = str(settings["severity"])
    findings = [
        *_config_findings(base, head, short, severity),
        *_tool_findings(base, head, short, severity),
        *_workflow_findings(base, head, renames, short, severity),
        *_baseline_findings(base, head, renames, short, severity),
    ]
    return PolicyResult(findings=tuple(findings), coverage=coverage)
