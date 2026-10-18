"""H5 API-catalog rules: PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001,
STUB003.

The facts are syntax (ir/python_catalog.py, ir/javascript_catalog.py, and the H4
discarded calls for RESULT001); this module applies the catalogs in each rule's section,
resolving callees through the file's own imports (rules/guardrails.py).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import ModuleEdge
from shockharness.contracts.catalog import runtime_callees
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CHECK_TRUE,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    RETRY_DECORATOR,
    TYPE_ESCAPE_ANY,
    TYPE_ESCAPE_CAST,
    TYPE_ESCAPE_NON_NULL,
    CatalogFacts,
    ConstantPredicate,
    ImportFact,
    ModuleFacts,
    ProcessCall,
    Span,
)
from shockharness.ir.suppression_directives import (
    TOOL_TS_EXPECT_ERROR,
    TOOL_TS_IGNORE,
    TOOL_TS_NOCHECK,
    TOOL_TYPE_IGNORE,
)
from shockharness.rules.guardrails import import_aliases, qualified_callee
from shockharness.rules.imports import ClassKey, imported_names
from shockharness.rules.registry import (
    BATCH001,
    PROCESS001,
    PYTHON,
    RESULT001,
    RETRY001,
    SLEEP001,
    STUB003,
    TYPE001,
    TYPESCRIPT,
    RuleSpec,
)
from shockharness.schema import MUST_USE_ENTRY
from shockharness.source import SourceText

CATALOG_RULES = (PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001, STUB003)
# Process APIs that always run their command through a shell.
SHELL_APIS = frozenset(
    {
        "os.system",
        "os.popen",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "child_process.exec",
        "child_process.execSync",
    }
)
# Process APIs whose exit status is returned rather than raised.
STATUS_APIS = frozenset(
    {"subprocess.run", "subprocess.call", "os.system", "child_process.spawnSync"}
)
PYTHON_RETURNCODE_APIS = frozenset({"subprocess.run", "subprocess.call"})
METHOD_PREFIX = "."
PROMISE_SLEEP = "Promise"
TIMERS_SET_TIMEOUT = "timers/promises.setTimeout"
DYNAMIC = "<dynamic>"
# Directives that silence the type checker: Python's type-ignore comment and TypeScript's
# @ts-ignore, @ts-expect-error and @ts-nocheck (the whole file).
TYPE_CHECKER_DIRECTIVES = frozenset(
    {TOOL_TYPE_IGNORE, TOOL_TS_IGNORE, TOOL_TS_EXPECT_ERROR, TOOL_TS_NOCHECK}
)
ESCAPE_MESSAGES = {
    TYPE_ESCAPE_ANY: "{name} turns type checking off for this value: {text}",
    TYPE_ESCAPE_CAST: "{name} asserts a type without checking it: {text}",
    TYPE_ESCAPE_NON_NULL: (
        "{name} (!) claims the value is never null or undefined without checking it: {text}"
    ),
}
PYTHON_ESCAPE_NAMES = {
    TYPE_ESCAPE_ANY: "Any",
    TYPE_ESCAPE_CAST: "cast(...)",
    TYPE_ESCAPE_NON_NULL: "",  # TypeScript only
}
TYPESCRIPT_ESCAPE_NAMES = {
    TYPE_ESCAPE_ANY: "any",
    TYPE_ESCAPE_CAST: "a type assertion",
    TYPE_ESCAPE_NON_NULL: "a non-null assertion",
}


def _finding(
    rule: RuleSpec,
    severity: str,
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    confidence: str,
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=confidence,
        status=STATUS_VIOLATION,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


# -- PROCESS001 --------------------------------------------------------------------------


def _status_ignored(call: ProcessCall, qualified: str) -> bool:
    if qualified not in STATUS_APIS or call.check == CHECK_TRUE or call.returned:
        return False  # checked here, or handed to the caller with the result
    if call.discarded:
        return True
    # os.system returns a plain int, so only a dropped result is certain to be ignored.
    reads_status = qualified in PYTHON_RETURNCODE_APIS or qualified.endswith("spawnSync")
    return reads_status and not call.status_read


def _process001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    key = "python_process_apis" if language == PYTHON else "javascript_process_apis"
    apis = {str(a) for a in settings[key]}
    aliases = import_aliases(facts.imports, language)
    severity = str(settings["severity"])
    found: list[Finding] = []
    for call in facts.catalog.process_calls:
        qualified = qualified_callee(call.callee, aliases)
        if qualified not in apis:
            continue
        shell = call.shell or qualified in SHELL_APIS
        if shell and call.interpolated:
            message = (
                f"{qualified}(...) runs a shell command built from data: a value containing "
                f"shell syntax runs as a command: {call.text}"
            )
        elif _status_ignored(call, qualified):
            message = (
                f"{qualified}(...) returns the exit status instead of raising, and nothing here "
                f"checks it: a failed command looks like success: {call.text}"
            )
        else:
            continue
        found.append(
            _finding(PROCESS001, severity, path, call.span, message, source, CONFIDENCE_EXACT)
        )
    return found


# -- RESULT001 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MustUse:
    """A RESULT001 catalog entry: the arguments the pure callee takes, when given."""

    low: int | None
    high: int | None

    def accepts(self, arguments: int | None) -> bool:
        if self.low is None:
            return True
        if arguments is None:
            return False  # an unpacked argument list: the count is not known
        if self.high is None:
            return arguments == self.low
        return self.low <= arguments <= self.high


def _must_use(entries: Sequence[str]) -> dict[str, MustUse]:
    found: dict[str, MustUse] = {}
    for entry in entries:
        match = MUST_USE_ENTRY.fullmatch(entry)
        assert match is not None, f"the schema admits only valid entries: {entry!r}"
        found[match.group("name")] = MustUse(
            low=_count(match.group("low")), high=_count(match.group("high"))
        )
    return found


def _count(text: str | None) -> int | None:
    if text is None:
        return None
    return int(text)


def _result001(
    facts: ModuleFacts,
    source: SourceText,
    path: str,
    language: str,
    settings: Mapping[str, Any],
    permitted: frozenset[str],
) -> list[Finding]:
    """``permitted``: the property-contracts runtime declarations (requires, produces,
    preserves, preserves_except of the runtime module), statements by design (§10)."""
    key = "python_must_use" if language == PYTHON else "javascript_must_use"
    listed = _must_use([str(e) for e in settings[key]])
    entries = {name: entry for name, entry in listed.items() if name not in permitted}
    aliases = import_aliases(facts.imports, language)
    found: list[Finding] = []
    for call in facts.asynchrony.discarded_calls:
        if call.callee == DYNAMIC or call.in_try:
            continue  # in a try with a handler, the call may run for what it raises
        qualified = qualified_callee(call.callee, aliases)
        receiver, dot, last = call.callee.rpartition(".")
        root, _dot, _rest = receiver.partition(".")
        method = METHOD_PREFIX + last
        if qualified in entries and entries[qualified].accepts(call.arguments):
            confidence = CONFIDENCE_EXACT
        elif dot != "" and receiver != "" and root not in aliases and method in entries:
            # A method by name; a function of an imported module (os.replace) is not one.
            if not entries[method].accepts(call.arguments):
                continue  # another method of that name (Thread.join(), location.replace(u))
            confidence = CONFIDENCE_APPROXIMATE  # matched by method name, receiver untyped
        else:
            continue
        found.append(
            _finding(
                RESULT001,
                str(settings["severity"]),
                path,
                call.span,
                f"{call.callee}(...) returns a new value and changes nothing; the result is "
                f"thrown away, so this line has no effect: {call.text}",
                source,
                confidence,
            )
        )
    return found


# -- TYPE001 -----------------------------------------------------------------------------


def _type001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    severity = str(settings["severity"])
    found: list[Finding] = []
    wanted = {
        TYPE_ESCAPE_ANY: settings["report_any"] is True,
        TYPE_ESCAPE_CAST: settings["report_cast"] is True,
        TYPE_ESCAPE_NON_NULL: settings["report_non_null"] is True,
    }
    names = PYTHON_ESCAPE_NAMES if language == PYTHON else TYPESCRIPT_ESCAPE_NAMES
    for escape in facts.catalog.type_escapes:
        if not wanted[escape.kind]:
            continue
        message = ESCAPE_MESSAGES[escape.kind].format(name=names[escape.kind], text=escape.text)
        found.append(
            _finding(TYPE001, severity, path, escape.span, message, source, CONFIDENCE_EXACT)
        )
    if settings["report_type_ignore"] is True:
        for directive in facts.verification.suppressions:
            if directive.tool not in TYPE_CHECKER_DIRECTIVES:
                continue
            found.append(
                _finding(
                    TYPE001,
                    severity,
                    path,
                    directive.span,
                    f"{directive.text} silences the type checker on this line",
                    source,
                    CONFIDENCE_EXACT,
                )
            )
    return found


# -- SLEEP001 / RETRY001 / BATCH001 / STUB003 --------------------------------------------


def _sleep001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    apis = {str(a) for a in settings["python_sleep_apis"]}
    aliases = import_aliases(facts.imports, language)
    found: list[Finding] = []
    for sleep in facts.catalog.sleeps:
        qualified = qualified_callee(sleep.callee, aliases)
        if language == PYTHON and qualified not in apis:
            continue
        if language != PYTHON and sleep.callee != PROMISE_SLEEP and qualified != TIMERS_SET_TIMEOUT:
            continue
        what = "polls with a fixed sleep in a loop" if sleep.in_loop else "waits a fixed time"
        found.append(
            _finding(
                SLEEP001,
                str(settings["severity"]),
                path,
                sleep.span,
                f"{what} instead of waiting for the condition it needs: {sleep.text}",
                source,
                CONFIDENCE_APPROXIMATE,
            )
        )
    return found


def _retry001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    decorators = {str(d) for d in settings["retry_decorators"]}
    aliases = import_aliases(facts.imports, language)
    found: list[Finding] = []
    for retry in facts.catalog.retries:
        if retry.kind == RETRY_DECORATOR:
            qualified = qualified_callee(retry.callee, aliases)
            if qualified not in decorators:
                continue
            message = (
                f"{retry.text} retries with no stop condition: a permanent failure retries forever"
            )
        else:
            message = (
                "an endless loop retries after an exception and its handler never raises, "
                "returns or breaks: a permanent failure loops forever"
            )
        found.append(
            _finding(
                RETRY001,
                str(settings["severity"]),
                path,
                retry.span,
                message,
                source,
                CONFIDENCE_EXACT,
            )
        )
    return found


def _batch001(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    return [
        _finding(
            BATCH001,
            str(settings["severity"]),
            path,
            loop.span,
            f"{loop.text} drops per-item failures (the handler only passes, continues or logs): "
            "the batch reports success with items missing",
            source,
            CONFIDENCE_APPROXIMATE,
        )
        for loop in facts.catalog.batch_loops
    ]


@dataclass(frozen=True)
class PredicateFile:
    path: str
    catalog: CatalogFacts
    imports: tuple[ImportFact, ...]
    source: SourceText
    applies: bool


def _resolve_base(
    path: str, base: str, defined: set[ClassKey], imported: Mapping[tuple[str, str], ClassKey]
) -> ClassKey | None:
    """The project class a base names: one of the file's own classes, a class it imports
    (``from base_modal import BaseModal``), or a class of a module it imports whole
    (``modals.BaseModal``)."""
    root, _dot, rest = base.partition(".")
    if rest == "" and (path, base) in defined:
        return (path, base)
    if rest == "" and (path, base) in imported:
        return imported[(path, base)]
    if rest != "" and "." not in rest and (path, root) in imported:
        module, name = imported[(path, root)]
        if (module, name) not in defined:  # the name is a module (import x; from p import m)
            return (module, rest)
    return None


def _class_bases(
    files: Sequence[PredicateFile], module_edges: Sequence[ModuleEdge]
) -> dict[ClassKey, list[ClassKey]]:
    """Every class and the project classes its bases resolve to."""
    defined = {(file.path, c.name) for file in files for c in file.catalog.classes}
    imported = imported_names([(f.path, f.imports) for f in files], module_edges)
    bases: dict[ClassKey, list[ClassKey]] = {}
    for file in files:
        for declared in file.catalog.classes:
            resolved = [_resolve_base(file.path, b, defined, imported) for b in declared.bases]
            bases[(file.path, declared.name)] = [r for r in resolved if r is not None]
    return bases


def run_stub003(
    files: Sequence[PredicateFile], module_edges: Sequence[ModuleEdge], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    """STUB003 across files. A base-class hook default (a class some project class
    extends) is not reported; an override that repeats an always-yes method of the base
    it extends is reported as redundant. Bases are resolved through each file's imports."""
    bases = _class_bases(files, module_edges)
    extended = {base for found in bases.values() for base in found}
    yes = {
        (file.path, p.class_name, p.name)
        for file in files
        for p in file.catalog.constant_predicates
        if p.class_name is not None
    }
    found: dict[str, list[Finding]] = {}
    for file in files:
        if not file.applies:
            continue
        for predicate in file.catalog.constant_predicates:
            finding = _stub003(file, predicate, bases, extended, yes, settings)
            if finding is None:
                continue
            if file.path not in found:
                found[file.path] = []
            found[file.path].append(finding)
    return found


