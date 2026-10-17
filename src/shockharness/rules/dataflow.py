"""H6 dataflow rules: INPUT001 (external input reaches a sink unvalidated) and INPUT002
(required configuration read as optional). Spec 21.1 decision 26.

The facts are each unit's value dependencies (ir/python_dataflow.py,
ir/javascript_dataflow.py): every value is a set of origins (a parameter, a read, a call's
result). This module decides with the rules.input catalogs which read or call is a source,
which call argument is a sink and which call is a validator, and composes units across
files through the call graph's per-site resolutions:

* a project function's **return summary** says which of its parameters and which sources
  reach its return values; a call's result is the summary with the call's arguments
  substituted (iterated to a fixed point, at most ``max_depth`` crossings deep);
* a parameter that reaches a sink, directly or through further calls, makes every source
  passed into it a finding at that sink.

A call that is neither a source, a validator nor a resolved project function passes on
everything it is given (receiver and arguments): ``json.loads(body)`` is as tainted as
``body``.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from shockharness.complexity.callgraph import (
    CONFIDENCE_PROBABLE,
    CONFIDENCE_RESOLVED,
    TARGET_UNIT,
    CallGraph,
)
from shockharness.complexity.metrics import unit_keys
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    ORIGIN_CALL,
    ORIGIN_PARAMETER,
    ORIGIN_READ,
    UNIT_CLASS,
    FlowCall,
    FlowRead,
    FlowUnit,
    ModuleFacts,
    Span,
    origin,
    origin_parts,
)
from shockharness.rules.guardrails import import_aliases, qualified_callee
from shockharness.rules.registry import ASSERT001, ASSERT002, INPUT001, INPUT002, PYTHON, RuleSpec
from shockharness.source import SourceText

METHOD_PREFIX = "."
SINK_SEPARATOR = ":"
CROSSING = " -> "
ASSERT_TARGET = "assert"
FIRST_WORD = re.compile(r"_*[A-Za-z][a-z0-9]*")
BELOW = ".*"
OPTIMIZE_FLAG = "sys.flags.optimize"
ASSERT_MODULE = "assert"
ASSERT_MODULE_BELOW = ("assert.", "assert/")
# Decoders that a ".parse" validator entry must not match: they parse, they do not check.
DECODERS = frozenset({"JSON.parse"})
ABSENT = {PYTHON: "None"}
ABSENT_JAVASCRIPT = "undefined"

K = TypeVar("K")
V = TypeVar("V")


def _add(mapping: dict[K, list[V]], key: K, value: V) -> None:
    if key not in mapping:
        mapping[key] = []
    mapping[key].append(value)


def _prefix(language: str) -> str:
    if language == PYTHON:
        return "python"
    return "javascript"


# -- catalogs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Catalog:
    """``issuer_prefixes`` (PROV001 only): a call whose name starts with one of these words
    (``start_run``, ``createSession``) is a source labelled with its callee."""

    sources: frozenset[str]
    sinks: Mapping[str, frozenset[int]]
    validators: frozenset[str]
    issuer_prefixes: frozenset[str]


def _sinks(entries: Sequence[Any]) -> dict[str, frozenset[int]]:
    """``"callee:N"`` entries (validated by config.py) as callee -> argument positions."""
    found: dict[str, set[int]] = {}
    for entry in entries:
        name, _separator, index = str(entry).rpartition(SINK_SEPARATOR)
        if name not in found:
            found[name] = set()
        found[name].add(int(index))
    return {name: frozenset(indices) for name, indices in found.items()}


def catalog_for(settings: Mapping[str, Any], language: str) -> Catalog:
    prefix = _prefix(language)
    return Catalog(
        sources=frozenset(str(s) for s in settings[f"{prefix}_sources"]),
        sinks=_sinks(settings[f"{prefix}_sinks"]),
        validators=frozenset(str(v) for v in settings[f"{prefix}_validators"]),
        issuer_prefixes=frozenset(),
    )


def _matches(text: str, entries: frozenset[str]) -> str | None:
    """The entry ``text`` reads (the entry itself or something below it), if any. An
    entry ending in ``.*`` matches only something below it (``os.environ.*`` is a
    variable, not the whole environment handed on)."""
    for entry in sorted(entries):
        if entry.endswith(BELOW):
            if text.startswith(entry[: len(entry) - len(BELOW)] + METHOD_PREFIX):
                return entry
        elif text == entry or text.startswith(entry + METHOD_PREFIX):
            return entry
    return None


def _method(callee: str, aliases: Mapping[str, str]) -> str | None:
    """``.m`` for a call ``x.y.m(...)`` whose root ``x`` is not an imported module."""
    receiver, dot, name = callee.rpartition(METHOD_PREFIX)
    root = receiver.partition(METHOD_PREFIX)[0]
    if dot == "" or receiver == "" or root in aliases:
        return None
    return METHOD_PREFIX + name


def issued_by(callee: str, prefixes: frozenset[str]) -> bool:
    """``store.start_run`` / ``createSession``: the callee's name opens with an issuing
    word."""
    if len(prefixes) == 0:
        return False
    _receiver, _dot, name = callee.rpartition(METHOD_PREFIX)
    word = FIRST_WORD.match(name)
    return word is not None and word.group(0).lstrip("_").lower() in prefixes


def is_validator(callee: str, aliases: Mapping[str, str], catalog: Catalog) -> bool:
    qualified = qualified_callee(callee, aliases)
    if qualified in catalog.validators:
        return True
    method = _method(callee, aliases)
    return method is not None and method in catalog.validators and qualified not in DECODERS


def sink_arguments(
    callee: str, aliases: Mapping[str, str], catalog: Catalog
) -> tuple[frozenset[int], bool]:
    """(argument positions, exact) of a sink call; no positions when it is not one."""
    qualified = qualified_callee(callee, aliases)
    if qualified in catalog.sinks:
        return catalog.sinks[qualified], True
    method = _method(callee, aliases)
    if method is not None and method in catalog.sinks:
        return catalog.sinks[method], False
    return frozenset(), False


# -- values -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    index: int


@dataclass(frozen=True)
class Taint:
    """A source value: the catalog entry it matched, where it was read, and the project
    functions it crossed to get here."""

    label: str
    path: str
    span: Span
    exact: bool
    via: tuple[str, ...]


Element = Param | Taint
Value = frozenset[Element]
EMPTY: Value = frozenset()


@dataclass(frozen=True)
class FlowFile:
    """What INPUT001 needs from one analyzed file."""

    path: str
    language: str
    facts: ModuleFacts
    source: SourceText
    applies: bool


@dataclass(frozen=True)
class Located:
    file: FlowFile
    unit: FlowUnit
    key: str
    is_class: bool


@dataclass(frozen=True)
class SinkHit:
    """A sink (a call argument, or an assert's test), reached from a parameter possibly
    through further project calls. ``target`` is the callee, or "assert"."""

    file: FlowFile
    span: Span
    text: str
    target: str
    argument: int
    exact: bool
    via: tuple[str, ...]


@dataclass(frozen=True)
class Mode:
    """What one run of the engine looks for: INPUT001 (call-argument sinks) or ASSERT001
    (asserts as sinks, no validators)."""

    rule: RuleSpec
    severity: str
    max_depth: int
    catalogs: Mapping[str, Catalog]
    assert_sinks: bool
    skipped_asserts: Mapping[str, frozenset[Span]]


@dataclass(frozen=True)
class Passed:
    """A value passed into a project function's parameter, at a call site."""

    value: Value
    target: Located
    parameter: int
    exact: bool
    span: Span
    text: str


def _index(files: Sequence[FlowFile]) -> dict[str, Located]:
    located: dict[str, Located] = {}
    for file in files:
        keys = unit_keys(file.path, file.facts.functions)
        kinds = [fact.kind for fact in file.facts.functions]
        for key, kind, unit in zip(keys, kinds, file.facts.dataflow.units, strict=True):
            located[key] = Located(file, unit, key, kind == UNIT_CLASS)
    return located


class Evaluation:
    """One unit's values under the analysis' current return summaries."""

    def __init__(self, analysis: "Analysis", located: Located) -> None:
        self.analysis = analysis
        self.located = located
        self.unit = located.unit
        self.path = located.file.path
        self.aliases = analysis.aliases[self.path]
        self.catalog = analysis.catalogs[self.path]
        self.memo: dict[int, Value] = {}

    def value(self, origins: Sequence[str]) -> Value:
        found: set[Element] = set()
        for item in origins:
            found.update(self.atom(item))
        return frozenset(found)

    def atom(self, item: str) -> Value:
        kind, index = origin_parts(item)
        if kind == ORIGIN_PARAMETER:
            return frozenset({Param(index)})
        if kind == ORIGIN_READ:
            return self.read(self.unit.reads[index])
        if index not in self.memo:
            self.memo[index] = self.call(self.unit.calls[index])
        return self.memo[index]

    def read(self, read: FlowRead) -> Value:
        text = read.text
        exact = False
        if not read.on_parameter:
            exact = text.partition(METHOD_PREFIX)[0] in self.aliases
            text = qualified_callee(text, self.aliases)
        label = _matches(text, self.catalog.sources)
        if label is None:
            return EMPTY
        return frozenset({Taint(label, self.path, read.span, exact=exact, via=())})

    def source(self, call: FlowCall) -> Value | None:
        """The call's result when the call itself is a catalog source, else None."""
        qualified = qualified_callee(call.callee, self.aliases)
        if qualified in self.catalog.sources:
            return frozenset({Taint(qualified, self.path, call.span, exact=True, via=())})
        method = _method(call.callee, self.aliases)
        if method is not None and method in self.catalog.sources:
            return frozenset({Taint(method, self.path, call.span, exact=False, via=())})
        return None

    def call(self, call: FlowCall) -> Value:
        source = self.source(call)
        if source is not None:
            return source
        if is_validator(call.callee, self.aliases, self.catalog):
            return EMPTY
        issued = issued_by(call.callee, self.catalog.issuer_prefixes)
        resolved = self.analysis.target(self.located, call)
        if resolved is not None:
            target, exact = resolved
            summary = self.substitute(call, target, exact)
            # A project function is known by its body before its name: one that returns a
            # source (a made-up uuid4()) is that, whatever it is called.
            if not issued or any(isinstance(e, Taint) for e in summary):
                return summary
        if issued:
            return frozenset({Taint(call.callee, self.path, call.span, exact=False, via=())})
        return self.passed_on(call)

    def passed_on(self, call: FlowCall) -> Value:
        """An unknown call's result: everything it was given."""
        found: set[Element] = set(self.value(call.receiver))
        for argument in call.arguments:
            found.update(self.value(argument))
        for _name, values in call.keywords:
            found.update(self.value(values))
        return frozenset(found)

    def argument(self, call: FlowCall, target: FlowUnit, parameter: int) -> tuple[str, ...]:
        """The origins a call passes to ``target``'s parameter (positional or keyword)."""
        position = parameter
        if target.bound_receiver and METHOD_PREFIX in call.callee:
            position -= 1
        origins: list[str] = []
        if position < 0:
            origins.extend(call.receiver)
        elif position < len(call.arguments):
            origins.extend(call.arguments[position])
        name = target.parameters[parameter]
        for keyword, values in call.keywords:
            if keyword == name:
                origins.extend(values)
        return tuple(origins)

    def substitute(self, call: FlowCall, target: Located, exact: bool) -> Value:
        """The call's result: the target's return summary with these arguments."""
        found: set[Element] = set()
        for element in self.analysis.returns[target.key]:
            if isinstance(element, Param):
                found.update(self.value(self.argument(call, target.unit, element.index)))
            elif len(element.via) < self.analysis.max_depth:
                via = (target.unit.name, *element.via)
                found.add(replace(element, exact=element.exact and exact, via=via))
        return frozenset(found)

    def sink_hits(self) -> Iterator[tuple[Value, SinkHit]]:
        file = self.located.file
        if self.analysis.mode.assert_sinks:
            skipped = self.analysis.mode.skipped_asserts[self.path]
            for checked in self.unit.asserts:
                if checked.span not in skipped:
                    text = file.source.excerpt(checked.span.line)
                    hit = SinkHit(file, checked.span, text, ASSERT_TARGET, 0, exact=True, via=())
                    yield self.value(checked.origins), hit
            return
        for call in self.unit.calls:
            positions, exact = sink_arguments(call.callee, self.aliases, self.catalog)
            for position in sorted(positions):
                if position < len(call.arguments):
                    value = self.value(call.arguments[position])
                    hit = SinkHit(
                        file, call.span, call.text, call.callee, position, exact=exact, via=()
                    )
                    yield value, hit

    def passed(self) -> Iterator[Passed]:
        for call in self.unit.calls:
            resolved = self.analysis.target(self.located, call)
            if resolved is None:
                continue
            target, exact = resolved
            for parameter in range(len(target.unit.parameters)):
                origins = self.argument(call, target.unit, parameter)
                if len(origins) > 0:
                    value = self.value(origins)
                    yield Passed(value, target, parameter, exact, call.span, call.text)


Reach = dict[tuple[str, int], list[SinkHit]]
Edges = dict[tuple[str, int], list[tuple[Located, int, bool]]]


class Analysis:
    """INPUT001 over every file: return summaries to a fixed point, then sinks."""

    def __init__(self, files: Sequence[FlowFile], graph: CallGraph, mode: Mode) -> None:
        self.sites = graph.sites
        self.mode = mode
        self.max_depth = mode.max_depth
        self.units = _index(files)
        self.catalogs = mode.catalogs
        self.aliases = {f.path: import_aliases(f.facts.imports, f.language) for f in files}
        self.returns: dict[str, Value] = {key: EMPTY for key in self.units}
        self.found: dict[tuple[str, Span, int, str, str, Span], tuple[Taint, SinkHit]] = {}

    def target(self, located: Located, call: FlowCall) -> tuple[Located, bool] | None:
        """The project function a call resolves to, and whether the resolution is exact."""
        key = (located.file.path, call.span)
        if key not in self.sites:
            return None
        resolution = self.sites[key]
        identifier = resolution.target.identifier
        if resolution.target.kind != TARGET_UNIT or identifier not in self.units:
            return None
        if resolution.confidence not in (CONFIDENCE_RESOLVED, CONFIDENCE_PROBABLE):
            return None
        target = self.units[identifier]
        if target.is_class:
            return None
        return target, resolution.confidence == CONFIDENCE_RESOLVED

    def summarize(self) -> None:
        for _round in range(self.max_depth + 1):
            changed = False
            for key, located in sorted(self.units.items()):
                evaluation = Evaluation(self, located)
                found: set[Element] = set()
                for returned in located.unit.returns:
                    found.update(evaluation.value(returned.origins))
                if frozenset(found) != self.returns[key]:
                    self.returns[key] = frozenset(found)
                    changed = True
            if not changed:
                return

    def reach(self) -> Reach:
        """For every (unit key, parameter): the sink arguments it reaches, transitively."""
        direct: Reach = {}
        edges: Edges = {}
        for key, located in sorted(self.units.items()):
            _parameter_flows(Evaluation(self, located), key, direct, edges)
        return _closure(direct, edges, self.max_depth)

    def report(self, taint: Taint, hit: SinkHit) -> None:
        if not hit.file.applies:
            return
        key = (hit.file.path, hit.span, hit.argument, taint.label, taint.path, taint.span)
        if key in self.found and len(self.found[key][0].via) <= len(taint.via):
            return
        self.found[key] = (taint, hit)

    def run(self) -> dict[str, list[Finding]]:
        self.summarize()
        self.collect(self.reach())
        return self.findings()

    def collect(self, reach: Reach) -> None:
        """Every (source, sink) pair: sources at a sink here, and through parameters."""
        for _key, located in sorted(self.units.items()):
            evaluation = Evaluation(self, located)
            for value, hit in evaluation.sink_hits():
                for element in value:
                    if isinstance(element, Taint):
                        self.report(element, hit)
            for passed in evaluation.passed():
                self.report_passed(passed, reach)

    def findings(self) -> dict[str, list[Finding]]:
        by_path: dict[str, list[Finding]] = {}
        if self.mode.assert_sinks:
            for taints, hit in self.by_assert():
                _add(by_path, hit.file.path, self.assert_finding(taints, hit))
        else:
            for taint, hit in self.found.values():
                _add(by_path, hit.file.path, self.finding(taint, hit))
        for findings in by_path.values():
            findings.sort(key=lambda f: (f.span, f.message))
        return by_path

    def report_passed(self, passed: Passed, reach: Reach) -> None:
        key = (passed.target.key, passed.parameter)
        if key not in reach:
            return
        for element in passed.value:
            if not isinstance(element, Taint):
                continue
            for hit in reach[key]:
                via = (*element.via, passed.target.unit.name, *hit.via)
                if len(via) > self.max_depth:
                    continue
                exact = element.exact and passed.exact and hit.exact
                self.report(replace(element, exact=exact, via=via), hit)

    def by_assert(self) -> list[tuple[list[Taint], SinkHit]]:
        """ASSERT001: every source that reaches one assert, so it is reported once."""
        grouped: dict[tuple[str, Span], tuple[list[Taint], SinkHit]] = {}
        for taint, hit in sorted(
            self.found.values(), key=lambda item: (item[1].span, item[0].span)
        ):
            key = (hit.file.path, hit.span)
            if key not in grouped:
                grouped[key] = ([], hit)
            grouped[key][0].append(taint)
        return list(grouped.values())

    def assert_finding(self, taints: Sequence[Taint], hit: SinkHit) -> Finding:
        origins = "; ".join(_origin(taint) for taint in taints)
        confidence = CONFIDENCE_APPROXIMATE
        if hit.exact and all(taint.exact for taint in taints):
            confidence = CONFIDENCE_EXACT
        message = (
            f"{hit.text} checks external input, {origins}: an expected failure is an error "
            "to raise, and python -O removes the assert"
        )
        return _finding(
            self.mode.rule,
            self.mode.severity,
            hit.file.path,
            hit.span,
            message,
            hit.file.source,
            confidence,
        )

    def finding(self, taint: Taint, hit: SinkHit) -> Finding:
        confidence = CONFIDENCE_APPROXIMATE
        if taint.exact and hit.exact:
            confidence = CONFIDENCE_EXACT
        through = ""
        if len(taint.via) > 0:
            through = f" (through {CROSSING.join(taint.via)})"
        message = (
            f"{taint.label} ({taint.path}:{taint.span.line}) reaches argument "
            f"{hit.argument + 1} of {hit.target}(...) without passing a validator"
            f"{through}: {hit.text}"
        )
        return _finding(
            self.mode.rule,
            self.mode.severity,
            hit.file.path,
            hit.span,
            message,
            hit.file.source,
            confidence,
        )


def _origin(taint: Taint) -> str:
    """``label (path:line)``, with the functions crossed."""
    through = ""
    if len(taint.via) > 0:
        through = f" (through {CROSSING.join(taint.via)})"
    return f"{taint.label} ({taint.path}:{taint.span.line}){through}"


def _parameter_flows(evaluation: Evaluation, key: str, direct: Reach, edges: Edges) -> None:
    """One unit's parameters that reach a sink here, or a project function's parameter."""
    for value, hit in evaluation.sink_hits():
        for element in value:
            if isinstance(element, Param):
                _add(direct, (key, element.index), hit)
    for passed in evaluation.passed():
        for element in passed.value:
            if isinstance(element, Param):
                _add(edges, (key, element.index), (passed.target, passed.parameter, passed.exact))


def _closure(direct: Reach, edges: Edges, depth: int) -> Reach:
    """Extend each parameter's sinks with those of the parameters it is passed to."""
    reach: Reach = {key: list(hits) for key, hits in direct.items()}
    for _round in range(depth):
        changed = False
        for start, targets in sorted(edges.items(), key=lambda item: item[0]):
            for target, parameter, exact in targets:
                if _extend(reach, start, (target.key, parameter), target, exact, depth):
                    changed = True
        if not changed:
            break
    return reach


def _extend(
    reach: Reach,
    start: tuple[str, int],
    into: tuple[str, int],
    target: Located,
    exact: bool,
    depth: int,
) -> bool:
    if into not in reach:
        return False
    changed = False
    for hit in list(reach[into]):
        if len(hit.via) + 1 > depth:
            continue
        extended = replace(hit, exact=hit.exact and exact, via=(target.unit.name, *hit.via))
        if start not in reach:
            reach[start] = []
        known = {(h.span, h.file.path, h.argument, h.via) for h in reach[start]}
        if (extended.span, extended.file.path, extended.argument, extended.via) not in known:
            reach[start].append(extended)
            changed = True
    return changed


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


def run_input001(
    files: Sequence[FlowFile], graph: CallGraph, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    """INPUT001 findings per path, for the files where the rule applies."""
    if not any(file.applies for file in files):
        return {}
    mode = Mode(
        rule=INPUT001,
        severity=str(settings["severity"]),
        max_depth=int(settings["max_depth"]),
        catalogs={f.path: catalog_for(settings, f.language) for f in files},
        assert_sinks=False,
        skipped_asserts={},
    )
    return Analysis(files, graph, mode).run()


def _assert_catalog(
    inputs: Mapping[str, Any], assertions: Mapping[str, Any], language: str
) -> Catalog:
    """External input for ASSERT001: request data, configuration reads and the listed
    file, network and command-line reads; nothing validates (an assert on int(x) still
    checks input), and the asserts themselves are the sinks."""
    prefix = _prefix(language)
    sources = {str(s) for s in inputs[f"{prefix}_sources"]}
    sources.update(str(r) for r in inputs[f"{prefix}_config_reads"])
    if language == PYTHON:
        sources.update(str(r) for r in assertions["external_reads"])
    return Catalog(
        sources=frozenset(sources), sinks={}, validators=frozenset(), issuer_prefixes=frozenset()
    )


def run_assert001(
    files: Sequence[FlowFile],
    graph: CallGraph,
    inputs: Mapping[str, Any],
    assertions: Mapping[str, Any],
) -> dict[str, list[Finding]]:
    """ASSERT001 (decision 28): an assert whose test depends on external input, traced
    like INPUT001 with the asserts as sinks. Internal invariants are never reported."""
    if not any(file.applies for file in files):
        return {}
    narrowing_allowed = assertions["allow_type_narrowing"] is True
    mode = Mode(
        rule=ASSERT001,
        severity=str(assertions["severity"]),
        max_depth=int(inputs["max_depth"]),
        catalogs={f.path: _assert_catalog(inputs, assertions, f.language) for f in files},
        assert_sinks=True,
        skipped_asserts={
            f.path: frozenset(
                a.span for a in f.facts.guardrails.asserts if narrowing_allowed and a.narrowing
            )
            for f in files
        },
    )
    return Analysis(files, graph, mode).run()


def _reads_optimize_flag(file: FlowFile) -> bool:
    aliases = import_aliases(file.facts.imports, file.language)
    for unit in file.facts.dataflow.units:
        for read in unit.reads:
            if not read.on_parameter and _matches(
                qualified_callee(read.text, aliases), frozenset({OPTIMIZE_FLAG})
            ):
                return True
    return False


def run_assert002(files: Sequence[FlowFile], severity: str) -> dict[str, list[Finding]]:
    """ASSERT002 (decision 28): production code relies on asserts (other than pure type
    narrowing) and no analyzed file reads sys.flags.optimize. One finding per run."""
    relying = sorted(
        (file.path, fact.span, file)
        for file in files
        if file.applies
        for fact in file.facts.guardrails.asserts
        if not fact.narrowing
    )
    if len(relying) == 0:
        return {}
    if any(f.language == PYTHON and _reads_optimize_flag(f) for f in files):
        return {}
    path, span, file = relying[0]
    count = len({path for path, _span, _file in relying})
    message = (
        f"production code relies on {len(relying)} assert(s) in {count} file(s), and no "
        f"analyzed code reads {OPTIMIZE_FLAG}: under python -O or PYTHONOPTIMIZE every one is "
        "removed; one startup check that refuses to run optimized makes them safe to rely on"
    )
    finding = _finding(ASSERT002, severity, path, span, message, file.source, CONFIDENCE_EXACT)
    return {path: [finding]}


# -- INPUT002 -----------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionalRead:
    origin: str
    span: Span
    text: str


def _optional_reads(
    unit: FlowUnit, aliases: Mapping[str, str], entries: frozenset[str], language: str
) -> list[OptionalRead]:
    """Python: a configured call given only the variable name (os.getenv("X")); JavaScript:
    a read below a configured object (process.env.X)."""
    found: list[OptionalRead] = []
    if language == PYTHON:
        for index, call in enumerate(unit.calls):
            qualified = qualified_callee(call.callee, aliases)
            if qualified in entries and len(call.arguments) == 1 and len(call.keywords) == 0:
                found.append(OptionalRead(origin(ORIGIN_CALL, index), call.span, call.text))
        return found
    for index, read in enumerate(unit.reads):
        if read.on_parameter:
            continue
        # Exactly the variable: process.env.HOME.length throws when HOME is unset.
        owner, dot, _name = read.text.rpartition(METHOD_PREFIX)
        if dot != "" and owner in entries:
            found.append(OptionalRead(origin(ORIGIN_READ, index), read.span, read.text))
    return found


def _uses(
    unit: FlowUnit, read: OptionalRead, aliases: Mapping[str, str], catalog: Catalog, language: str
) -> list[tuple[Span, str]]:
    uses: list[tuple[Span, str]] = []
    for call in unit.calls:
        given = [*call.arguments, *(values for _name, values in call.keywords)]
        if not any(read.origin in values for values in given):
            continue
        if language == PYTHON and is_validator(call.callee, aliases, catalog):
            continue  # int(None) raises: the missing variable fails loudly
        uses.append((call.span, f"is passed to {call.callee}(...)"))
    for returned in unit.returns:
        if read.origin in returned.origins:
            uses.append((returned.span, "is returned"))
    for stored in unit.stores:
        if read.origin in stored.origins:
            uses.append((stored.span, f"is stored in {stored.target}"))
    if language == PYTHON:
        # On the read's own line, DEF006 already reports the implicit None.
        uses = [use for use in uses if use[0].line != read.span.line]
    return sorted(uses)


def _is_assertion(callee: str, aliases: Mapping[str, str]) -> bool:
    """A call into node:assert (``assert(...)``, ``assert.ok``, ``strict.equal``): it
    throws when its condition fails, so what it is given is checked."""
    root = callee.partition(METHOD_PREFIX)[0]
    if root not in aliases:
        return False
    qualified = qualified_callee(callee, aliases)
    return qualified == ASSERT_MODULE or qualified.startswith(ASSERT_MODULE_BELOW)


def _asserted(unit: FlowUnit, aliases: Mapping[str, str]) -> frozenset[str]:
    """Every origin a node:assert call of the unit is given, through nested calls
    (``assert(["a", "b"].includes(name))`` checks ``name``)."""
    found: set[str] = set()
    pending: list[str] = []
    for call in unit.calls:
        if _is_assertion(call.callee, aliases):
            for values in (*call.arguments, *(v for _name, v in call.keywords)):
                pending.extend(values)
    while len(pending) > 0:
        item = pending.pop()
        if item in found:
            continue
        found.add(item)
        kind, index = origin_parts(item)
        if kind == ORIGIN_CALL:
            nested = unit.calls[index]
            pending.extend(nested.receiver)
            for values in nested.arguments:
                pending.extend(values)
    return frozenset(found)


def run_input002(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    aliases = import_aliases(facts.imports, language)
    catalog = catalog_for(settings, language)
    entries = frozenset(str(e) for e in settings[f"{_prefix(language)}_config_reads"])
    absent = ABSENT_JAVASCRIPT
    if language in ABSENT:
        absent = ABSENT[language]
    found: list[Finding] = []
    for unit in facts.dataflow.units:
        reads = _optional_reads(unit, aliases, entries, language)
        # A check on one read of a variable covers every read of it in the unit
        # (`process.env.X === undefined ? d : process.env.X`).
        asserted = _asserted(unit, aliases)
        checked = {
            read.text for read in reads if read.origin in unit.tested or read.origin in asserted
        }
        for read in reads:
            if read.text in checked:
                continue
            uses = _uses(unit, read, aliases, catalog, language)
            if len(uses) == 0:
                continue
            span, what = uses[0]
            message = (
                f"{read.text} is {absent} when the variable is unset, and the value {what} "
                f"without any check in {unit.name}: a missing variable travels on as a value"
            )
            found.append(
                _finding(
                    INPUT002,
                    str(settings["input002_severity"]),
                    path,
                    span,
                    message,
                    source,
                    CONFIDENCE_EXACT,
                )
            )
    return found


INPUT_RULES = (INPUT001, INPUT002)
