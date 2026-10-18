"""`shockharness exceptions`: every exception the code and the configuration make, in one
place (0.5.0, docs/shockharness-suggestions-4.md item 7).

Read-only and never gating. It lists:

* inline suppression comments, each with its rule IDs, its reason, and which of its
  rules it actually silences (used) or does not (unused, SUPP002); malformed ones (SUPP001)
  separately;
* every policy deviation of the effective configuration (the same lines the reports
  print), each with where it comes from: the configuration file and line, a profile, the
  ``--policy`` file, or the command line; plus every ``exclude`` pattern the configuration
  sets (the bundled excludes are not listed);
* the ``--policy`` attempts;
* the baseline given with ``--baseline``: entries per rule and per file.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.analysis import FileResult
from shockharness.config import (
    ORIGIN_CLI_OVERRIDE,
    ORIGIN_POLICY,
    TIER_BUNDLED,
    USER_TIERS,
    EffectiveConfig,
)
from shockharness.constants import REPORT_SCHEMA_VERSION
from shockharness.contracts.report import Considered
from shockharness.gating.baseline import Baseline
from shockharness.loosening import EXCLUDE_KEY, deviation_key
from shockharness.report import Report
from shockharness.rules.policy_integrity import FIRST_LINE, TOOL_TABLE_PREFIX, toml_key_line
from shockharness.rules.registry import SUPP001
from shockharness.version import __version__

REPORT_KIND = "exceptions"
ORIGIN_COMMAND_LINE = "command line"
FIRST_INDEX = re.compile(r"\[(\d+)\]")
ARRAY_HEADER = re.compile(r"\[\[\s*(?P<name>[^\]]+?)\s*\]\]")


@dataclass(frozen=True)
class SuppressionEntry:
    path: str
    line: int
    rules: tuple[str, ...]
    reason: str
    used: tuple[str, ...]
    unused: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "rules": list(self.rules),
            "reason": self.reason,
            "used": list(self.used),
            "unused": list(self.unused),
        }


@dataclass(frozen=True)
class InvalidSuppression:
    path: str
    line: int
    message: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "message": self.message}


@dataclass(frozen=True)
class ConfigurationEntry:
    """``origin`` is a configuration tier (``dedicated``, ``pyproject``, ``cli``), a
    profile (``profile:recommended``), ``policy`` or ``command line``; ``path`` and
    ``line`` locate it when it comes from a file."""

    key: str
    text: str
    origin: str
    path: str | None
    line: int | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "text": self.text,
            "origin": self.origin,
            "path": self.path,
            "line": self.line,
        }


@dataclass(frozen=True)
class BaselineSummary:
    path: str
    entries: int
    by_rule: Mapping[str, int]
    by_path: Mapping[str, int]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "entries": self.entries,
            "by_rule": dict(sorted(self.by_rule.items())),
            "by_path": dict(sorted(self.by_path.items())),
        }


@dataclass(frozen=True)
class Inventory:
    config: EffectiveConfig
    source_path: str  # the configuration source, relative to the root when inside it
    suppressions: tuple[SuppressionEntry, ...]
    invalid: tuple[InvalidSuppression, ...]
    configuration: tuple[ConfigurationEntry, ...]
    attempts: tuple[ConfigurationEntry, ...]
    baseline: BaselineSummary | None
    considered: tuple[Considered, ...]  # no-property requires(x) under complete (§9)

    def summary(self) -> dict[str, int]:
        baseline_entries = 0
        if self.baseline is not None:
            baseline_entries = self.baseline.entries
        return {
            "suppressions": len(self.suppressions),
            "unused_suppressions": sum(1 for s in self.suppressions if len(s.unused) > 0),
            "invalid_suppressions": len(self.invalid),
            "configuration": len(self.configuration),
            "policy_attempts": len(self.attempts),
            "baseline_entries": baseline_entries,
            "no_property_requires": len(self.considered),
        }

    def to_json_dict(self) -> dict[str, Any]:
        baseline = None
        if self.baseline is not None:
            baseline = self.baseline.to_json_dict()
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool_version": __version__,
            "report_kind": REPORT_KIND,
            "effective_profile": self.config.values["profile"],
            "config_digest": self.config.digest,
            "config_source": {"tier": self.config.source.tier, "path": self.source_path},
            "summary": self.summary(),
            "suppressions": [s.to_json_dict() for s in self.suppressions],
            "invalid_suppressions": [s.to_json_dict() for s in self.invalid],
            "configuration": [c.to_json_dict() for c in self.configuration],
            "policy_attempts": [a.to_json_dict() for a in self.attempts],
            "baseline": baseline,
            "no_property_requires": [c.to_json_dict() for c in self.considered],
        }


def _silenced(file: FileResult) -> dict[int, set[str]]:
    """Suppression comment line -> the rules it actually silences in ``file``."""
    silenced: dict[int, set[str]] = {}
    for finding in file.findings:
        if finding.suppression is None:
            continue
        line = finding.suppression.line
        if line not in silenced:
            silenced[line] = set()
        silenced[line].add(finding.rule_id)
    return silenced


def _file_suppressions(file: FileResult) -> list[SuppressionEntry]:
    silenced = _silenced(file)
    entries: list[SuppressionEntry] = []
    for suppression in file.suppressions:
        line = suppression.span.line
        used: set[str] = set()
        if line in silenced:
            used = silenced[line] & set(suppression.rule_ids)
        entries.append(
            SuppressionEntry(
                path=file.path,
                line=line,
                rules=suppression.rule_ids,
                reason=suppression.reason,
                used=tuple(sorted(used)),
                unused=tuple(r for r in suppression.rule_ids if r not in used),
            )
        )
    return entries


def _suppressions(report: Report) -> tuple[list[SuppressionEntry], list[InvalidSuppression]]:
    entries: list[SuppressionEntry] = []
    invalid: list[InvalidSuppression] = []
    for file in report.files:
        entries.extend(_file_suppressions(file))
        invalid.extend(
            InvalidSuppression(file.path, finding.span.line, finding.message)
            for finding in file.findings
            if finding.rule_id == SUPP001.rule_id
        )
    entries.sort(key=lambda e: (e.path, e.line))
    invalid.sort(key=lambda e: (e.path, e.line, e.message))
    return entries, invalid


def _origin(origins: Mapping[str, str], key: str) -> str:
    """The origin of ``key``, else of its closest recorded ancestor, else (a table such as
    ``rules.magic_numbers`` in "rules.magic_numbers is disabled") the origin of the keys
    under it, preferring one that is not the bundled defaults."""
    parts = key.split(".")
    while len(parts) > 0:
        dotted = ".".join(parts)
        if dotted in origins:
            return origins[dotted]
        parts = parts[: len(parts) - 1]
    below = sorted({origin for name, origin in origins.items() if name.startswith(key + ".")})
    configured = [origin for origin in below if origin != TIER_BUNDLED]
    if len(configured) > 0:
        return configured[0]
    return TIER_BUNDLED


def _array_entry_line(text: str, key: str, index: int) -> int | None:
    """The line of the ``index``-th ``[[tool.shockharness.<key>]]`` header, if written so."""
    wanted = f"{TOOL_TABLE_PREFIX}.{key}"
    seen = 0
    for number, line in enumerate(text.splitlines(), start=FIRST_LINE):
        header = ARRAY_HEADER.fullmatch(line.strip())
        if header is None or header.group("name").replace(" ", "") != wanted:
            continue
        if seen == index:
            return number
        seen += 1
    return None


@dataclass(frozen=True)
class _Source:
    """A configuration file the inventory points into: its displayed path and text."""

    path: str
    text: str | None


def _key_line(source: _Source, key: str, deviation: str) -> int | None:
    if source.text is None:
        return None
    match = FIRST_INDEX.search(deviation)
    if match is not None and deviation.startswith(key):
        entry = _array_entry_line(source.text, key, int(match.group(1)))
        if entry is not None:
            return entry
    return toml_key_line(source.text, key)


def _locate(
    origin: str, key: str, deviation: str, repository: _Source, policy: _Source | None
) -> tuple[str | None, int | None]:
    if origin in USER_TIERS:
        return repository.path, _key_line(repository, key, deviation)
    if origin == ORIGIN_POLICY and policy is not None:
        return policy.path, _key_line(policy, key, deviation)
    return None, None


def _display_origin(origin: str) -> str:
    if origin == ORIGIN_CLI_OVERRIDE:
        return ORIGIN_COMMAND_LINE
    return origin


def _configuration(
    config: EffectiveConfig, repository: _Source, policy: _Source | None
) -> list[ConfigurationEntry]:
    entries: list[ConfigurationEntry] = []
    for deviation in config.deviations:
        key = deviation_key(deviation)
        origin = _origin(config.origins, key)
        path, line = _locate(origin, key, deviation, repository, policy)
        entries.append(ConfigurationEntry(key, deviation, _display_origin(origin), path, line))
    exclude_origin = _origin(config.origins, EXCLUDE_KEY)
    if exclude_origin in USER_TIERS or exclude_origin == ORIGIN_POLICY:
        for pattern in config.values[EXCLUDE_KEY]:
            text = f"exclude drops {pattern!r} from analysis"
            path, line = _locate(exclude_origin, EXCLUDE_KEY, text, repository, policy)
            entries.append(ConfigurationEntry(EXCLUDE_KEY, text, exclude_origin, path, line))
    return entries


def _attempts(config: EffectiveConfig, repository: _Source) -> list[ConfigurationEntry]:
    entries: list[ConfigurationEntry] = []
    for attempt in config.policy_attempts:
        text = (
            f"{attempt.key} = {attempt.attempted_value!r} would loosen the policy's "
            f"{attempt.policy_value!r} ({'; '.join(attempt.reasons)}); the policy's value applies"
        )
        line = None
        if repository.text is not None:
            line = toml_key_line(repository.text, attempt.key)
        entries.append(
            ConfigurationEntry(attempt.key, text, config.source.tier, repository.path, line)
        )
    return entries


def _baseline(baseline: Baseline, path: str) -> BaselineSummary:
    by_rule: dict[str, int] = {}
    by_path: dict[str, int] = {}
    for entry in baseline.entries:
        if entry.rule_id not in by_rule:
            by_rule[entry.rule_id] = 0
        by_rule[entry.rule_id] += 1
        if entry.path not in by_path:
            by_path[entry.path] = 0
        by_path[entry.path] += 1
    return BaselineSummary(path, len(baseline.entries), by_rule, by_path)


def _display_path(path: str, root: Path) -> str:
    resolved = Path(path).resolve()
    if resolved.is_relative_to(root.resolve()):
        return resolved.relative_to(root.resolve()).as_posix()
    return path


def build_inventory(
    report: Report,
    config: EffectiveConfig,
    root: Path,
    texts: Mapping[str, str | None],
    baseline: tuple[Baseline, str] | None,
    considered: tuple[Considered, ...],
) -> Inventory:
    """``texts`` maps the configuration source path and the policy path (as the config
    names them) to their text, ``None`` when there is none to point into."""
    suppressions, invalid = _suppressions(report)
    repository = _Source(_display_path(config.source.path, root), None)
    if config.source.path in texts:
        repository = _Source(repository.path, texts[config.source.path])
    policy: _Source | None = None
    if config.policy is not None and config.policy.path in texts:
        policy = _Source(config.policy.path, texts[config.policy.path])
    summary: BaselineSummary | None = None
    if baseline is not None:
        summary = _baseline(baseline[0], _display_path(baseline[1], root))
    return Inventory(
        config=config,
        source_path=repository.path,
        suppressions=tuple(suppressions),
        invalid=tuple(invalid),
        configuration=tuple(_configuration(config, repository, policy)),
        attempts=tuple(_attempts(config, repository)),
        baseline=summary,
        considered=considered,
    )


def _where(entry: ConfigurationEntry) -> str:
    if entry.path is None:
        return entry.origin
    if entry.line is None:
        return entry.path
    return f"{entry.path}:{entry.line}"


def _counted(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))


def render_text(inventory: Inventory, root: Path) -> str:
    summary = inventory.summary()
    lines = [
        f"exceptions under {root}: {summary['suppressions']} inline suppression(s) "
        f"({summary['unused_suppressions']} with unused rules, "
        f"{summary['invalid_suppressions']} invalid), {summary['configuration']} "
        f"configuration exception(s), {summary['policy_attempts']} policy attempt(s), "
        f"{summary['baseline_entries']} baseline entr(ies)"
    ]
    if len(inventory.considered) > 0:
        lines[0] += f", {len(inventory.considered)} no-property requires (the sorry count)"
    _section(
        lines,
        "inline suppressions",
        [
            f"{s.path}:{s.line}  {', '.join(s.rules)}  reason: {s.reason}"
            + (f"  [unused: {', '.join(s.unused)}]" if len(s.unused) > 0 else "")
            for s in inventory.suppressions
        ],
    )
    _section(
        lines,
        "invalid suppression comments (SUPP001)",
        [f"{s.path}:{s.line}  {s.message}" for s in inventory.invalid],
    )
    _section(
        lines,
        "configuration",
        [f"{_where(c)}  {c.text}" for c in inventory.configuration],
    )
    _section(lines, "policy attempts", [f"{_where(a)}  {a.text}" for a in inventory.attempts])
    _section(
        lines,
        "no-property requires under complete (the sorry count)",
        [f"{c.path}:{c.line}  {c.text}" for c in inventory.considered],
    )
    if inventory.baseline is not None:
        baseline = inventory.baseline
        _section(
            lines,
            f"baseline {baseline.path}",
            [
                f"{baseline.entries} entr(ies)",
                f"by rule: {_counted(baseline.by_rule)}",
                f"by file: {_counted(baseline.by_path)}",
            ],
        )
    return "\n".join(lines) + "\n"


def _section(lines: list[str], title: str, items: Sequence[str]) -> None:
    if len(items) == 0:
        return
    lines.append("")
    lines.append(f"{title}:")
    lines.extend(f"  {item}" for item in items)
