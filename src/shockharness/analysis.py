"""Per-file analysis pipeline: read, decode, parse, run rules, apply suppressions.

A file that cannot be read, decoded, or parsed gets an explicit non-``analyzed``
status and zero findings. It is never reported as clean; the gate decides what
that status means (``parse_errors`` = fail or warn).

Since Milestone E the pipeline has two phases. :func:`prepare_file` runs the
per-file rules and measures the file's units; :func:`analyze_files` then builds
the cross-file call graph over every parsed file (``CPLX005`` needs it) and
only after that applies suppressions and assigns fingerprints, so a graph
finding can be suppressed and baselined like any other.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.complexity.assemble import ComplexityOutcome, assemble
from shockharness.complexity.callgraph import ModuleInput
from shockharness.complexity.metrics import UnitMetrics, measure_units
from shockharness.config import EffectiveConfig
from shockharness.discovery import DiscoveredFile
from shockharness.findings import Finding
from shockharness.gating.baseline import assign_fingerprints
from shockharness.globs import compile_globset
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import ModuleFacts, ParseFailure
from shockharness.ir.python import extract_python_facts
from shockharness.rules import registry
from shockharness.rules.complexity import run_unit_rules
from shockharness.rules.defaults import DEFAULT_RULES, run_default_rules
from shockharness.rules.exceptions import run_exception_rules
from shockharness.rules.magic_numbers import run_magic001
from shockharness.source import SourceText
from shockharness.suppressions import apply_suppressions

STATUS_ANALYZED = "analyzed"
STATUS_PARSE_ERROR = "parse_error"
STATUS_DECODE_ERROR = "decode_error"
STATUS_READ_ERROR = "read_error"
FAILURE_STATUSES = frozenset({STATUS_PARSE_ERROR, STATUS_DECODE_ERROR, STATUS_READ_ERROR})

ORIGIN_CONFIG = "config"
ORIGIN_OVERRIDE = "override"
ORIGIN_CONFIGURATION_FILE = "configuration_file"

COMPLEXITY_SECTION = "complexity"
UNIT_RULES = (
    registry.CPLX001,
    registry.CPLX002,
    registry.CPLX003,
    registry.CPLX004,
    registry.CPLX006,
)


@dataclass(frozen=True)
class AnalysisOptions:
    inline_suppressions: bool


@dataclass(frozen=True)
class RuleDisable:
    rule_id: str
    reason: str
    origin: str

    def to_json_dict(self) -> dict[str, str]:
        return {"rule_id": self.rule_id, "reason": self.reason, "origin": self.origin}


@dataclass(frozen=True)
class FileResult:
    path: str
    language: str
    parser: str | None
    status: str
    line_count: int
    rules_applied: tuple[str, ...]
    rules_disabled: tuple[RuleDisable, ...]
    parse_failure: ParseFailure | None
    error: str | None
    findings: tuple[Finding, ...]

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_STATUSES

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "parser": self.parser,
            "status": self.status,
            "line_count": self.line_count,
            "rules_applied": list(self.rules_applied),
            "rules_disabled": [d.to_json_dict() for d in self.rules_disabled],
            "parse_failure": None
            if self.parse_failure is None
            else self.parse_failure.to_json_dict(),
            "error": self.error,
            "finding_count": len(self.findings),
        }


@dataclass(frozen=True)
class PendingFile:
    """A file after the per-file phase, before suppressions and fingerprints.

    ``source``/``facts``/``units`` are ``None`` for a file that failed to read,
    decode or parse; ``findings`` are the per-file rule findings without
    suppression markers.
    """

    path: str
    language: str
    parser: str | None
    status: str
    line_count: int
    rules_applied: tuple[str, ...]
    rules_disabled: tuple[RuleDisable, ...]
    parse_failure: ParseFailure | None
    error: str | None
    source: SourceText | None
    facts: ModuleFacts | None
    units: tuple[UnitMetrics, ...]
    findings: tuple[Finding, ...]

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_STATUSES

    def disabled_ids(self) -> frozenset[str]:
        return frozenset(d.rule_id for d in self.rules_disabled)


@dataclass(frozen=True)
class AnalysisOutcome:
    files: tuple[FileResult, ...]
    metrics: Mapping[str, Any]  # ``complexity`` and ``graph`` sections of metrics


def _disabled_rules(
    relative_path: str, language: str, config: EffectiveConfig
) -> tuple[RuleDisable, ...]:
    disabled: dict[str, RuleDisable] = {}
    rules_config: Mapping[str, Any] = config.values["rules"]
    for rule in registry.implemented_rules():
        if rule.config_section is None:
            continue
        section = config.section(rule.config_section)
        if section["enabled"] is False:
            disabled[rule.rule_id] = RuleDisable(
                rule.rule_id, f"{rule.config_section}.enabled = false", ORIGIN_CONFIG
            )
    magic = rules_config["magic_numbers"]
    if magic["exclude_configuration_files"] is True and registry.MAGIC001.rule_id not in disabled:
        patterns = compile_globset(list(magic["configuration_files"]))
        matched = patterns.first_match(relative_path)
        if matched is not None:
            disabled[registry.MAGIC001.rule_id] = RuleDisable(
                registry.MAGIC001.rule_id,
                f"file matches configuration_files pattern {matched!r}",
                ORIGIN_CONFIGURATION_FILE,
            )
    for index, override in enumerate(config.values["overrides"]):
        paths = compile_globset(list(override["paths"]))
        if not paths.matches(relative_path):
            continue
        for rule_id in override["disable"]:
            if rule_id in disabled:
                continue
            disabled[rule_id] = RuleDisable(rule_id, override["reason"], f"overrides[{index}]")
    return tuple(disabled[key] for key in sorted(disabled))


def _extract(language: str, source: SourceText, filename: str) -> ModuleFacts:
    if language == registry.PYTHON:
        return extract_python_facts(source, filename)
    if language == registry.JAVASCRIPT:
        return extract_javascript_facts(source, filename)
    raise ValueError(f"no parser adapter for language {language!r}")


def _failed(
    relative_path: str,
    language: str,
    parser: str | None,
    status: str,
    line_count: int,
    disabled: tuple[RuleDisable, ...],
    parse_failure: ParseFailure | None,
    error: str | None,
) -> PendingFile:
    return PendingFile(
        path=relative_path,
        language=language,
        parser=parser,
        status=status,
        line_count=line_count,
        rules_applied=(),
        rules_disabled=disabled,
        parse_failure=parse_failure,
        error=error,
        source=None,
        facts=None,
        units=(),
        findings=(),
    )


def prepare_text(
    relative_path: str, language: str, text: str, config: EffectiveConfig
) -> PendingFile:
    """Phase one: parse, run the per-file rules, measure the units."""
    source = SourceText.from_text(text)
    facts = _extract(language, source, relative_path)
    disabled = _disabled_rules(relative_path, language, config)
    disabled_ids = {d.rule_id for d in disabled}

    if facts.parse_failure is not None:
        return _failed(
            relative_path,
            language,
            facts.parser,
            STATUS_PARSE_ERROR,
            source.line_count,
            disabled,
            facts.parse_failure,
            facts.parse_failure.message,
        )

    applied: list[str] = []
    findings: list[Finding] = []
    if registry.MAGIC001.rule_id not in disabled_ids:
        applied.append(registry.MAGIC001.rule_id)
        findings.extend(
            run_magic001(
                facts, source, config.section(str(registry.MAGIC001.config_section)), relative_path
            )
        )

    active_default_rules = frozenset(
        rule.rule_id for rule in DEFAULT_RULES if rule.rule_id not in disabled_ids
    )
    active_exception_rules = frozenset(
        rule.rule_id
        for rule in (registry.EXC001, registry.EXC002, registry.EXC003)
        if rule.rule_id not in disabled_ids
    )
    if len(active_exception_rules) > 0:
        applied.extend(sorted(active_exception_rules))
        findings.extend(
            run_exception_rules(
                facts,
                source,
                config.section(str(registry.EXC001.config_section)),
                relative_path,
                language,
                active_exception_rules,
                registry.DEF005.rule_id in active_default_rules,
            )
        )
    if len(active_default_rules) > 0:
        applied.extend(sorted(active_default_rules))
        findings.extend(
            run_default_rules(
                facts,
                source,
                config.section(str(registry.DEF001.config_section)),
                relative_path,
                language,
                active_default_rules,
            )
        )

    complexity = config.section(COMPLEXITY_SECTION)
    units: tuple[UnitMetrics, ...] = ()
    if complexity["enabled"] is True:
        units = measure_units(relative_path, facts.functions, complexity)
        active_unit_rules = frozenset(
            rule.rule_id for rule in UNIT_RULES if rule.rule_id not in disabled_ids
        )
        if len(active_unit_rules) > 0:
            applied.extend(sorted(active_unit_rules))
            findings.extend(
                run_unit_rules(units, source, complexity, relative_path, active_unit_rules)
            )
        if registry.CPLX005.rule_id not in disabled_ids:
            applied.append(registry.CPLX005.rule_id)

    return PendingFile(
        path=relative_path,
        language=language,
        parser=facts.parser,
        status=STATUS_ANALYZED,
        line_count=source.line_count,
        rules_applied=tuple(applied),
        rules_disabled=disabled,
        parse_failure=None,
        error=None,
        source=source,
        facts=facts,
        units=units,
        findings=tuple(findings),
    )


def _read_source(path: Path) -> tuple[str | None, str | None, str | None]:
    """Return (text, status, error). Exactly one of text / error is set."""
    # Boundary (declared in .shockharness.toml): reading and decoding analyzed files.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, STATUS_READ_ERROR, f"cannot read file: {exc}"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, STATUS_DECODE_ERROR, f"file is not valid UTF-8: {exc}"
    return text, None, None


def prepare_file(file: DiscoveredFile, config: EffectiveConfig) -> PendingFile:
    text, status, error = _read_source(file.path)
    if text is None:
        assert status is not None
        return _failed(
            file.relative,
            file.language,
            None,
            status,
            0,
            _disabled_rules(file.relative, file.language, config),
            None,
            error,
        )
    return prepare_text(file.relative, file.language, text, config)


def finish(pending: PendingFile, extra: Sequence[Finding], options: AnalysisOptions) -> FileResult:
    """Phase three: suppressions (SUPP001/SUPP002), ordering, fingerprints."""
    if pending.failed:
        return FileResult(
            path=pending.path,
            language=pending.language,
            parser=pending.parser,
            status=pending.status,
            line_count=pending.line_count,
            rules_applied=(),
            rules_disabled=pending.rules_disabled,
            parse_failure=pending.parse_failure,
            error=pending.error,
            findings=(),
        )
    assert pending.source is not None and pending.facts is not None
    disabled_ids = pending.disabled_ids()
    applied = list(pending.rules_applied)
    supp001_enabled = registry.SUPP001.rule_id not in disabled_ids
    supp002_enabled = registry.SUPP002.rule_id not in disabled_ids
    if supp001_enabled:
        applied.append(registry.SUPP001.rule_id)
    if supp002_enabled:
        applied.append(registry.SUPP002.rule_id)
    findings = apply_suppressions(
        pending.path,
        [*pending.findings, *extra],
        pending.facts.comments,
        pending.source,
        options.inline_suppressions,
        supp001_enabled,
        supp002_enabled,
    )
    findings.sort(key=lambda f: f.sort_key())
    findings = assign_fingerprints(findings)
    return FileResult(
        path=pending.path,
        language=pending.language,
        parser=pending.parser,
        status=STATUS_ANALYZED,
        line_count=pending.line_count,
        rules_applied=tuple(sorted(applied)),
        rules_disabled=pending.rules_disabled,
        parse_failure=None,
        error=None,
        findings=tuple(findings),
    )


def cross_file(pendings: Sequence[PendingFile], config: EffectiveConfig) -> ComplexityOutcome:
    """Phase two: the call graph over every parsed file, and the CPLX005 findings."""
    modules: list[ModuleInput] = []
    sources: dict[str, SourceText] = {}
    cplx005_paths: set[str] = set()
    for pending in pendings:
        if pending.failed or pending.facts is None or pending.source is None:
            continue
        modules.append(
            ModuleInput(
                path=pending.path,
                language=pending.language,
                units=pending.units,
                imports=pending.facts.imports,
                bindings=pending.facts.bindings,
            )
        )
        sources[pending.path] = pending.source
        if registry.CPLX005.rule_id in pending.rules_applied:
            cplx005_paths.add(pending.path)
    return assemble(modules, sources, config, frozenset(cplx005_paths))


def complete(
    pendings: Sequence[PendingFile], config: EffectiveConfig, options: AnalysisOptions
) -> AnalysisOutcome:
    outcome = cross_file(pendings, config)
    results: list[FileResult] = []
    for pending in pendings:
        extra: Sequence[Finding] = ()
        if pending.path in outcome.graph_findings:
            extra = outcome.graph_findings[pending.path]
        results.append(finish(pending, extra, options))
    return AnalysisOutcome(
        files=tuple(results),
        metrics={"complexity": outcome.complexity, "graph": outcome.graph},
    )


def analyze_files(
    files: Sequence[DiscoveredFile], config: EffectiveConfig, options: AnalysisOptions
) -> AnalysisOutcome:
    """The whole pipeline for a set of discovered files."""
    pendings = [prepare_file(file, config) for file in files]
    return complete(pendings, config, options)


def analyze_text(
    relative_path: str,
    language: str,
    text: str,
    config: EffectiveConfig,
    options: AnalysisOptions,
) -> FileResult:
    """One in-memory file through the whole pipeline (its graph is the file alone)."""
    outcome = complete([prepare_text(relative_path, language, text, config)], config, options)
    return outcome.files[0]


def analyze_file(
    file: DiscoveredFile, config: EffectiveConfig, options: AnalysisOptions
) -> FileResult:
    outcome = complete([prepare_file(file, config)], config, options)
    return outcome.files[0]
