"""Per-file analysis pipeline: read, decode, parse, run rules, apply suppressions.

A file that cannot be read, decoded, or parsed gets an explicit non-``analyzed``
status and zero findings. It is never reported as clean; the gate decides what
that status means (``parse_errors`` = fail or warn).

Since Milestone E the pipeline has two phases. :func:`prepare_file` runs the
per-file rules and measures the file's units; :func:`analyze_files` then builds
the cross-file call graph over every parsed file (``CPLX005`` needs it) and
only after that applies suppressions and assigns fingerprints, so a graph
finding can be suppressed and baselined like any other.

Every file, analyzed or failed, carries its role (H1, :mod:`shockharness.roles`).
The role scopes ``[[overrides]]`` entries written with ``roles = [...]`` and the
MAGIC001 configuration-file exemption; it never decides whether a file is analyzed.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from shockharness.cache.codec import from_plain, to_plain
from shockharness.cache.contracts import (
    ContractsResult,
    FileEntry,
    decode_contracts,
    encode_contracts,
    entries_by_path,
)
from shockharness.cache.store import FileCache
from shockharness.complexity.assemble import ComplexityOutcome, assemble
from shockharness.complexity.callgraph import (
    CONFIDENCE_RESOLVED,
    CallGraph,
    ModuleInput,
    build_call_graph,
)
from shockharness.complexity.metrics import UnitMetrics, measure_units
from shockharness.config import (
    UNSUPPORTED_FAIL,
    UNSUPPORTED_SOURCES_KEY,
    EffectiveConfig,
    is_opt_in,
    switched_off,
)
from shockharness.contracts.catalog import complete_scope
from shockharness.contracts.deps import Deps, no_deps
from shockharness.contracts.disk import new_log, text_digest
from shockharness.contracts.incremental import Current, current_of, entry_for, reusable
from shockharness.contracts.report import ContractFile
from shockharness.discovery import DiscoveredFile, DiscoveryResult, discover
from shockharness.findings import Finding
from shockharness.gating.baseline import assign_fingerprints
from shockharness.globs import compile_globset
from shockharness.ir.javascript import extract_javascript_facts, extract_typescript_facts
from shockharness.ir.model import (
    NO_VERIFICATION,
    UNIT_CLASS,
    UNIT_METHOD,
    CatchFact,
    ModuleFacts,
    ParseFailure,
)
from shockharness.ir.python import extract_python_facts
from shockharness.roles import FILE_ROLES_KEY, ROLE_CONFIG, ROLE_TEST, FileRole, role_classifier
from shockharness.rules import registry
from shockharness.rules.api_catalog import (
    CATALOG_RULES,
    PredicateFile,
    run_catalog_rules,
    run_stub003,
)
from shockharness.rules.async_lifecycle import ASYNC_RULES, run_async_rules
from shockharness.rules.complexity import run_unit_rules
from shockharness.rules.consistency import run_guard001, run_prov001
from shockharness.rules.dataflow import (
    INPUT_RULES,
    FlowFile,
    run_assert001,
    run_assert002,
    run_input001,
    run_input002,
)
from shockharness.rules.dead_code import DeadFile, run_dead_code
from shockharness.rules.defaults import (
    DEFAULT_RULES,
    EntryExits,
    run_default_rules,
    script_functions,
)
from shockharness.rules.exceptions import (
    applicable_boundaries,
    manager_catches,
    run_exception_rules,
)
from shockharness.rules.floating import FloatingFile, run_dom002
from shockharness.rules.guardrails import GUARDRAIL_RULES, run_guardrail_rules
from shockharness.rules.magic_numbers import run_magic001, run_magic004, run_magic005
from shockharness.rules.property_contracts import property_contract_findings
from shockharness.rules.registry import (
    CATALOG_SECTIONS,
    CONTRACT_RULES,
    DATAFLOW_SECTIONS,
    GUARDRAIL_SECTIONS,
    SENTINEL_SECTIONS,
    STRING_SECTIONS,
)
from shockharness.rules.role_integrity import RoleFile, run_role_integrity
from shockharness.rules.sentinels import run_magic003
from shockharness.rules.strings import StringFile, run_magic002
from shockharness.rules.type_coverage import TypedFile, run_type002
from shockharness.rules.verification import FileVerification
from shockharness.source import SourceText
from shockharness.suppressions import Suppression, apply_suppressions, parse_suppressions

EXCEPTIONS_SECTION = "rules.exceptions"
STATUS_ANALYZED = "analyzed"
STATUS_PARSE_ERROR = "parse_error"
STATUS_DECODE_ERROR = "decode_error"
STATUS_READ_ERROR = "read_error"
STATUS_UNSUPPORTED = "unsupported_source"  # only under unsupported_sources = "fail"
LANGUAGE_UNSUPPORTED = "unsupported"
FAILURE_STATUSES = frozenset(
    {STATUS_PARSE_ERROR, STATUS_DECODE_ERROR, STATUS_READ_ERROR, STATUS_UNSUPPORTED}
)

ORIGIN_CONFIG = "config"
ORIGIN_OVERRIDE = "override"
ORIGIN_CONFIGURATION_FILE = "configuration_file"
ORIGIN_SCRIPT = "script"
SHEBANG = "#!"
FIRST_LINE_NUMBER = 1

COMPLEXITY_SECTION = "complexity"
UNIT_RULES = (
    registry.CPLX001,
    registry.CPLX002,
    registry.CPLX003,
    registry.CPLX004,
    registry.CPLX006,
)


# How a run treats the content-hash cache (0.3.0): honour ``cache.enabled`` and
# ``cache.directory``, or bypass reading and writing for this run (``--no-cache``).
CACHE_CONFIGURED = "configured"
CACHE_BYPASSED = "bypassed"


@dataclass(frozen=True)
class AnalysisOptions:
    inline_suppressions: bool
    cache: str  # CACHE_CONFIGURED | CACHE_BYPASSED


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
    role: str
    role_pattern: str | None
    parser: str | None
    status: str
    line_count: int
    rules_applied: tuple[str, ...]
    rules_disabled: tuple[RuleDisable, ...]
    parse_failure: ParseFailure | None
    error: str | None
    findings: tuple[Finding, ...]
    # The file's inline suppression comments (well-formed ones), for `shockharness
    # exceptions`; not part of the JSON report, which lists suppressions on findings.
    suppressions: tuple[Suppression, ...]

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_STATUSES

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "role": self.role,
            "role_pattern": self.role_pattern,
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
    role: str
    role_pattern: str | None
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
    # Per-file verification facts (H2), for a revision diff to compare; a plain check
    # does not use them.
    verification: Mapping[str, FileVerification]
    # Every catch of each parsed file (clauses and capture managers, as EXC001 sees
    # them), for EXC005's question whether a declared boundary is used.
    catches: Mapping[str, tuple[CatchFact, ...]]


def file_role(relative_path: str, config: EffectiveConfig) -> FileRole:
    """The role of a file: the first role whose ``file_roles`` globs match, else production."""
    return role_classifier(config.values[FILE_ROLES_KEY]).classify(relative_path)


def _configuration_exemption(relative_path: str, role: FileRole, config: EffectiveConfig) -> str:
    """The MAGIC001 exemption reason, or ``""`` when the config role's globs do not match.

    A file whose role is config is exempt. So is a generated or vendor file that a config
    glob also matches: it was exempt in 0.3.0, before roles existed, and stays exempt.
    """
    if role.role == ROLE_CONFIG:
        assert role.pattern is not None
        return f"file role is config (pattern {role.pattern!r}; exclude_configuration_files = true)"
    classifier = role_classifier(config.values[FILE_ROLES_KEY])
    matched = classifier.pattern_of(ROLE_CONFIG, relative_path)
    if matched is None:
        return ""
    return (
        f"file matches config role pattern {matched!r} (its role is {role.role}, which takes "
        "precedence; exclude_configuration_files = true)"
    )


def _override_applies(override: Mapping[str, Any], relative_path: str, role: FileRole) -> bool:
    if "roles" in override:
        return role.role in override["roles"]
    return compile_globset(list(override["paths"])).matches(relative_path)


def _disabled_rules(
    relative_path: str, role: FileRole, config: EffectiveConfig
) -> tuple[RuleDisable, ...]:
    disabled: dict[str, RuleDisable] = {}
    rules_config: Mapping[str, Any] = config.values["rules"]
    for rule in registry.implemented_rules():
        if switched_off(config.values, rule.config_section):
            disabled[rule.rule_id] = RuleDisable(
                rule.rule_id, f"{rule.config_section}.enabled = false", ORIGIN_CONFIG
            )
    magic = rules_config["magic_numbers"]
    if magic["exclude_configuration_files"] is True and registry.MAGIC001.rule_id not in disabled:
        reason = _configuration_exemption(relative_path, role, config)
        if reason != "":
            disabled[registry.MAGIC001.rule_id] = RuleDisable(
                registry.MAGIC001.rule_id, reason, ORIGIN_CONFIGURATION_FILE
            )
    for index, override in enumerate(config.values["overrides"]):
        if not _override_applies(override, relative_path, role):
            continue
        for rule_id in override["disable"]:
            if rule_id in disabled:
                continue
            disabled[rule_id] = RuleDisable(rule_id, override["reason"], f"overrides[{index}]")
    return tuple(disabled[key] for key in sorted(disabled))


def _script_disable(
    source: SourceText, disabled: tuple[RuleDisable, ...]
) -> tuple[RuleDisable, ...]:
    """IMPORT001 does not apply to a script run directly: its first line is a shebang."""
    if any(d.rule_id == registry.IMPORT001.rule_id for d in disabled):
        return disabled
    if not source.line_text(FIRST_LINE_NUMBER).startswith(SHEBANG):
        return disabled
    reason = "a script run directly (#! on line 1) does its work at the top level"
    return (*disabled, RuleDisable(registry.IMPORT001.rule_id, reason, ORIGIN_SCRIPT))


def _unimported_scripts(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph
) -> list[PendingFile]:
    """IMPORT001 does not apply to a file rules.import_effects.script_files matches that
    no other analyzed file imports (through a resolved module edge)."""
    globs = config.section(registry.IMPORT_EFFECTS_SECTION)["script_files"]
    scripts = compile_globset([str(g) for g in globs])
    imported = {
        edge.target
        for edge in graph.module_edges
        if edge.confidence == CONFIDENCE_RESOLVED
        and edge.target is not None
        and edge.target != edge.source
    }
    updated: list[PendingFile] = []
    for pending in pendings:
        exempt = (
            registry.IMPORT001.rule_id in pending.rules_applied
            and scripts.matches(pending.path)
            and pending.path not in imported
        )
        updated.append(_without_import001(pending) if exempt else pending)
    return updated


def _without_import001(pending: PendingFile) -> PendingFile:
    rule = registry.IMPORT001.rule_id
    reason = "a script (rules.import_effects.script_files) that no analyzed file imports"
    return replace(
        pending,
        rules_applied=tuple(r for r in pending.rules_applied if r != rule),
        rules_disabled=(*pending.rules_disabled, RuleDisable(rule, reason, ORIGIN_SCRIPT)),
        findings=tuple(f for f in pending.findings if f.rule_id != rule),
    )


def _in_scope(rule: registry.RuleSpec, role: FileRole, config: EffectiveConfig) -> bool:
    """H3: a role-scoped rule applies to the roles its section lists. Like the VERIFY role
    scopes, a rule outside its roles is not applied to the file (and not listed as disabled)."""
    section = rule.config_section
    if rule is registry.PROP005:
        # The test bootstrap's enable(...) lives in test code (conftest.py is config by
        # default), whatever the family's roles say.
        return role.role in (ROLE_TEST, ROLE_CONFIG)
    if section is None or section not in (
        *GUARDRAIL_SECTIONS,
        *CATALOG_SECTIONS,
        *DATAFLOW_SECTIONS,
        *SENTINEL_SECTIONS,
        *STRING_SECTIONS,
        registry.PROPERTY_CONTRACTS_SECTION,
        registry.DEAD_CODE_SECTION,
    ):
        return True
    return role.role in config.section(section)["roles"]


def _active_guardrails(
    language: str, role: FileRole, config: EffectiveConfig, disabled_ids: set[str]
) -> frozenset[str]:
    return frozenset(
        rule.rule_id
        for rule in GUARDRAIL_RULES
        if rule.rule_id not in disabled_ids
        and language in rule.languages
        and _in_scope(rule, role, config)
    )


def _units(
    relative_path: str, facts: ModuleFacts, config: EffectiveConfig, applied: list[str]
) -> tuple[UnitMetrics, ...]:
    """ASYNC001 resolves callees through the call graph, which is built from the units, so
    they are measured for it even when complexity is disabled (and then not reported).
    The dead-code rules need every file's units, test files' too (they are its roots)."""
    complexity = config.section(COMPLEXITY_SECTION)
    graph_rules = (
        registry.ASYNC001.rule_id,
        registry.INPUT001.rule_id,
        registry.ASSERT001.rule_id,
        registry.PROV001.rule_id,
        registry.GUARD001.rule_id,
    )
    if (
        complexity["enabled"] is True
        or any(rule in applied for rule in graph_rules)
        or config.section(registry.DEAD_CODE_SECTION)["enabled"] is True
    ):
        return measure_units(relative_path, facts.functions, complexity)
    return ()


DEAD_RULES = (registry.DEAD001, registry.DEAD002)
# A runtime module given as a project path, not a module name (rules.property_contracts).
RUNTIME_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts")
# The rules recorded as applied by role and scope; most find in the cross-file phase.
SCOPED_RULES = (
    *CATALOG_RULES,
    registry.TYPE002,
    *INPUT_RULES,
    registry.PROV001,
    registry.GUARD001,
    registry.MAGIC003,
    registry.MAGIC002,
    registry.DOM002,
    *CONTRACT_RULES,
    *DEAD_RULES,
)


def _policy_rules(
    facts: ModuleFacts,
    source: SourceText,
    config: EffectiveConfig,
    relative_path: str,
    language: str,
    role: FileRole,
    disabled_ids: set[str],
) -> tuple[list[str], list[Finding]]:
    """The H3-H6 rules for one file: (rule IDs applied, findings). ASYNC001-ASYNC003 and
    INPUT001 run in the cross-file phase (they need the call graph); here they are only
    recorded as applied when they apply to the file, and so is ROLE001."""
    rules = config.values["rules"]
    guardrails = _active_guardrails(language, role, config, disabled_ids)
    catalog = frozenset(
        rule.rule_id
        for rule in SCOPED_RULES
        if rule.rule_id not in disabled_ids
        and language in rule.languages
        and _in_scope(rule, role, config)
        and _opted_in(rule, config)
    )
    applied = [
        *sorted(guardrails),
        *sorted(catalog),
        *sorted(_active_async(language, role, config, disabled_ids)),
    ]
    if registry.ROLE001.rule_id not in disabled_ids:
        applied.append(registry.ROLE001.rule_id)  # findings come from the cross-file phase
    findings = [
        *run_guardrail_rules(facts, source, rules, relative_path, language, guardrails),
        *run_catalog_rules(facts, source, rules, relative_path, language, catalog),
    ]
    if registry.INPUT002.rule_id in catalog:
        findings.extend(run_input002(facts, source, relative_path, language, rules["input"]))
    if registry.MAGIC003.rule_id in catalog:
        magic = rules["magic_numbers"]
        findings.extend(
            run_magic003(facts, source, relative_path, language, rules["sentinels"], magic)
        )
    return applied, findings


def _opted_in(rule: registry.RuleSpec, config: EffectiveConfig) -> bool:
    """An opt-in family's rules apply only once the repository turns it on."""
    section = rule.config_section
    return section is None or not is_opt_in(section) or config.section(section)["enabled"] is True


