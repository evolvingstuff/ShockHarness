"""H5 API-catalog rules: PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001,
STUB003.

The facts are syntax (ir/python_catalog.py, ir/javascript_catalog.py, and the H4
discarded calls for RESULT001); this module applies the catalogs in each rule's section,
resolving callees through the file's own imports (rules/guardrails.py).
"""

from collections.abc import Mapping
from typing import Any

from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CHECK_TRUE,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    RETRY_DECORATOR,
    TYPE_ESCAPE_ANY,
    TYPE_ESCAPE_CAST,
    TYPE_ESCAPE_NON_NULL,
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


def _result001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    key = "python_must_use" if language == PYTHON else "javascript_must_use"
    entries = [str(e) for e in settings[key]]
    functions = {e for e in entries if not e.startswith(METHOD_PREFIX)}
    methods = {e[len(METHOD_PREFIX) :] for e in entries if e.startswith(METHOD_PREFIX)}
    aliases = import_aliases(facts.imports, language)
    found: list[Finding] = []
    for call in facts.asynchrony.discarded_calls:
        if call.callee == DYNAMIC:
            continue
        qualified = qualified_callee(call.callee, aliases)
        receiver, dot, last = call.callee.rpartition(".")
        root, _dot, _rest = receiver.partition(".")
        if qualified in functions:
            confidence = CONFIDENCE_EXACT
        elif dot != "" and receiver != "" and root not in aliases and last in methods:
            # A method by name; a function of an imported module (os.replace) is not one.
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


def _stub003(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    return [
        _finding(
            STUB003,
            str(settings["stub003_severity"]),
            path,
            predicate.span,
            f"{predicate.name} is named as a check and always answers yes",
            source,
            CONFIDENCE_APPROXIMATE,
        )
        for predicate in facts.catalog.constant_predicates
    ]


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
        found.extend(_result001(facts, source, path, language, rules["results"]))
    if TYPE001.rule_id in active and language in (PYTHON, TYPESCRIPT):
        found.extend(_type001(facts, source, path, language, rules["types"]))
    if SLEEP001.rule_id in active:
        found.extend(_sleep001(facts, source, path, language, rules["sleep"]))
    if RETRY001.rule_id in active:
        found.extend(_retry001(facts, source, path, language, rules["retry"]))
    if BATCH001.rule_id in active:
        found.extend(_batch001(facts, source, path, rules["batches"]))
    if STUB003.rule_id in active:
        found.extend(_stub003(facts, source, path, rules["stubs"]))
    return found
