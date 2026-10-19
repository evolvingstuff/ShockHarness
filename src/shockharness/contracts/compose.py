"""Compositions and literals (spec §5.2a): the one place the analysis gives an operation
a meaning, and only because the catalog says so, with a reason.

A plain string literal carries every property marked ``literal_satisfies``. A
composition (an f-string, a template literal, a concatenation with a string literal in
it, ``str.format`` or ``%``, a join of written-out items or of a comprehension) carries
a rule's ``produces`` when every non-literal part satisfies one of the rules with that
``produces`` for its operation; literal parts are constants and are not checked. A part that is known not to satisfy any of them makes the
whole carry nothing (and the note names the part); a part whose set is unknown makes the
result unknown.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from shockharness.contracts.catalog import JAVASCRIPT, PYTHON, TYPESCRIPT, Catalog, Composition
from shockharness.contracts.python_flow import EMPTY, Part, PropSet, known_set

# A TypeScript file is composed by the JavaScript rules as well as its own.
SAME_RULES = {
    PYTHON: (PYTHON,),
    JAVASCRIPT: (JAVASCRIPT,),
    TYPESCRIPT: (TYPESCRIPT, JAVASCRIPT),
}


@dataclass(frozen=True)
class Outcome:
    """One ``produces`` of an operation: carried, unknown (``why``), or not (``why``)."""

    carried: bool
    exact: bool
    why: str


def _quoted(properties: frozenset[str]) -> str:
    return ", ".join(repr(p) for p in sorted(properties))


def _outcome(rules: Sequence[Composition], parts: Sequence[Part]) -> Outcome:
    uncertain = ""
    for part in parts:
        if any(rule.inputs_require <= part.value.known for rule in rules):
            continue
        if part.value.exact:
            needed = min((rule.inputs_require - part.value.known for rule in rules), key=sorted)
            return Outcome(
                carried=False,
                exact=True,
                why=f"the part {part.text} does not carry {_quoted(needed)}",
            )
        if uncertain == "":
            uncertain = f"the part {part.text}: {part.value.why}"
    if uncertain != "":
        return Outcome(carried=False, exact=False, why=uncertain)
    return Outcome(carried=True, exact=True, why="")


class Compositions:
    """The catalog's literal properties and composition rules for one language."""

    def __init__(self, catalog: Catalog, language: str) -> None:
        languages = SAME_RULES[language]
        self.literal = frozenset(p.name for p in catalog.properties.values() if p.literal_satisfies)
        self.rules: dict[str, dict[str, list[Composition]]] = {}
        for rule in catalog.compositions:
            if rule.language not in languages:
                continue
            if rule.operation not in self.rules:
                self.rules[rule.operation] = {}
            by_product = self.rules[rule.operation]
            if rule.produces not in by_product:
                by_product[rule.produces] = []
            by_product[rule.produces].append(rule)

    def literal_set(self) -> PropSet:
        """What a string literal with no interpolation carries."""
        return known_set(self.literal)

    def compose(self, operation: str, parts: Sequence[Part]) -> PropSet:
        if operation not in self.rules:
            return EMPTY  # no rule: an undeclared operation destroys every property
        carried: set[str] = set()
        exact = True
        notes: list[str] = []
        for produces, rules in sorted(self.rules[operation].items()):
            outcome = _outcome(rules, parts)
            if outcome.carried:
                carried.add(produces)
                continue
            exact = exact and outcome.exact
            notes.append(f"not {produces!r}: {outcome.why}")
        return replace(known_set(frozenset(carried)), exact=exact, why="; ".join(notes))
