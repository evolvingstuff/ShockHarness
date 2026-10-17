"""Names a file imports from another analyzed file, through the module graph's resolved
import edges (STUB003's base classes, DOM002's selector constants)."""

from collections.abc import Sequence

from shockharness.complexity.callgraph import ModuleEdge
from shockharness.ir.model import ImportFact

# A definition: (the path that defines it, its name there); "" for a whole module.
ClassKey = tuple[str, str]
WILDCARD = "*"


def imported_names(
    files: Sequence[tuple[str, Sequence[ImportFact]]], module_edges: Sequence[ModuleEdge]
) -> dict[tuple[str, str], ClassKey]:
    """(path, local name) -> (the file it comes from, the name there), for every name a
    file imports from an analyzed file; a whole-module import maps to (file, "")."""
    targets = {
        (edge.source, edge.span): edge.target for edge in module_edges if edge.target is not None
    }
    found: dict[tuple[str, str], ClassKey] = {}
    for path, imports in files:
        for fact in imports:
            if (path, fact.span) not in targets:
                continue
            target = targets[(path, fact.span)]
            for imported, local in fact.names:
                if imported != WILDCARD:
                    found[(path, local)] = (target, imported)
    return found
