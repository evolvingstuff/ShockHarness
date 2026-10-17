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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from shockharness.cache.codec import from_plain, to_plain
from shockharness.cache.store import FileCache
from shockharness.complexity.assemble import ComplexityOutcome, assemble
from shockharness.complexity.callgraph import CallGraph, ModuleInput, build_call_graph
from shockharness.complexity.metrics import UnitMetrics, measure_units
from shockharness.config import UNSUPPORTED_FAIL, UNSUPPORTED_SOURCES_KEY, EffectiveConfig
from shockharness.discovery import DiscoveredFile, DiscoveryResult
from shockharness.findings import Finding
from shockharness.gating.baseline import assign_fingerprints
from shockharness.globs import compile_globset
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import NO_VERIFICATION, ModuleFacts, ParseFailure
from shockharness.ir.python import extract_python_facts
from shockharness.roles import FILE_ROLES_KEY, ROLE_CONFIG, FileRole, role_classifier
from shockharness.rules import registry
from shockharness.rules.api_catalog import CATALOG_RULES, run_catalog_rules
from shockharness.rules.async_lifecycle import ASYNC_RULES, run_async_rules
from shockharness.rules.complexity import run_unit_rules
from shockharness.rules.defaults import DEFAULT_RULES, run_default_rules
from shockharness.rules.exceptions import run_exception_rules
from shockharness.rules.guardrails import GUARDRAIL_RULES, run_guardrail_rules
from shockharness.rules.magic_numbers import run_magic001
from shockharness.rules.registry import CATALOG_SECTIONS, GUARDRAIL_SECTIONS
from shockharness.rules.role_integrity import RoleFile, run_role_integrity
from shockharness.rules.verification import FileVerification
from shockharness.source import SourceText
from shockharness.suppressions import Suppression, apply_suppressions, parse_suppressions

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
        if rule.config_section is None:
            continue
        section = config.section(rule.config_section)
        if section["enabled"] is False:
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


def _in_scope(rule: registry.RuleSpec, role: FileRole, config: EffectiveConfig) -> bool:
    """H3: a role-scoped rule applies to the roles its section lists. Like the VERIFY role
    scopes, a rule outside its roles is not applied to the file (and not listed as disabled)."""
    section = rule.config_section
    if section is None or section not in (*GUARDRAIL_SECTIONS, *CATALOG_SECTIONS):
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
    relative_path: str, facts: ModuleFacts, complexity: Mapping[str, Any], applied: list[str]
) -> tuple[UnitMetrics, ...]:
    """ASYNC001 resolves callees through the call graph, which is built from the units, so
    they are measured for it even when complexity is disabled (and then not reported)."""
    if complexity["enabled"] is True or registry.ASYNC001.rule_id in applied:
        return measure_units(relative_path, facts.functions, complexity)
    return ()


def _policy_rules(
    facts: ModuleFacts,
    source: SourceText,
    config: EffectiveConfig,
    relative_path: str,
    language: str,
    role: FileRole,
    disabled_ids: set[str],
) -> tuple[list[str], list[Finding]]:
    """The H3-H5 rules for one file: (rule IDs applied, findings). ASYNC001-ASYNC003 run
    in the cross-file phase (ASYNC001 needs the call graph); here they are only recorded
    as applied when they apply to the file, and so is ROLE001."""
    rules = config.values["rules"]
    guardrails = _active_guardrails(language, role, config, disabled_ids)
    catalog = frozenset(
        rule.rule_id
        for rule in CATALOG_RULES
        if rule.rule_id not in disabled_ids
        and language in rule.languages
        and _in_scope(rule, role, config)
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
    return applied, findings


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


def prepare_text(
    relative_path: str, language: str, text: str, config: EffectiveConfig
) -> PendingFile:
    """Phase one: parse, run the per-file rules, measure the units."""
    source = SourceText.from_text(text)
    facts = _extract(language, source, relative_path)
    role = file_role(relative_path, config)
    disabled = _disabled_rules(relative_path, role, config)
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

    policy_applied, policy_findings = _policy_rules(
        facts, source, config, relative_path, language, role, disabled_ids
    )
    applied.extend(policy_applied)
    findings.extend(policy_findings)

    complexity = config.section(COMPLEXITY_SECTION)
    units = _units(relative_path, facts, complexity, applied)
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


def complete(
    pendings: Sequence[PendingFile], config: EffectiveConfig, options: AnalysisOptions
) -> AnalysisOutcome:
    outcome = cross_file(pendings, config)
    graph = outcome.call_graph
    graph_rules = (*ASYNC_RULES, registry.ROLE001)
    if graph is None and any(
        rule.rule_id in p.rules_applied for p in pendings for rule in graph_rules
    ):
        graph = build_call_graph(_module_inputs(pendings))
    asynchrony = async_findings(pendings, config, graph)
    roles = role_findings(pendings, config, graph)
    results: list[FileResult] = []
    for pending in pendings:
        extra: list[Finding] = []
        for found in (outcome.graph_findings, asynchrony, roles):
            if pending.path in found:
                extra.extend(found[pending.path])
        results.append(finish(pending, extra, options))
    return AnalysisOutcome(
        files=tuple(results),
        metrics={"complexity": outcome.complexity, "graph": outcome.graph},
        verification={pending.path: verification_input(pending) for pending in pendings},
    )


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
    outcome = complete([prepare_file(file, config, None)], config, options)
    return outcome.files[0]