def _active_async(
    language: str, role: FileRole, config: EffectiveConfig, disabled_ids: set[str]
) -> frozenset[str]:
    roles = config.section(registry.ASYNC_SECTION)["roles"]
    return frozenset(
        rule.rule_id
        for rule in ASYNC_RULES
        if rule.rule_id not in disabled_ids and language in rule.languages and role.role in roles
    )


def _extract(language: str, source: SourceText, filename: str) -> ModuleFacts:
    if language == registry.PYTHON:
        return extract_python_facts(source, filename)
    if language == registry.JAVASCRIPT:
        return extract_javascript_facts(source, filename)
    if language == registry.TYPESCRIPT:
        return extract_typescript_facts(source, filename)
    raise ValueError(f"no parser adapter for language {language!r}")


def _failed(
    relative_path: str,
    language: str,
    role: FileRole,
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
        role=role.role,
        role_pattern=role.pattern,
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


def _default_rules(
    facts: ModuleFacts,
    source: SourceText,
    config: EffectiveConfig,
    relative_path: str,
    language: str,
    active: frozenset[str],
) -> list[Finding]:
    """DEF001-DEF006, with what DEF005 needs to accept an entry point's exit status."""
    entries = EntryExits(
        applicable_boundaries(config.section(EXCEPTIONS_SECTION), language, relative_path),
        script_functions(config.entry_points, relative_path),
    )
    settings = config.section(str(registry.DEF001.config_section))
    return run_default_rules(facts, source, settings, relative_path, language, active, entries)


def _magic_rules(
    facts: ModuleFacts,
    source: SourceText,
    config: EffectiveConfig,
    relative_path: str,
    disabled_ids: set[str],
) -> tuple[list[str], list[Finding]]:
    """MAGIC001, MAGIC004 and MAGIC005 (all read rules.magic_numbers): applied IDs and
    findings. MAGIC005 applies only where MAGIC001 does: it is MAGIC001 spelled otherwise."""
    settings = config.section(str(registry.MAGIC001.config_section))
    applied: list[str] = []
    findings: list[Finding] = []
    if registry.MAGIC001.rule_id not in disabled_ids:
        applied.append(registry.MAGIC001.rule_id)
        findings.extend(run_magic001(facts, source, settings, relative_path))
    if registry.MAGIC004.rule_id not in disabled_ids:
        applied.append(registry.MAGIC004.rule_id)
        findings.extend(run_magic004(facts, source, settings, relative_path))
    magic005 = registry.MAGIC005.rule_id
    if registry.MAGIC001.rule_id not in disabled_ids and magic005 not in disabled_ids:
        applied.append(magic005)
        findings.extend(run_magic005(facts, source, settings, relative_path))
    return applied, findings


def prepare_text(
    relative_path: str, language: str, text: str, config: EffectiveConfig
) -> PendingFile:
    """Phase one: parse, run the per-file rules, measure the units."""
    source = SourceText.from_text(text)
    facts = _extract(language, source, relative_path)
    role = file_role(relative_path, config)
    disabled = _script_disable(source, _disabled_rules(relative_path, role, config))
    disabled_ids = {d.rule_id for d in disabled}

    if facts.parse_failure is not None:
        return _failed(
            relative_path,
            language,
            role,
            facts.parser,
            STATUS_PARSE_ERROR,
            source.line_count,
            disabled,
            facts.parse_failure,
            facts.parse_failure.message,
        )

    applied, findings = _magic_rules(facts, source, config, relative_path, disabled_ids)

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
            _default_rules(facts, source, config, relative_path, language, active_default_rules)
        )

    policy_applied, policy_findings = _policy_rules(
        facts, source, config, relative_path, language, role, disabled_ids
    )
    applied.extend(policy_applied)
    findings.extend(policy_findings)

    complexity = config.section(COMPLEXITY_SECTION)
    units = _units(relative_path, facts, config, applied)
    if complexity["enabled"] is True:
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
        role=role.role,
        role_pattern=role.pattern,
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


