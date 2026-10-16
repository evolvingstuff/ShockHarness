"""H3 guardrails: EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001 and IMPORT001.

The facts are syntax (ir/python_guardrails.py, ir/javascript_guardrails.py, plus the
existing imports, bindings, functions and comments); this module applies the
configuration: the catalogs, the permissions, and each section's severity. Role scoping
(``roles`` in each section) is decided in analysis.py, where a rule that does not apply to
a file's role is listed as disabled for that file with origin ``role``.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.globs import compile_globset
from shockharness.ir.model import (
    BINDING_VARIABLE,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    IMPORT_MODULE,
    IMPORT_NAMES,
    MODULE_SCOPE,
    PLACEHOLDER_EMPTY_BODY,
    PLACEHOLDER_NOT_IMPLEMENTED,
    UNIT_CLASS,
    UNIT_MODULE,
    ImportFact,
    ModuleFacts,
    Span,
)
from shockharness.rules.registry import (
    ASSERT001,
    BOOL001,
    EXC004,
    IMPORT001,
    JAVASCRIPT,
    PYTHON,
    STATE001,
    STUB001,
    STUB002,
    RuleSpec,
)
from shockharness.rules.severity import section_severity
from shockharness.source import SourceText

GUARDRAIL_RULES = (EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001)
NODE_PREFIX = "node:"
DEFAULT_EXPORT = "default"
PLACEHOLDER_MESSAGES = {
    PLACEHOLDER_NOT_IMPLEMENTED: "raises 'not implemented' instead of doing the work",
    PLACEHOLDER_EMPTY_BODY: "has an empty body (only pass, ... or a docstring)",
}
NOT_IMPLEMENTED_CONSTANT_MESSAGE = (
    "raises NotImplemented, which is not an exception (raising it is a TypeError); "
    "it stands in for an implementation"
)


def _finding(
    rule: RuleSpec,
    severity: str,
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    scope: str | None,
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
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


# -- EXC004 ------------------------------------------------------------------------------


def _exc004(facts: ModuleFacts, source: SourceText, path: str, severity: str) -> list[Finding]:
    return [
        _finding(
            EXC004,
            severity,
            path,
            exit_.span,
            f"{exit_.kind} leaves a finally block: an exception propagating through the try "
            f"is discarded and the {exit_.kind} takes its place",
            source,
            None,
            CONFIDENCE_EXACT,
        )
        for exit_ in facts.guardrails.finally_exits
    ]


# -- STUB001 / STUB002 -------------------------------------------------------------------


def _stub001(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    severity = str(settings["severity"])
    found: list[Finding] = []
    for placeholder in facts.guardrails.placeholders:
        where = "the module" if placeholder.scope == MODULE_SCOPE else placeholder.scope
        if placeholder.kind in PLACEHOLDER_MESSAGES:
            message = f"{where} {PLACEHOLDER_MESSAGES[placeholder.kind]}: {placeholder.text}"
        else:
            message = f"{where} {NOT_IMPLEMENTED_CONSTANT_MESSAGE}: {placeholder.text}"
        found.append(
            _finding(
                STUB001,
                severity,
                path,
                placeholder.span,
                message,
                source,
                placeholder.scope,
                CONFIDENCE_EXACT,
            )
        )
    markers = [str(m) for m in settings["markers"]]
    if len(markers) > 0:
        pattern = re.compile(r"\b(" + "|".join(re.escape(m) for m in markers) + r")\b")
        for comment in facts.comments:
            match = pattern.search(comment.text)
            if match is not None:
                found.append(
                    _finding(
                        STUB001,
                        severity,
                        path,
                        comment.span,
                        f"comment marks unfinished work ({match.group(1)} is listed in "
                        "rules.stubs.markers)",
                        source,
                        None,
                        CONFIDENCE_EXACT,
                    )
                )
    return found


def _within(module: str, prefix: str, separator: str) -> bool:
    return module == prefix or module.startswith(prefix + separator)


def _module_segments(fact: ImportFact, language: str) -> list[str]:
    if language == PYTHON:
        segments = [s for s in fact.module.split(".") if s != ""]
        if fact.module == "":
            segments.extend(name for name, _local in fact.names)
        return segments
    if not fact.module.startswith((".", "/")):
        return []  # a package name, not a path
    return [s for s in fact.module.split("/") if s not in ("", ".", "..")]


def _mock_module(fact: ImportFact, language: str, mocks: Sequence[str]) -> tuple[str, str] | None:
    """(the imported module as matched, the listed mock module), if one matches."""
    separator = "." if language == PYTHON else "/"
    candidates = [fact.module]
    if language == PYTHON and fact.kind == IMPORT_NAMES and fact.module != "":
        candidates.extend(f"{fact.module}.{name}" for name, _local in fact.names)
    for candidate in candidates:
        for mock in mocks:
            if _within(candidate, mock, separator):
                return candidate, mock
    return None


def _stub002(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    severity = str(settings["severity"])
    mocks = [str(m) for m in settings["mock_modules"]]
    segments = {str(s) for s in settings["test_path_segments"]}
    found: list[Finding] = []
    for fact in facts.imports:
        if fact.kind not in (IMPORT_MODULE, IMPORT_NAMES):
            continue
        matched = _mock_module(fact, language, mocks)
        test_segments = [s for s in _module_segments(fact, language) if s in segments]
        shown = fact.module if fact.module != "" else "."
        if matched is not None:
            shown, mock = matched
            why = f"{mock!r} is a mocking or fake-data library (rules.stubs.mock_modules)"
        elif len(test_segments) > 0:
            why = (
                f"the path has the test segment {test_segments[0]!r} "
                "(rules.stubs.test_path_segments)"
            )
        else:
            continue
        found.append(
            _finding(
                STUB002,
                severity,
                path,
                fact.span,
                f"production code imports {shown}: {why}",
                source,
                None,
                CONFIDENCE_EXACT,
            )
        )
    return found


# -- ASSERT001 / BOOL001 -----------------------------------------------------------------


def _assert001(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    allow_narrowing = settings["allow_type_narrowing"] is True
    return [
        _finding(
            ASSERT001,
            str(settings["severity"]),
            path,
            fact.span,
            f"{fact.text} is removed under python -O; the check it makes disappears in an "
            "optimized run",
            source,
            None,
            CONFIDENCE_EXACT,
        )
        for fact in facts.guardrails.asserts
        if not (allow_narrowing and fact.narrowing)
    ]


def _bool001(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    allowed = {str(c) for c in settings["allowed_callees"]}
    found: list[Finding] = []
    for argument in facts.guardrails.boolean_arguments:
        _receiver, _dot, last = argument.callee.rpartition(".")
        if last in allowed:
            continue
        found.append(
            _finding(
                BOOL001,
                str(settings["severity"]),
                path,
                argument.span,
                f"a Boolean literal is passed as positional argument {argument.position + 1} "
                f"of {argument.callee}(...); the call does not say what it switches: "
                f"{argument.text}",
                source,
                None,
                CONFIDENCE_EXACT,
            )
        )
    return found


# -- STATE001 ----------------------------------------------------------------------------


def _writers(facts: ModuleFacts) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = {}
    for unit in facts.functions:
        if unit.kind in (UNIT_MODULE, UNIT_CLASS):
            continue
        for name, _kind in unit.writes:
            if name not in writers:
                writers[name] = set()
            writers[name].add(unit.name)
    return writers


def _declared(path: str, name: str, allowed: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        entry["name"] == name and compile_globset([str(entry["path"])]).matches(path)
        for entry in allowed
    )


def _state001(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    writers = _writers(facts)
    declared_global: set[str] = set()
    for unit in facts.functions:
        declared_global.update(unit.globals_declared)
    found: list[Finding] = []
    for binding in facts.bindings:
        # As in complexity/coupling.py: a variable bound to a mutable value, or named by a
        # ``global`` statement, is mutable.
        mutable = binding.mutable or binding.name in declared_global
        if binding.kind != BINDING_VARIABLE or not mutable or binding.name not in writers:
            continue
        if _declared(path, binding.name, settings["allowed"]):
            continue
        units = ", ".join(sorted(writers[binding.name]))
        found.append(
            _finding(
                STATE001,
                str(settings["severity"]),
                path,
                binding.span,
                f"module-level {binding.name} is mutable shared state: written by {units}",
                source,
                None,
                CONFIDENCE_APPROXIMATE,
            )
        )
    return found


# -- IMPORT001 ---------------------------------------------------------------------------


def _strip(module: str) -> str:
    if module.startswith(NODE_PREFIX):
        return module[len(NODE_PREFIX) :]
    return module


def _target(fact: ImportFact, module: str, name: str, local: str, language: str) -> str | None:
    """What ``local`` refers to after this import (``None`` for a re-export)."""
    if fact.kind == IMPORT_MODULE:
        root, _dot, _rest = module.partition(".")
        if language == PYTHON and local == root:
            return root  # ``import os.path`` binds ``os``
        return module
    if fact.kind != IMPORT_NAMES:
        return None
    if name == DEFAULT_EXPORT and language == JAVASCRIPT:
        return module  # a CommonJS module's default export is the module object
    return f"{module}.{name}"


def _aliases(imports: Sequence[ImportFact], language: str) -> dict[str, str]:
    """Local name -> the qualified name it refers to, from the file's own imports."""
    aliases: dict[str, str] = {}
    for fact in imports:
        if fact.level > 0:
            continue  # a relative module is the project's own code
        module = _strip(fact.module)
        for name, local in fact.names:
            target = _target(fact, module, name, local, language)
            if target is not None:
                aliases[local] = target
    return aliases


