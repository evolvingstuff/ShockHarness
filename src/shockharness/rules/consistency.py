"""H6 part two: cross-site consistency rules (spec 21.1 decisions 20, 21 and 29).

Both compare the call sites of one project function, as the call graph resolves them
(resolved and probable sites, in files where the rule applies), and report the sites
that disagree with the others. They cannot know intent, so they ship at review.

* **PROV001** (decision 20): a parameter that some sites fill with an identifier issued
  by the program (the result of ``store.start_run()``, ``createSession()``, followed
  through attributes, ``str(...)`` and helper functions by the INPUT001 engine) and
  another site fills with a freshly made one (``uuid4()``, ``crypto.randomUUID()``):
  the made-up identifier names nothing the program knows.
* **GUARD001** (decision 21): most sites call the function only after a check of the
  same argument (``if has_hash(x): remove_hash(x)``, ``if (!hasHash(x)) return;``),
  and some do not.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import CallGraph
from shockharness.constants import PERCENT
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import CONFIDENCE_APPROXIMATE, FlowCall, FlowGuard, FlowUnit, Span
from shockharness.rules.dataflow import (
    METHOD_PREFIX,
    Analysis,
    Catalog,
    Evaluation,
    FlowFile,
    Located,
    Mode,
    Passed,
    Taint,
)
from shockharness.rules.registry import GUARD001, PROV001, PYTHON, RuleSpec

ISSUED = "issued"
FABRICATED = "fabricated"


def _finding(rule: RuleSpec, severity: str, file: FlowFile, span: Span, message: str) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _by_path(findings: Sequence[Finding]) -> dict[str, list[Finding]]:
    found: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.path not in found:
            found[finding.path] = []
        found[finding.path].append(finding)
    for listed in found.values():
        listed.sort(key=lambda f: (f.span, f.message))
    return found


# -- PROV001 ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    """One call site's argument for a parameter, classified by where its value came from."""

    file: FlowFile
    span: Span
    text: str
    issued: tuple[str, ...]
    fabricated: tuple[str, ...]


def _catalog(settings: Mapping[str, Any], language: str) -> Catalog:
    prefix = "python" if language == PYTHON else "javascript"
    return Catalog(
        sources=frozenset(str(f) for f in settings[f"{prefix}_fabricators"]),
        sinks={},
        validators=frozenset(),
        issuer_prefixes=frozenset(str(p).lower() for p in settings["issuer_prefixes"]),
    )


def _site(file: FlowFile, passed: Passed, fabricators: frozenset[str]) -> Site:
    labels = sorted({e.label for e in passed.value if isinstance(e, Taint)})
    return Site(
        file=file,
        span=passed.span,
        text=passed.text,
        issued=tuple(label for label in labels if label not in fabricators),
        fabricated=tuple(label for label in labels if label in fabricators),
    )


def _sites(analysis: Analysis, mode: Mode) -> dict[tuple[str, int], list[Site]]:
    """Every applying call site of a project function, per (unit key, parameter)."""
    sites: dict[tuple[str, int], list[Site]] = {}
    for _key, located in sorted(analysis.units.items()):
        if not located.file.applies:
            continue
        fabricators = mode.catalogs[located.file.path].sources
        for passed in Evaluation(analysis, located).passed():
            site = _site(located.file, passed, fabricators)
            key = (passed.target.key, passed.parameter)
            if key not in sites:
                sites[key] = []
            sites[key].append(site)
    return sites


def _prov_message(target: Located, parameter: int, site: Site, issued: Sequence[Site]) -> str:
    example = issued[0]
    name = target.unit.parameters[parameter]
    return (
        f"argument {name!r} of {target.unit.name}(...) is a freshly made "
        f"{site.fabricated[0]}() here, while {len(issued)} other call site(s) pass an "
        f"identifier the program issued ({example.issued[0]}(...) at "
        f"{example.file.path}:{example.span.line}): the made-up one names nothing the "
        f"program knows: {site.text}"
    )