def _read_source(path: Path) -> tuple[bytes | None, str | None, str | None, str | None]:
    """Return (bytes, text, status, error). Either text or error is set; bytes are set
    whenever the file could be read (a decode failure still has them)."""
    # Boundary (declared in .shockharness.toml): reading and decoding analyzed files.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, None, STATUS_READ_ERROR, f"cannot read file: {exc}"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return raw, None, STATUS_DECODE_ERROR, f"file is not valid UTF-8: {exc}"
    return raw, text, None, None


def pending_to_plain(pending: PendingFile) -> Any:
    """The cache entry of a prepared file: everything but the source text, which the
    warm run reads again (it has to hash the bytes anyway)."""
    return to_plain(replace(pending, source=None))


def pending_from_plain(data: Any) -> PendingFile:
    pending = from_plain(PendingFile, data, "pending")
    assert isinstance(pending, PendingFile)
    return pending


def prepare_file(
    file: DiscoveredFile, config: EffectiveConfig, cache: FileCache | None
) -> PendingFile:
    """Phase one for a file on disk, served from ``cache`` when its key matches."""
    raw, text, status, error = _read_source(file.path)
    if text is None:
        assert status is not None
        role = file_role(file.relative, config)
        return _failed(
            file.relative,
            file.language,
            role,
            None,
            status,
            0,
            _disabled_rules(file.relative, role, config),
            None,
            error,
        )
    assert raw is not None
    if cache is None:
        return prepare_text(file.relative, file.language, text, config)
    cached = cache.lookup(file.relative, file.language, raw, pending_from_plain)
    if cached is not None:
        assert isinstance(cached, PendingFile)
        if cached.failed:
            return cached
        return replace(cached, source=SourceText.from_text(text))
    pending = prepare_text(file.relative, file.language, text, config)
    cache.store(file.relative, file.language, raw, pending_to_plain(pending))
    return pending