def _qualified(callee: str, aliases: Mapping[str, str]) -> str:
    head, _dot, rest = callee.partition(".")
    if head not in aliases:
        return callee
    if rest == "":
        return aliases[head]
    return f"{aliases[head]}.{rest}"


def _import001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    key = "python_operations" if language == PYTHON else "javascript_operations"
    operations = {str(o) for o in settings[key]}
    aliases = _aliases(facts.imports, language)
    found: list[Finding] = []
    for call in facts.guardrails.import_time_calls:
        qualified = _qualified(call.callee, aliases)
        if qualified not in operations:
            continue
        found.append(
            _finding(
                IMPORT001,
                str(settings["severity"]),
                path,
                call.span,
                f"{qualified} runs when the module is imported: {call.text}",
                source,
                None,
                CONFIDENCE_EXACT,
            )
        )
    return found


def run_guardrail_rules(
    facts: ModuleFacts,
    source: SourceText,
    rules: Mapping[str, Any],
    path: str,
    language: str,
    active: frozenset[str],
) -> list[Finding]:
    """Findings of the active H3 rules for one file; ``rules`` is the ``rules`` table."""
    found: list[Finding] = []
    if EXC004.rule_id in active:
        severity = section_severity(rules["exceptions"], EXC004.default_severity)
        found.extend(_exc004(facts, source, path, severity))
    if STUB001.rule_id in active:
        found.extend(_stub001(facts, source, path, rules["stubs"]))
    if STUB002.rule_id in active:
        found.extend(_stub002(facts, source, path, language, rules["stubs"]))
    if ASSERT001.rule_id in active:
        found.extend(_assert001(facts, source, path, rules["assertions"]))
    if BOOL001.rule_id in active:
        found.extend(_bool001(facts, source, path, rules["boolean_arguments"]))
    if STATE001.rule_id in active:
        found.extend(_state001(facts, source, path, rules["module_state"]))
    if IMPORT001.rule_id in active:
        found.extend(_import001(facts, source, path, language, rules["import_effects"]))
    return found
