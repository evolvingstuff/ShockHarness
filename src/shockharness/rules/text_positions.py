"""DOM003: a selection or caret saved as text positions and found again by walking text
nodes only (spec 21.1 decision 45).

The facts (``ir/javascript_positions.py``) say what each named function returns, which
parameters a text-node walk counts with, and what its calls pass on. Here, across files
and to a fixpoint: an **encoder** returns a point's text position (or an encoder's
result); a **decoder** walks text nodes only and counts with a parameter, or passes a
parameter on to a decoder's position. A call of a decoder whose position argument holds an
encoder's result (directly, through a local, or through a property the file stores one
under) is a round trip, reported at the call. Names resolve in the file, then through its
imports; ``obj.name(...)`` matches a function of that name anywhere (approximate).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import ModuleEdge
from shockharness.findings import CONFIDENCE_APPROXIMATE, STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    POSITION_CALL,
    POSITION_DIRECT,
    POSITION_PARAMETER,
    POSITION_PROPERTY,
    ImportFact,
    PositionCall,
    PositionFunction,
    PositionSource,
    TextPositionFacts,
)
from shockharness.rules.imports import imported_names
from shockharness.rules.registry import DOM003
from shockharness.source import SourceText

# A function: (the file that defines it, its name).
Key = tuple[str, str]
# A call as written: (the file it is in, the callee's name, obj.name(...)).
Site = tuple[str, str, bool]


@dataclass(frozen=True)
class PositionFile:
    path: str
    positions: TextPositionFacts
    imports: tuple[ImportFact, ...]
    source: SourceText
    applies: bool  # DOM003 applies to the file


class _Project:
    def __init__(self, files: Sequence[PositionFile], module_edges: Sequence[ModuleEdge]) -> None:
        self.functions: dict[Key, PositionFunction] = {}
        for f in files:
            for function in f.positions.functions:
                key = (f.path, function.name)
                if key not in self.functions:
                    self.functions[key] = function
        self.resolved = self._resolve(files, module_edges)
        self.encoders: set[Key] = set()
        self.decoders: dict[Key, int] = {}  # the position parameter
        self._summarize()

    def _resolve(
        self, files: Sequence[PositionFile], module_edges: Sequence[ModuleEdge]
    ) -> dict[Site, list[Key]]:
        """The functions every call may run: in the file, else through its imports; by
        name anywhere for obj.name(...)."""
        imported = imported_names([(f.path, f.imports) for f in files], module_edges)
        by_name: dict[str, list[Key]] = {}
        for key in sorted(self.functions):
            if key[1] not in by_name:
                by_name[key[1]] = []
            by_name[key[1]].append(key)
        resolved: dict[Site, list[Key]] = {}
        for site in _sites(files):
            path, name, member = site
            targets: list[Key] = []
            if member and name in by_name:
                targets.extend(by_name[name])
            elif not member and (path, name) in self.functions:
                targets.append((path, name))
            elif not member and (path, name) in imported:
                targets.append(imported[(path, name)])
            resolved[site] = targets
        return resolved

    def targets(self, path: str, name: str, member: bool) -> list[Key]:
        return self.resolved[(path, name, member)]

    def encodes(self, path: str, source: PositionSource) -> bool:
        """Whether the source holds a point's text position."""
        if source.kind == POSITION_DIRECT:
            return True
        if source.kind != POSITION_CALL or source.guarded:
            return False
        return any(t in self.encoders for t in self.targets(path, source.name, source.member))

    def decoder(self, path: str, call: PositionCall) -> tuple[Key, int] | None:
        """The decoder a call runs and its position parameter."""
        for target in self.targets(path, call.callee, call.member):
            if target in self.decoders and self.decoders[target] < len(call.arguments):
                return target, self.decoders[target]
        return None

    def _position(self, path: str, function: PositionFunction) -> int | None:
        if function.walks_text and len(function.counted_parameters) > 0:
            return function.counted_parameters[0]
        for call in function.calls:
            found = self.decoder(path, call)
            if found is None:
                continue
            for source in call.arguments[found[1]]:
                if source.kind == POSITION_PARAMETER:
                    return source.index
        return None

    def _summarize(self) -> None:
        changed = True
        while changed:
            changed = False
            for key, function in self.functions.items():
                path = key[0]
                if key not in self.encoders and any(
                    self.encodes(path, s) for s in function.returns
                ):
                    self.encoders.add(key)
                    changed = True
                if key in self.decoders:
                    continue
                position = self._position(path, function)
                if position is not None:
                    self.decoders[key] = position
                    changed = True


def _sites(files: Sequence[PositionFile]) -> set[Site]:
    """Every call the facts name: callees, and calls whose results are returned, passed
    or stored."""
    sites: set[Site] = set()
    for f in files:
        sources = [s for store in f.positions.stores for s in store.sources]
        for function in f.positions.functions:
            sources.extend(function.returns)
            for call in function.calls:
                sites.add((f.path, call.callee, call.member))
                sources.extend(s for argument in call.arguments for s in argument)
        sites.update((f.path, s.name, s.member) for s in sources if s.kind == POSITION_CALL)
    return sites


def _stored(project: _Project, file: PositionFile) -> set[str]:
    """The properties the file sets to a text position."""
    return {
        store.name
        for store in file.positions.stores
        if any(project.encodes(file.path, s) for s in store.sources)
    }


def _origin(
    project: _Project, file: PositionFile, stored: set[str], sources: Sequence[PositionSource]
) -> str | None:
    """How the argument holds a text position, for the message; None when it does not."""
    for source in sources:
        if source.kind == POSITION_DIRECT:
            return "a range's toString().length"
        if source.kind == POSITION_CALL and project.encodes(file.path, source):
            return f"{source.name}(...)"
        if source.kind == POSITION_PROPERTY and source.name in stored:
            return f"the property {source.name}, which this file sets to a text position"
    return None


def _finding(file: PositionFile, call: PositionCall, origin: str, severity: str) -> Finding:
    message = (
        f"{call.callee} finds a point again by walking text nodes only, from {origin}: a "
        "point next to an image or another non-text node has no text position of its own, "
        "so the round trip moves it to the nearest text or finds nothing"
    )
    return Finding(
        rule_id=DOM003.rule_id,
        rule_version=DOM003.version,
        severity=severity,
        path=file.path,
        span=call.span,
        message=message,
        evidence=file.source.excerpt(call.span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=DOM003.remediation,
        safe_autofix=False,
        scope=call.callee,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _round_trips(project: _Project, file: PositionFile, severity: str) -> list[Finding]:
    found: list[Finding] = []
    stored = _stored(project, file)
    for function in file.positions.functions:
        for call in function.calls:
            decoded = project.decoder(file.path, call)
            if decoded is None:
                continue
            origin = _origin(project, file, stored, call.arguments[decoded[1]])
            if origin is not None:
                found.append(_finding(file, call, origin, severity))
    return found


def run_dom003(
    files: Sequence[PositionFile], module_edges: Sequence[ModuleEdge], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    project = _Project(files, module_edges)
    if len(project.decoders) == 0:
        return {}
    severity = str(settings["dom003_severity"])
    found: dict[str, list[Finding]] = {}
    for file in files:
        if file.applies:
            round_trips = _round_trips(project, file, severity)
            if len(round_trips) > 0:
                found[file.path] = round_trips
    return found