def _file_result(
    pending: PendingFile,
    rules_applied: tuple[str, ...],
    findings: tuple[Finding, ...],
    suppressions: tuple[Suppression, ...],
) -> FileResult:
    """``pending`` as a final result with its applied rules and finished findings."""
    return FileResult(
        path=pending.path,
        language=pending.language,
        role=pending.role,
        role_pattern=pending.role_pattern,
        parser=pending.parser,
        status=pending.status,
        line_count=pending.line_count,
        rules_applied=rules_applied,
        rules_disabled=pending.rules_disabled,
        parse_failure=pending.parse_failure,
        error=pending.error,
        findings=findings,
        suppressions=suppressions,
    )


def finish(pending: PendingFile, extra: Sequence[Finding], options: AnalysisOptions) -> FileResult:
    """Phase three: suppressions (SUPP001/SUPP002), ordering, fingerprints."""
    if pending.failed:
        return _file_result(pending, (), (), ())
    assert pending.source is not None and pending.facts is not None
    if pending.status != STATUS_ANALYZED or pending.parse_failure is not None:
        raise AssertionError(f"{pending.path}: finishing a file that was not analyzed")
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
    suppressions, _problems = parse_suppressions(pending.facts.comments)
    return _file_result(pending, tuple(sorted(applied)), tuple(findings), suppressions)


