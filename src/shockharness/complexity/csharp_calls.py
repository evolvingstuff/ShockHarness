"""C# call resolution (milestone G3): a project-wide type index over the C# files and the
receiver facts they record (ir/csharp_receivers.py).

C# imports namespaces, not files, so a call is resolved by the types the syntax states,
not by imports:

* ``M()`` and ``this.M()``: a method of the enclosing class, its ``partial`` declarations
  in every file included, or of a project base class.
* ``base.M()``: a method of a project base class.
* ``Type.M()``: a method of a project class ``Type`` (a static call).
* ``x.M()`` and ``x.y.M()``: ``x`` a parameter, local, field or property whose type the
  syntax states, ``y`` a field or property of that type.
* ``new T(...)``: the constructor of a project class ``T``, else its class body.

Names are simple: two project classes of one name in different namespaces are both
candidates, and the call is probable. Everything else (a library call, a method of a
generic parameter, an extension method) stays unresolved, and the dead-code rules match
it by name.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from shockharness.complexity.metrics import UnitMetrics
from shockharness.ir.model import (
    CALL_ARGUMENT,
    CALL_ATTRIBUTE,
    CALL_NAME,
    CALL_NEW,
    MODULE_SCOPE,
    CallSite,
    ReceiverClass,
)

RESOLVED = "resolved"
PROBABLE = "probable"
UNRESOLVED = "unresolved"
THIS = "this"
BASE = "base"
HIERARCHY_DEPTH = 8


@dataclass(frozen=True)
class CSharpModule:
    path: str
    units: tuple[UnitMetrics, ...]
    classes: tuple[ReceiverClass, ...]
    typed: tuple[tuple[str, str, str], ...]  # (unit name, name, type)


@dataclass(frozen=True)
class CSharpResolution:
    """A unit key (``unit`` set) or nothing found (``unit`` None); ``owner`` is the
    class the target belongs to, for the type dependency between files."""

    unit: str | None
    owner: str | None
    confidence: str
    reason: str


def _final(name: str) -> str:
    _head, _dot, last = name.rpartition(".")
    return last


def _add(table: dict[str, list[str]], key: str, value: str) -> None:
    if key not in table:
        table[key] = []
    if value not in table[key]:
        table[key].append(value)


class CSharpIndex:
    """The project's classes (``partial`` declarations merged by name), their methods'
    units, and the types of the names each unit and class declares."""

    def __init__(self, modules: Sequence[CSharpModule]) -> None:
        self.classes: dict[str, list[str]] = {}  # simple name -> qualified names
        self.bases: dict[str, list[str]] = {}  # qualified name -> base simple names
        self.units: dict[str, list[str]] = {}  # qualified unit name -> keys
        self.class_paths: dict[str, list[str]] = {}  # qualified class name -> files
        self.typed: dict[tuple[str, str], str] = {}  # (unit or class name, name) -> type
        for module in modules:
            for cls in module.classes:
                _add(self.classes, _final(cls.name), cls.name)
                _add(self.class_paths, cls.name, module.path)
                for base in cls.bases:
                    _add(self.bases, cls.name, base)
            for unit in module.units:
                _add(self.units, unit.name, unit.key)
            for unit_name, name, typed in module.typed:
                self.typed[(unit_name, name)] = typed

    def class_named(self, written: str) -> list[str]:
        """The project classes a written type name may be (``Inner``, ``Outer.Inner``)."""
        if written in self.class_paths:
            return [written]
        final = _final(written)
        if final in self.classes:
            return list(self.classes[final])
        return []

    def method(self, cls: str, name: str) -> tuple[list[str], str | None]:
        """The units of ``cls.name`` in the class or its project bases, nearest first,
        and the class that declares them."""
        for current in self.lineage(cls):
            qualified = f"{current}.{name}"
            if qualified in self.units:
                return list(self.units[qualified]), current
        return [], None

    def lineage(self, cls: str) -> list[str]:
        """``cls`` and its project ancestors, nearest first, at most HIERARCHY_DEPTH deep."""
        order: list[str] = []
        pending = [cls]
        for _depth in range(HIERARCHY_DEPTH):
            fresh = [c for c in pending if c not in order]
            order.extend(fresh)
            pending = [p for c in fresh for p in self._parents(c)]
        return order

    def _parents(self, cls: str) -> list[str]:
        if cls not in self.bases:
            return []
        return [found for base in self.bases[cls] for found in self.class_named(base)]

    def member_type(self, cls: str, name: str) -> str | None:
        """The type of field or property ``name`` of ``cls`` or a project base."""
        for current in self.lineage(cls):
            if (current, name) in self.typed:
                return self.typed[(current, name)]
        return None


def _found(units: list[str], owner: str | None, reason: str, exact: bool) -> CSharpResolution:
    if len(units) == 0:
        return CSharpResolution(None, None, UNRESOLVED, reason)
    confidence = RESOLVED if exact and len(units) == 1 else PROBABLE
    return CSharpResolution(units[0], owner, confidence, reason)


NOT_FOUND = CSharpResolution(None, None, UNRESOLVED, "not a method of a project class")


class CSharpResolver:
    def __init__(self, index: CSharpIndex) -> None:
        self.index = index

    def enclosing_class(self, unit: UnitMetrics) -> str | None:
        """The class a unit is in: its own class for a method, the nearest enclosing
        class for a local function or lambda (``Player._Ready.twice`` is in ``Player``)."""
        if unit.fact.class_name is not None:
            return unit.fact.class_name
        name = unit.name
        while name not in (MODULE_SCOPE, ""):
            if name in self.index.class_paths:
                return name
            name, _dot, _last = name.rpartition(".")
        return None

    def name_type(self, unit: UnitMetrics, name: str) -> str | None:
        """The stated type of a name visible in ``unit``: its own or an enclosing
        function's parameter or local, else a field or property of its class."""
        scope = unit.name
        while scope not in (MODULE_SCOPE, ""):
            if (scope, name) in self.index.typed:
                return self.index.typed[(scope, name)]
            scope, _dot, _last = scope.rpartition(".")
        cls = self.enclosing_class(unit)
        if cls is None:
            return None
        return self.index.member_type(cls, name)

    def resolve(self, unit: UnitMetrics, call: CallSite) -> CSharpResolution:
        if call.shape in (CALL_NAME, CALL_ARGUMENT):
            return self._name(unit, call.callee)
        if call.shape == CALL_NEW:
            return self._new(call.callee)
        if call.shape == CALL_ATTRIBUTE:
            return self._dotted(unit, call.callee.split("."))
        return CSharpResolution(None, None, UNRESOLVED, "computed callee")

    def _name(self, unit: UnitMetrics, name: str) -> CSharpResolution:
        nested = f"{unit.name}.{name}"
        if nested in self.index.units:
            return _found(
                self.index.units[nested], None, "local function of the calling unit", exact=True
            )
        cls = self.enclosing_class(unit)
        if cls is None:
            return NOT_FOUND
        units, owner = self.index.method(cls, name)
        return _found(units, owner, "method of the enclosing class or a project base", exact=True)

    def _new(self, written: str) -> CSharpResolution:
        candidates = self.index.class_named(written)
        for cls in candidates:
            constructor = f"{cls}.{_final(cls)}"
            if constructor in self.index.units:
                return _found(
                    self.index.units[constructor], cls, "constructor", exact=len(candidates) == 1
                )
        for cls in candidates:
            if cls in self.index.units:
                return _found(
                    self.index.units[cls], cls, "class without a declared constructor", exact=False
                )
        return CSharpResolution(None, None, UNRESOLVED, "not a project class")

    def _dotted(self, unit: UnitMetrics, parts: list[str]) -> CSharpResolution:
        root, *rest = parts
        if len(rest) == 0:
            return NOT_FOUND
        *path, method = rest
        cls = self._root_class(unit, root)
        if cls is None:
            return NOT_FOUND
        for member in path:
            member_class = self._member_class(cls, member)
            if member_class is None:
                return NOT_FOUND
            cls = member_class
        units, owner = self.index.method(cls, method)
        return _found(
            units, owner, f"method of {cls}, the receiver's stated type", exact=root != BASE
        )

    def _member_class(self, cls: str, member: str) -> str | None:
        """The project class of field or property ``member`` of ``cls``."""
        typed = self.index.member_type(cls, member)
        if typed is None:
            return None
        found = self.index.class_named(typed)
        return found[0] if len(found) > 0 else None

    def _root_class(self, unit: UnitMetrics, root: str) -> str | None:
        """The class a dotted call's first segment stands for."""
        own = self.enclosing_class(unit)
        if root == THIS:
            return own
        if root == BASE:
            if own is None or own not in self.index.bases:
                return None
            for base in self.index.bases[own]:
                found = self.index.class_named(base)
                if len(found) > 0:
                    return found[0]
            return None
        typed = self.name_type(unit, root)
        if typed is not None:
            found = self.index.class_named(typed)
            return found[0] if len(found) > 0 else None
        statics = self.index.class_named(root)
        return statics[0] if len(statics) > 0 else None