def _stub003(
    file: PredicateFile,
    predicate: ConstantPredicate,
    bases: Mapping[ClassKey, Sequence[ClassKey]],
    extended: set[ClassKey],
    yes: set[tuple[str, str | None, str]],
    settings: Mapping[str, Any],
) -> Finding | None:
    message = f"{predicate.name} is named as a check and always answers yes"
    if predicate.class_name is not None:
        own = (file.path, predicate.class_name)
        repeated = [b for b in bases[own] if (b[0], b[1], predicate.name) in yes]
        if len(repeated) > 0:
            message = (
                f"{predicate.class_name}.{predicate.name} repeats {repeated[0][1]}."
                f"{predicate.name}, which already answers yes: remove the override"
            )
        elif own in extended:
            return None  # a default for subclasses to override
    return _finding(
        STUB003,
        str(settings["stub003_severity"]),
        file.path,
        predicate.span,
        message,
        file.source,
        CONFIDENCE_APPROXIMATE,
    )


def run_catalog_rules(
    facts: ModuleFacts,
    source: SourceText,
    rules: Mapping[str, Any],
    path: str,
    language: str,
    active: frozenset[str],
) -> list[Finding]:
    """Findings of the active H5 rules for one file; ``rules`` is the ``rules`` table."""
    found: list[Finding] = []
    if PROCESS001.rule_id in active:
        found.extend(_process001(facts, source, path, language, rules["processes"]))
    if RESULT001.rule_id in active:
        permitted = runtime_callees(rules["property_contracts"])
        found.extend(_result001(facts, source, path, language, rules["results"], permitted))
    if TYPE001.rule_id in active and language in (PYTHON, TYPESCRIPT):
        found.extend(_type001(facts, source, path, language, rules["types"]))
    if SLEEP001.rule_id in active:
        found.extend(_sleep001(facts, source, path, language, rules["sleep"]))
    if RETRY001.rule_id in active:
        found.extend(_retry001(facts, source, path, language, rules["retry"]))
    if BATCH001.rule_id in active:
        found.extend(_batch001(facts, source, path, rules["batches"]))
    return found