def verification_input(pending: PendingFile) -> FileVerification:
    """What the VERIFY rules need from a prepared file (H2)."""
    failure: str | None = None
    facts = NO_VERIFICATION
    if pending.failed:
        failure = pending.status
        if pending.error is not None:
            failure = f"{pending.status}: {pending.error}"
    else:
        assert pending.facts is not None
        facts = pending.facts.verification
    return FileVerification(
        path=pending.path,
        role=pending.role,
        failure=failure,
        disabled=pending.disabled_ids(),
        facts=facts,
    )


def _module_inputs(pendings: Sequence[PendingFile]) -> list[ModuleInput]:
    return [
        ModuleInput(
            path=pending.path,
            language=pending.language,
            units=pending.units,
            imports=pending.facts.imports,
            bindings=pending.facts.bindings,
            receivers=pending.facts.receivers,
        )
        for pending in pendings
        if not pending.failed and pending.facts is not None and pending.source is not None
    ]


def cross_file(pendings: Sequence[PendingFile], config: EffectiveConfig) -> ComplexityOutcome:
    """Phase two: the call graph over every parsed file, and the CPLX005 findings."""
    sources: dict[str, SourceText] = {}
    cplx005_paths: set[str] = set()
    for pending in pendings:
        if pending.failed or pending.facts is None or pending.source is None:
            continue
        sources[pending.path] = pending.source
        if registry.CPLX005.rule_id in pending.rules_applied:
            cplx005_paths.add(pending.path)
    return assemble(_module_inputs(pendings), sources, config, frozenset(cplx005_paths))


def _rejections_reported(pendings: Sequence[PendingFile]) -> bool:
    """Some file registers a global unhandled-rejection listener that reports (ASYNC001)."""
    return any(
        handler.reports
        for pending in pendings
        if pending.facts is not None
        for handler in pending.facts.asynchrony.rejection_handlers
    )


def async_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """ASYNC001-ASYNC003 for every file that applies them (H4). ASYNC001 resolves project
    callees through the call graph, built here when complexity did not build it."""
    applying = [
        p
        for p in pendings
        if not p.failed and any(rule.rule_id in p.rules_applied for rule in ASYNC_RULES)
    ]
    if len(applying) == 0:
        return {}
    if graph is None:
        graph = build_call_graph(_module_inputs(pendings))
    async_units = frozenset(
        unit.key for pending in pendings for unit in pending.units if unit.fact.is_async
    )
    reported = _rejections_reported(pendings)
    found: dict[str, list[Finding]] = {}
    for pending in applying:
        assert pending.facts is not None and pending.source is not None
        found[pending.path] = run_async_rules(
            pending.facts,
            pending.source,
            config.section(registry.ASYNC_SECTION),
            pending.path,
            pending.language,
            frozenset(r.rule_id for r in ASYNC_RULES if r.rule_id in pending.rules_applied),
            graph.sites,
            async_units,
            reported,
        )
    return found


