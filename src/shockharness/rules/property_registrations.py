"""PROP005, the predicate half (spec §6.4, P2): with ``runtime_mode_required = "verify"``,
every property that is not static needs a predicate, and the catalog's
``registration_module`` is where the project registers them. A property that module
never passes to the runtime's ``register(...)`` (as a string literal) would raise at its
first ``requires`` or ``produces`` in verify mode; it is reported on the configuration
file, at the ``registration_module`` line, like EXC005."""

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shockharness.config import EffectiveConfig
from shockharness.contracts.catalog import (
    SECTION_PATH,
    is_javascript_path,
    javascript_runtime_modules,
    module_file,
    python_runtime_modules,
    read_module,
    static_properties,
)
from shockharness.contracts.deps import Tracker
from shockharness.contracts.disk import new_log
from shockharness.contracts.javascript_flow import field_nodes, inner
from shockharness.contracts.javascript_index import (
    NO_JS_RECEIVERS,
    RUNTIME_MARKER,
    JsProjectIndex,
)
from shockharness.contracts.python_index import NO_RECEIVERS, ProjectIndex
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.javascript_functions import string_value
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import MODULE_SCOPE, Span
from shockharness.rules.policy_integrity import FIRST_LINE, USER_TIERS, fingerprinted, read_text
from shockharness.rules.registry import PROP005

VERIFY = "verify"
REGISTER = "register"
REGISTRATION_KEY = "registration_module"


def _python_registrations(root: Path, module: str, runtime: frozenset[str]) -> frozenset[str]:
    found = module_file(root, module.split("."))
    if found is None:
        return frozenset()
    tree, _why = read_module(found)
    if tree is None:
        return frozenset()
    index = ProjectIndex(
        root, {found.relative_to(root).as_posix(): tree}, runtime, new_log(root), Tracker()
    )
    project = index.by_path[found.relative_to(root).as_posix()]
    targets = {f"{name}.{REGISTER}" for name in runtime}
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) == 0:
            continue
        first = node.args[0]
        callee = index.callee(project, node.func, frozenset(), NO_RECEIVERS)
        if (
            callee.reference in targets
            and isinstance(first, ast.Constant)
            and isinstance(first.value, str)
        ):
            names.add(str(first.value))
    return frozenset(names)


def _javascript_registrations(root: Path, path: str, runtime: frozenset[str]) -> frozenset[str]:
    index = JsProjectIndex(root, {}, runtime, new_log(root), Tracker())
    module = index.module(path)
    if module is None:
        return frozenset()
    names: set[str] = set()
    pending = [module.root]
    while len(pending) > 0:
        node = pending.pop()
        pending.extend(node.named_children)
        if node.type != Kind.CALL_EXPRESSION:
            continue
        for function in field_nodes(node, Field.FUNCTION):
            callee = index.callee(module, function, frozenset(), NO_JS_RECEIVERS)
            arguments = inner(node, Field.ARGUMENTS)
            if callee.reference == f"{RUNTIME_MARKER}:{REGISTER}" and len(arguments) > 0:
                name = string_value(arguments[0])
                if name is not None:
                    names.add(name)
    return frozenset(names)


def registered(root: Path, settings: Mapping[str, Any]) -> frozenset[str]:
    """The property names ``registration_module`` passes to the runtime's ``register``."""
    module = str(settings[REGISTRATION_KEY])
    if is_javascript_path(module):
        return _javascript_registrations(root, module, javascript_runtime_modules(settings))
    return _python_registrations(root, module, python_runtime_modules(settings))


def _line(text: str | None) -> int:
    if text is None:
        return FIRST_LINE
    for number, line in enumerate(text.splitlines(), start=FIRST_LINE):
        if line.strip().startswith(REGISTRATION_KEY):
            return number
    return FIRST_LINE


def _anchor(root: Path, config: EffectiveConfig) -> str:
    source = Path(config.source.path).resolve()
    if source.is_relative_to(root.resolve()):
        return source.relative_to(root.resolve()).as_posix()
    return source.name


def predicate_findings(root: Path, config: EffectiveConfig) -> tuple[Finding, ...]:
    settings = config.section(SECTION_PATH)
    if settings["enabled"] is not True or settings["runtime_mode_required"] != VERIFY:
        return ()
    if config.source.tier not in USER_TIERS:
        return ()
    static = frozenset(static_properties(settings))
    needed = sorted(str(p["name"]) for p in settings["properties"] if str(p["name"]) not in static)
    missing = [name for name in needed if name not in registered(root, settings)]
    text, _error = read_text(Path(config.source.path))
    line = _line(text)
    module = str(settings[REGISTRATION_KEY])
    findings = [
        Finding(
            rule_id=PROP005.rule_id,
            rule_version=PROP005.version,
            severity=str(settings["severities"][PROP005.rule_id]),
            path=_anchor(root, config),
            span=Span(line, FIRST_LINE, line, FIRST_LINE),
            message=(
                f"runtime_mode_required is verify, but {module} registers no predicate for "
                f"{name!r}; its first requires or produces in verify mode would raise"
            ),
            evidence=f"{REGISTRATION_KEY} = {module!r}: no register({name!r}, ...)",
            confidence=CONFIDENCE_EXACT,
            status=STATUS_VIOLATION,
            remediation=PROP005.remediation,
            safe_autofix=False,
            scope=MODULE_SCOPE,
            suppression=None,
            fingerprint=None,
            baseline=None,
        )
        for name in missing
    ]
    return fingerprinted(findings)
