"""What one file's property-contract findings depend on, so a later run can reuse them
while none of it changed (the incremental contracts phase).

A file's findings come from its own units and from everything the analysis consulted
for them: each module a name or a path resolved to (or that it resolved to nothing),
the text of each of those modules, each existence check of a JavaScript path, and, when
an override check ran, the classes of every analyzed module. The analysis memoizes units,
contracts and results across files; each memoized entry keeps the dependencies it was
computed with, and a file that reuses the entry takes them on (``Tracker.add``).
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class Deps:
    names: dict[str, str]  # a name resolved (Python dotted, JavaScript path) -> path or ""
    probes: dict[str, bool]  # a JavaScript path -> whether it was a project file
    paths: set[str]  # the modules whose text the findings depend on
    classes: bool  # an override check consulted every analyzed class

    def merge(self, other: "Deps") -> None:
        self.names.update(other.names)
        self.probes.update(other.probes)
        self.paths.update(other.paths)
        if other.classes:
            self.classes = True


def no_deps() -> Deps:
    return Deps({}, {}, set(), classes=False)


class Tracker:
    """A stack of open frames: every dependency recorded goes into each of them."""

    def __init__(self) -> None:
        self.frames: list[Deps] = []

    def push(self) -> None:
        self.frames.append(no_deps())

    def pop(self) -> Deps:
        """Close the innermost frame; the enclosing frames take its dependencies."""
        closed = self.frames.pop()
        self.add(closed)
        return closed

    def add(self, deps: Deps) -> None:
        for frame in self.frames:
            frame.merge(deps)

    def name(self, name: str, path: str) -> None:
        for frame in self.frames:
            frame.names[name] = path
            if path != "":
                frame.paths.add(path)

    def path(self, path: str) -> None:
        for frame in self.frames:
            frame.paths.add(path)

    def probe(self, path: str, found: bool) -> None:
        for frame in self.frames:
            frame.probes[path] = found

    def classes(self) -> None:
        for frame in self.frames:
            frame.classes = True


def plain_deps(deps: Deps) -> dict[str, object]:
    return {
        "names": dict(sorted(deps.names.items())),
        "probes": dict(sorted(deps.probes.items())),
        "paths": sorted(deps.paths),
        "classes": deps.classes,
    }


def deps_from(
    names: Mapping[str, str], probes: Mapping[str, bool], paths: list[str], classes: bool
) -> Deps:
    return Deps(dict(names), dict(probes), set(paths), classes=classes)