def role_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """ROLE001 for every file that applies it: imports of test-role files from production
    files (through the module graph) and test-role files with no test case."""
    if graph is None:
        return {}
    files = [
        RoleFile(
            path=p.path,
            role=p.role,
            role_pattern=p.role_pattern,
            facts=p.facts,
            source=p.source,
            applies=registry.ROLE001.rule_id in p.rules_applied,
        )
        for p in pendings
        if not p.failed and p.facts is not None and p.source is not None
    ]
    return run_role_integrity(files, graph, config.section(registry.ROLE_INTEGRITY_SECTION))


def input_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """INPUT001 for every file that applies it (H6): sources traced to sinks across files
    through the call graph."""
    if graph is None:
        return {}
    files = _flow_files(pendings, registry.INPUT001)
    return run_input001(files, graph, config.section(registry.INPUT_SECTION))


def _flow_files(pendings: Sequence[PendingFile], rule: registry.RuleSpec) -> list[FlowFile]:
    return [
        FlowFile(
            path=p.path,
            language=p.language,
            facts=p.facts,
            source=p.source,
            applies=rule.rule_id in p.rules_applied,
        )
        for p in pendings
        if not p.failed and p.facts is not None and p.source is not None
    ]


def assert_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """ASSERT001 (an assert on external input, traced across files) and ASSERT002 (asserts
    relied on, optimized runs not refused): decision 28."""
    assertions = config.section(registry.ASSERTIONS_SECTION)
    found: dict[str, list[Finding]] = {}
    if graph is not None:
        inputs = config.section(registry.INPUT_SECTION)
        files = _flow_files(pendings, registry.ASSERT001)
        for path, findings in run_assert001(files, graph, inputs, assertions).items():
            found[path] = list(findings)
    severity = str(assertions["assert002_severity"])
    for path, findings in run_assert002(
        _flow_files(pendings, registry.ASSERT002), severity
    ).items():
        if path not in found:
            found[path] = []
        found[path].extend(findings)
    return found


def type_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig
) -> dict[str, list[Finding]]:
    """TYPE002 (decision 33): annotations that no configured type checker verifies."""
    files = [
        TypedFile(p.path, p.language, p.source, p.facts.annotations)
        for p in pendings
        if registry.TYPE002.rule_id in p.rules_applied
        and p.facts is not None
        and p.source is not None
    ]
    if len(files) == 0:
        return {}
    return run_type002(files, config.root, config.section(registry.TYPES_SECTION))


def string_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig
) -> dict[str, list[Finding]]:
    """MAGIC002: string literals repeated across the files where the rule applies."""
    files = [
        StringFile(
            path=p.path,
            strings=p.facts.strings,
            source=p.source,
            applies=registry.MAGIC002.rule_id in p.rules_applied,
        )
        for p in pendings
        if not p.failed and p.facts is not None and p.source is not None
    ]
    if not any(file.applies for file in files):
        return {}
    return run_magic002(files, config.section(registry.MAGIC_STRINGS_SECTION))


def stub_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """STUB003: checks that always answer yes, told apart from base-class hook defaults
    by the classes of every file and the module graph's import edges."""
    if graph is None:
        return {}
    files = [
        PredicateFile(
            path=p.path,
            catalog=p.facts.catalog,
            imports=p.facts.imports,
            source=p.source,
            applies=registry.STUB003.rule_id in p.rules_applied,
        )
        for p in pendings
        if not p.failed and p.facts is not None and p.source is not None
    ]
    if not any(file.applies for file in files):
        return {}
    return run_stub003(files, graph.module_edges, config.section(registry.STUBS_SECTION))


def dom_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """DOM002: pressable elements on document.body that a named skip list misses."""
    if graph is None:
        return {}
    files = [
        FloatingFile(
            path=p.path,
            dom=p.facts.dom,
            imports=p.facts.imports,
            source=p.source,
            applies=registry.DOM002.rule_id in p.rules_applied,
        )
        for p in pendings
        if not p.failed and p.facts is not None and p.source is not None
    ]
    if not any(file.applies for file in files):
        return {}
    return run_dom002(files, graph.module_edges, config.section(registry.DOM_SECTION))


def consistency_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """PROV001 and GUARD001 (H6 part two): call sites of one function that disagree."""
    if graph is None:
        return {}
    settings = config.section(registry.CONSISTENCY_SECTION)
    depth = int(config.section(registry.INPUT_SECTION)["max_depth"])
    found: dict[str, list[Finding]] = {}
    for rule, run in ((registry.PROV001, run_prov001), (registry.GUARD001, run_guard001)):
        for path, findings in run(_flow_files(pendings, rule), graph, settings, depth).items():
            if path not in found:
                found[path] = []
            found[path].extend(findings)
    return found