def run_prov001(
    files: Sequence[FlowFile], graph: CallGraph, settings: Mapping[str, Any], max_depth: int
) -> dict[str, list[Finding]]:
    if not any(file.applies for file in files):
        return {}
    mode = Mode(
        rule=PROV001,
        severity=str(settings["severity"]),
        max_depth=max_depth,
        catalogs={f.path: _catalog(settings, f.language) for f in files},
        assert_sinks=False,
        skipped_asserts={},
    )
    analysis = Analysis(files, graph, mode)
    analysis.summarize()
    found: list[Finding] = []
    for (key, parameter), sites in sorted(_sites(analysis, mode).items()):
        issued = [s for s in sites if len(s.issued) > 0]
        if len(issued) == 0:
            continue
        target = analysis.units[key]
        for site in sites:
            if len(site.fabricated) > 0 and len(site.issued) == 0:
                message = _prov_message(target, parameter, site, issued)
                found.append(_finding(PROV001, mode.severity, site.file, site.span, message))
    return _by_path(found)


# -- GUARD001 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    file: FlowFile
    call: FlowCall
    guards: frozenset[str]


def _guard_name(guard: FlowGuard) -> str:
    _receiver, _dot, name = guard.callee.rpartition(METHOD_PREFIX)
    return name


def _calls(analysis: Analysis) -> dict[str, list[Call]]:
    """Applying call sites with a first argument, per resolved project function, with the
    names of the guards in effect on that same argument."""
    calls: dict[str, list[Call]] = {}
    for _key, located in sorted(analysis.units.items()):
        if not located.file.applies:
            continue
        for call in located.unit.calls:
            resolved = analysis.target(located, call)
            if resolved is None or call.first_argument == "":
                continue
            guards = frozenset(
                _guard_name(g) for g in call.guards if g.argument == call.first_argument
            )
            target = resolved[0].key
            if target not in calls:
                calls[target] = []
            calls[target].append(Call(located.file, call, guards))
    return calls


def _usual_guard(calls: Sequence[Call], settings: Mapping[str, Any]) -> tuple[str, int] | None:
    """(the most common guard, the number of guarded sites) when enough sites check their
    argument before the call to call it the rule, and some do not."""
    guarded = [site for site in calls if len(site.guards) > 0]
    total = len(calls)
    if len(guarded) == 0 or len(guarded) == total or total < int(settings["guard_min_sites"]):
        return None
    if len(guarded) * PERCENT < int(settings["guard_min_percent"]) * total:
        return None
    counts: dict[str, int] = {}
    for site in guarded:
        for name in site.guards:
            if name not in counts:
                counts[name] = 0
            counts[name] += 1
    name, _count = max(sorted(counts.items()), key=lambda item: item[1])
    return name, len(guarded)


def _checks_itself(unit: FlowUnit) -> bool:
    """The callee checks the parameter its first argument binds before anything else
    (``if not isinstance(tags, str): raise``): a call without the check is safe."""
    index = 0
    if unit.bound_receiver:
        index = 1
    if len(unit.parameters) <= index:
        return False
    parameter = unit.parameters[index]
    return any(check.argument == parameter for check in unit.checks)


def run_guard001(
    files: Sequence[FlowFile], graph: CallGraph, settings: Mapping[str, Any], max_depth: int
) -> dict[str, list[Finding]]:
    if not any(file.applies for file in files):
        return {}
    mode = Mode(
        rule=GUARD001,
        severity=str(settings["severity"]),
        max_depth=max_depth,
        catalogs={f.path: _catalog(settings, f.language) for f in files},
        assert_sinks=False,
        skipped_asserts={},
    )
    analysis = Analysis(files, graph, mode)
    found: list[Finding] = []
    for key, calls in sorted(_calls(analysis).items()):
        usual = _usual_guard(calls, settings)
        if usual is None or _checks_itself(analysis.units[key].unit):
            continue
        name, count = usual
        target = analysis.units[key].unit.name
        for site in calls:
            # A site that checks its argument some other way (isdir for exists) is guarded.
            if len(site.guards) > 0:
                continue
            message = (
                f"{site.call.callee}({site.call.first_argument}) runs without a check of its "
                f"argument, while {count} of {len(calls)} call sites of {target}(...) check it "
                f"first (most often {name}({site.call.first_argument})): {site.call.text}"
            )
            found.append(_finding(GUARD001, mode.severity, site.file, site.call.span, message))
    return _by_path(found)