def _whole_project(pendings: Sequence[PendingFile], config: EffectiveConfig) -> bool:
    """Every file the configuration includes was analyzed and parsed: a partial run (a
    path argument, the edit hook) cannot tell dead code from code called elsewhere."""
    analyzed = {p.path for p in pendings if not p.failed}
    every = discover(config.root, [config.root], config).files
    return all(f.relative in analyzed for f in every)


def dead_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, graph: CallGraph | None
) -> dict[str, list[Finding]]:
    """DEAD001, DEAD002: functions nothing in production reaches, by cluster."""
    ids = frozenset(rule.rule_id for rule in DEAD_RULES)
    if graph is None or not any(ids & set(p.rules_applied) for p in pendings):
        return {}
    if not _whole_project(pendings, config):
        return {}
    files = [
        DeadFile(
            path=p.path,
            tested=p.role in (ROLE_TEST, ROLE_CONFIG),
            applied=ids & frozenset(p.rules_applied),
            source=p.source,
            units=p.units,
            usage=p.facts.usage,
            imports=p.facts.imports,
            classes=p.facts.receivers.classes,
        )
        for p in pendings
        if p.facts is not None and p.source is not None
    ]
    runtime = config.section(registry.PROPERTY_CONTRACTS_SECTION)["runtime_module"]
    libraries = [str(m) for m in runtime if str(m).endswith(RUNTIME_SUFFIXES)]
    return run_dead_code(files, graph, config.section(registry.DEAD_CODE_SECTION), libraries)


def contract_findings(
    pendings: Sequence[PendingFile], config: EffectiveConfig, cache: FileCache | None
) -> dict[str, list[Finding]]:
    """PROP001, PROP003, PROP005-PROP007 (property contracts, opt-in): declarations checked
    at call sites and catalog sinks, reading resolved callees' own contracts from the
    analyzed files, or from the project's files under the root for the others. The one
    cross-file phase the cache covers: its findings are reused while every analyzed file
    and every other file it probed or read is unchanged."""
    parsed = [p for p in pendings if not p.failed and p.source is not None]
    files: list[ContractFile] = []
    sources: dict[str, tuple[str, SourceText]] = {}
    settings = config.section(registry.PROPERTY_CONTRACTS_SECTION)
    for pending in parsed:
        assert pending.source is not None, "a parsed file has its source"
        sources[pending.path] = (pending.language, pending.source)
        applies = frozenset(r.rule_id for r in CONTRACT_RULES if r.rule_id in pending.rules_applied)
        if len(applies) > 0:
            complete = complete_scope(settings, pending.path)
            files.append(
                ContractFile(pending.path, pending.language, pending.source, applies, complete)
            )
    if len(files) == 0:
        return {}
    if cache is None:
        return property_contract_findings(
            files, sources, config.root, settings, new_log(config.root), {}
        )
    return _incremental_contracts(files, sources, pendings, config, cache)


def _incremental_contracts(
    files: Sequence[ContractFile],
    sources: Mapping[str, tuple[str, SourceText]],
    pendings: Sequence[PendingFile],
    config: EffectiveConfig,
    cache: FileCache,
) -> dict[str, list[Finding]]:
    """The last run's findings for every file whose findings' inputs are unchanged
    (``contracts/incremental.py``); the phase for the others; the merged entries stored."""
    current = current_of(config.root, sources, _classes_digest(pendings))
    previous = cache.lookup_contracts({}, decode_contracts)
    entries: dict[str, FileEntry] = {}
    stale: list[ContractFile] = []
    for file in files:
        entry = _previous_entry(previous, file, current)
        if entry is None:
            stale.append(file)
        else:
            entries[file.path] = entry
    deps: dict[str, Deps] = {}
    found: dict[str, list[Finding]] = {}
    if len(stale) > 0:
        settings = config.section(registry.PROPERTY_CONTRACTS_SECTION)
        disk = new_log(config.root)
        found = property_contract_findings(stale, sources, config.root, settings, disk, deps)
    for file in stale:
        findings: list[Finding] = []
        if file.path in found:
            findings = found[file.path]
        file_deps = no_deps()
        if file.path in deps:
            file_deps = deps[file.path]
        entries[file.path] = entry_for(file, findings, file_deps, current)
    cache.contracts_counts(len(files) - len(stale), len(files))
    result = ContractsResult(current.classes, tuple(entries[path] for path in sorted(entries)))
    cache.store_contracts({}, encode_contracts(result))
    return {path: list(entry.findings) for path, entry in entries.items()}


def _previous_entry(
    previous: ContractsResult | None, file: ContractFile, current: Current
) -> FileEntry | None:
    if previous is None:
        return None
    entries = entries_by_path(previous)
    if file.path not in entries:
        return None
    entry = entries[file.path]
    if not reusable(entry, file, current, previous.classes):
        return None
    return entry


# The units whose names make up a class's structure for the override checks.
CLASS_UNIT_KINDS = frozenset({UNIT_CLASS, UNIT_METHOD})


def _classes_digest(pendings: Sequence[PendingFile]) -> str:
    """Every analyzed class: its name, its bases, the names of its methods (properties
    included), from the per-file facts."""
    material = []
    for pending in sorted(pendings, key=lambda p: p.path):
        if pending.facts is None:
            continue
        classes = [[c.name, list(c.bases)] for c in pending.facts.receivers.classes]
        methods = sorted(u.name for u in pending.units if u.kind in CLASS_UNIT_KINDS)
        if len(classes) > 0 or len(methods) > 0:  # a file without classes changes nothing
            material.append([pending.path, classes, methods])
    return text_digest(json.dumps(material, separators=(",", ":")))


# The cross-file rules that need the call graph or the module graph (built here when
# complexity did not build it), and the phases that compute them, in report order.
GRAPH_RULES = (
    *ASYNC_RULES,
    registry.ROLE001,
    registry.INPUT001,
    registry.IMPORT001,
    registry.ASSERT001,
    registry.PROV001,
    registry.GUARD001,
    registry.STUB003,
    registry.DOM002,
    *DEAD_RULES,
)
GRAPH_PHASES = (
    async_findings,
    role_findings,
    input_findings,
    assert_findings,
    consistency_findings,
    stub_findings,
    dom_findings,
    dead_findings,
)


def complete(
    pendings: Sequence[PendingFile],
    config: EffectiveConfig,
    options: AnalysisOptions,
    cache: FileCache | None,
) -> AnalysisOutcome:
    outcome = cross_file(pendings, config)
    graph = outcome.call_graph
    if graph is None and any(
        rule.rule_id in p.rules_applied for p in pendings for rule in GRAPH_RULES
    ):
        graph = build_call_graph(_module_inputs(pendings))
    if graph is not None:
        pendings = _unimported_scripts(pendings, config, graph)
    phases = (
        outcome.graph_findings,
        *(phase(pendings, config, graph) for phase in GRAPH_PHASES),
        contract_findings(pendings, config, cache),
        string_findings(pendings, config),
        type_findings(pendings, config),
    )
    results: list[FileResult] = []
    for pending in pendings:
        extra: list[Finding] = []
        for found in phases:
            if pending.path in found:
                extra.extend(found[pending.path])
        results.append(finish(pending, extra, options))
    return AnalysisOutcome(
        files=tuple(results),
        metrics={"complexity": outcome.complexity, "graph": outcome.graph},
        verification={pending.path: verification_input(pending) for pending in pendings},
        catches=_catches(pendings, config),
    )


def _catches(
    pendings: Sequence[PendingFile], config: EffectiveConfig
) -> dict[str, tuple[CatchFact, ...]]:
    capture = frozenset(
        str(name) for name in config.section(EXCEPTIONS_SECTION)["capture_managers"]
    )
    return {
        pending.path: (*pending.facts.catches, *manager_catches(pending.facts.managers, capture))
        for pending in pendings
        if pending.facts is not None
    }


def unsupported_source_result(relative: str, reason: str, config: EffectiveConfig) -> FileResult:
    """The failed result an included-but-unparseable file becomes under
    ``unsupported_sources = "fail"``: it counts as an analysis failure, never as clean."""
    role = file_role(relative, config)
    return FileResult(
        path=relative,
        language=LANGUAGE_UNSUPPORTED,
        role=role.role,
        role_pattern=role.pattern,
        parser=None,
        status=STATUS_UNSUPPORTED,
        line_count=0,
        rules_applied=(),
        rules_disabled=(),
        parse_failure=None,
        error=f'{reason} and unsupported_sources = "fail"',
        findings=(),
        suppressions=(),
    )


def with_unsupported_sources(
    files: Sequence[FileResult], discovery: DiscoveryResult, config: EffectiveConfig
) -> tuple[FileResult, ...]:
    """Under ``unsupported_sources = "fail"``, the included files no adapter can parse
    join the results as analysis failures; under ``warn``/``ignore`` they stay in
    ``coverage`` only."""
    if config.values[UNSUPPORTED_SOURCES_KEY] != UNSUPPORTED_FAIL:
        return tuple(files)
    extra = [unsupported_source_result(s.relative, s.reason, config) for s in discovery.unsupported]
    return tuple(sorted([*files, *extra], key=lambda f: f.path))


def analyze_files(
    files: Sequence[DiscoveredFile],
    config: EffectiveConfig,
    options: AnalysisOptions,
    cache: FileCache | None,
) -> AnalysisOutcome:
    """The whole pipeline for a set of discovered files; per-file results come from
    ``cache`` when it is open and the key matches, cross-file work is always recomputed."""
    pendings = [prepare_file(file, config, cache) for file in files]
    return complete(pendings, config, options, cache)


def analyze_text(
    relative_path: str,
    language: str,
    text: str,
    config: EffectiveConfig,
    options: AnalysisOptions,
) -> FileResult:
    """One in-memory file through the whole pipeline (its graph is the file alone)."""
    outcome = complete([prepare_text(relative_path, language, text, config)], config, options, None)
    return outcome.files[0]


def analyze_file(
    file: DiscoveredFile, config: EffectiveConfig, options: AnalysisOptions
) -> FileResult:
    outcome = complete([prepare_file(file, config, None)], config, options, None)
    return outcome.files[0]
