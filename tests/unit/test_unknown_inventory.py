"""Milestone H1: the inventory of findings whose verdict rests on missing information.

Two halves, both recorded in STATUS.md (Milestone H1, "Unresolved-finding inventory"):

* :data:`SITES` lists every function in ``src/shockharness`` that produces or consumes an
  ``unresolved`` confidence, an ``opaque`` handler body or the ``unknown`` status, or that
  constructs a :class:`Finding`, with the decision taken there. A new such function makes
  :func:`test_every_site_is_inventoried` fail until its status decision is recorded here
  and in STATUS.md.
* :data:`CASES` is one snippet per kind of finding the inventory names, with the status
  assigned to it; the golden corpus's unknown findings are pinned in :data:`CORPUS_UNKNOWN`.
"""

import ast
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.findings import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    STATUS_UNKNOWN,
    STATUS_VIOLATION,
)
from tests.conftest import FIXTURES, REPO_ROOT, fixture_config, language_for_fixture

SOURCE_ROOT = REPO_ROOT / "src" / "shockharness"
MARKERS = frozenset({"CONFIDENCE_UNRESOLVED", "BODY_OPAQUE", "STATUS_UNKNOWN"})
FINDING_CONSTRUCTOR = "Finding()"
OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)

# (module, function) -> (markers it references, the decision taken there).
SITES: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    # Producers of unresolved identities (facts, not findings).
    ("ir/python_catches.py", "SymbolTable._bind_statement"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "a rebound name resolves as unresolved; EXC001 decides (unknown)",
    ),
    ("ir/python_catches.py", "SymbolTable.resolve_name"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "an unbound name resolves as unresolved; EXC001 decides (unknown)",
    ),
    ("ir/python_catches.py", "resolve_identity"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "a non-dotted or unbound type expression is unresolved; EXC001 decides (unknown)",
    ),
    ("ir/python_catches.py", "_resolve_callee"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "an unresolved manager callee; matched by bare name as approximate, never unknown",
    ),
    ("ir/javascript_catches.py", "_rejection_handler"): (
        frozenset({"BODY_OPAQUE"}),
        "a rejection handler reference this module does not define is opaque; EXC001 unknown",
    ),
    # EXC001: where the status is decided.
    ("rules/exceptions.py", "_name_matches"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "an unresolved identity never matches a boundary (fails closed)",
    ),
    ("rules/exceptions.py", "_bare_problem"): (
        frozenset({"BODY_OPAQUE"}),
        "message only: an opaque handler's own explanation",
    ),
    ("rules/exceptions.py", "bare_status"): (
        frozenset({"BODY_OPAQUE", "STATUS_UNKNOWN"}),
        "untyped catch: opaque handler or manager -> unknown; bare except, untyped catch "
        "clause, inline rejection handler -> violation",
    ),
    ("rules/exceptions.py", "evaluate_approval"): (
        frozenset({"CONFIDENCE_UNRESOLVED", "STATUS_UNKNOWN"}),
        "typed catch: only unresolved identities in the way -> unknown; any resolved "
        "identity no boundary approves -> violation",
    ),
    ("rules/exceptions.py", "_manager_match"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "an unresolved manager callee is matched by bare name (approximate), not unknown",
    ),
    ("rules/exceptions.py", "_unresolved"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "a with-name whose manager binding cannot be established: opaque, unknown",
    ),
    ("rules/exceptions.py", "manager_catches"): (
        frozenset({"BODY_OPAQUE"}),
        "builds the opaque catch for an unestablished manager binding (unknown)",
    ),
    ("rules/exceptions.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "EXC001 takes the approval's status; EXC002 and EXC003 are always violation",
    ),
    # DEF001-DEF006.
    ("rules/defaults.py", "fact_status"): (
        frozenset({"STATUS_UNKNOWN"}),
        "DEF002 mapping lookup on a receiver not proven a mapping -> unknown",
    ),
    ("rules/defaults.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "takes fact_status; DEF005 is always violation",
    ),
    # Rules that are always violation.
    ("rules/magic_numbers.py", "run_magic001"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "MAGIC001 is exact: violation",
    ),
    ("rules/complexity.py", "_finding_at"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "CPLX001-CPLX006 measure what was resolved: violation (unresolved calls are listed "
        "in the CPLX005 message and never counted)",
    ),
    # VERIFY001, VERIFY002, VERIFY004 (H2).
    ("rules/verification.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR, "STATUS_UNKNOWN", "CONFIDENCE_UNRESOLVED"}),
        "violation when the base version of the file is known; unknown (confidence "
        "unresolved) when the base version could not be analyzed, or when rename detection "
        "failed and the file has no base version under its own path",
    ),
    # H4: ASYNC001 through a probable call-graph edge (the callee matched by name only)
    # is unknown; every other ASYNC finding is a violation.
    ("rules/async_lifecycle.py", "_async_callee"): (
        frozenset({"STATUS_UNKNOWN", "CONFIDENCE_UNRESOLVED"}),
        "violation for a catalog API or a resolved async callee; unknown (confidence "
        "unresolved) when the call graph matched the async callee by name only",
    ),
    ("rules/async_lifecycle.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "the status is decided by the caller (_async001, _async002, _async003)",
    ),
    # H3: every guardrail finding is a violation (the facts are exact syntax; STATE001's
    # approximate confidence concerns aliasing, not whether the binding is written).
    ("rules/guardrails.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001: violation",
    ),
    # VERIFY003 (H2 part 2).
    ("rules/policy_integrity.py", "_finding"): (
        frozenset({FINDING_CONSTRUCTOR, "STATUS_UNKNOWN", "CONFIDENCE_UNRESOLVED"}),
        "violation when both sides of the comparison were read; unknown (confidence "
        "unresolved) when a configuration, tool configuration or baseline of either "
        "revision could not be read or parsed",
    ),
    ("suppressions.py", "_problem_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "SUPP001 is exact: violation",
    ),
    ("suppressions.py", "_unused_finding"): (
        frozenset({FINDING_CONSTRUCTOR}),
        "SUPP002 is exact: violation",
    ),
    # Unresolved call and module edges: metrics, never findings.
    ("complexity/callgraph.py", "_ModuleIndex.python_relative"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "_ModuleIndex.javascript"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "resolve_module_edges"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "_Resolver._imported"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "_Resolver.resolve_name"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "_Resolver.resolve_attribute"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/callgraph.py", "_classify"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "graph edge confidence; no finding",
    ),
    ("complexity/coupling.py", "UnitCoupling.to_json_dict"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "unresolved call count in metrics.graph; no finding",
    ),
    ("complexity/coupling.py", "unit_coupling"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "fan-out counts resolved edges only; CPLX005 stays violation",
    ),
    ("complexity/coupling.py", "GraphMetrics.to_json_dict"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "edge summary in metrics.graph; no finding",
    ),
    ("complexity/coupling.py", "disabled_graph"): (
        frozenset({"CONFIDENCE_UNRESOLVED"}),
        "edge summary in metrics.graph; no finding",
    ),
    # The status model itself.
    ("findings.py", "Finding.is_unknown"): (frozenset({"STATUS_UNKNOWN"}), "the predicate"),
}


def _scan_function(node: ast.AST) -> frozenset[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in MARKERS:
            found.add(child.id)
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "Finding"
        ):
            found.add(FINDING_CONSTRUCTOR)
    return frozenset(found)


def scan_sites() -> dict[tuple[str, str], frozenset[str]]:
    """Every function (methods by ``Class.name``) under src/ that references a marker."""
    sites: dict[tuple[str, str], frozenset[str]] = {}

    def visit(node: ast.AST, module: str, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                markers = _scan_function(child)
                if len(markers) > 0:
                    sites[(module, prefix + child.name)] = markers
                visit(child, module, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, module, f"{prefix}{child.name}.")

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        module = path.relative_to(SOURCE_ROOT).as_posix()
        visit(ast.parse(path.read_text(encoding="utf-8")), module, "")
    return sites


def test_every_site_is_inventoried() -> None:
    scanned = scan_sites()
    missing = sorted(set(scanned) - set(SITES))
    assert missing == [], (
        f"new place(s) that produce an unresolved/opaque state, decide a status or build a "
        f"Finding: {missing}; record the status decision in SITES and in STATUS.md"
    )
    stale = sorted(set(SITES) - set(scanned))
    assert stale == [], f"inventory entries that no longer exist: {stale}"
    for site, (markers, _decision) in SITES.items():
        assert scanned[site] == markers, (site, scanned[site])


# (name, language, source, rule, confidence, status). One entry per kind of finding the
# inventory names; ``boundary`` cases are analyzed with ValueError approved for src/**.
CASES: list[tuple[str, str, str, str, str, str]] = [
    (
        "bare except",
        "python",
        "def f(g):\n    try:\n        g()\n    except:\n        raise\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_VIOLATION,
    ),
    (
        "untyped catch clause",
        "javascript",
        "function f(g) {\n  try {\n    g();\n  } catch (err) {\n    throw err;\n  }\n}\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_VIOLATION,
    ),
    (
        "inline rejection handler",
        "javascript",
        "export function f(p) {\n  return p.catch((err) => {\n    throw err;\n  });\n}\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_VIOLATION,
    ),
    (
        "opaque rejection handler",
        "javascript",
        'import { onError } from "./errors.js";\nexport function f(p) {\n'
        "  return p.catch(onError);\n}\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "unbound exception name",
        "python",
        "def f(g):\n    try:\n        g()\n    except MissingError:\n        raise\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "dynamic exception expression",
        "python",
        "def f(g, h):\n    try:\n        g()\n    except h():\n        raise\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "unresolved and refused identities",
        "python",
        "def f(g):\n    try:\n        g()\n    except (MissingError, KeyError):\n        raise\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_VIOLATION,
    ),
    (
        "manager without a readable type",
        "python",
        "import contextlib\n\n\ndef f(g, errors):\n"
        "    with contextlib.suppress(*errors):\n        g()\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "manager with an unresolved type",
        "python",
        "import contextlib\n\n\ndef f(g):\n"
        "    with contextlib.suppress(MissingError):\n        g()\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "manager binding not established",
        "python",
        "import contextlib\n\n\ndef f(g, h):\n    m = contextlib.suppress(KeyError)\n"
        "    m = h()\n    with m:\n        g()\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
    (
        "resolved exception without a boundary",
        "python",
        "def f(g):\n    try:\n        g()\n    except KeyError:\n        raise\n",
        "EXC001",
        CONFIDENCE_EXACT,
        STATUS_VIOLATION,
    ),
    (
        "lookup on an unproven receiver",
        "python",
        'def f(session):\n    return session.get("key", None)\n',
        "DEF002",
        CONFIDENCE_APPROXIMATE,
        STATUS_UNKNOWN,
    ),
    (
        "implicit lookup on an unproven receiver",
        "python",
        'def f(session):\n    return session.get("key")\n',
        "DEF002",
        CONFIDENCE_APPROXIMATE,
        STATUS_UNKNOWN,
    ),
    (
        "pop on an unproven receiver",
        "python",
        'def f(table):\n    return table.pop("key", None)\n',
        "DEF002",
        CONFIDENCE_APPROXIMATE,
        STATUS_UNKNOWN,
    ),
    (
        "lookup on a proven mapping",
        "python",
        "def f(key):\n    table = {}\n    return table.get(key, None)\n",
        "DEF002",
        CONFIDENCE_EXACT,
        STATUS_VIOLATION,
    ),
    (
        "non-constant truthiness fallback",
        "python",
        "def f(a, b):\n    return a or b\n",
        "DEF003",
        CONFIDENCE_APPROXIMATE,
        STATUS_VIOLATION,
    ),
]

BOUNDARY_CASES: list[tuple[str, str, str, str, str, str]] = [
    (
        "unresolved identity next to an approved one",
        "python",
        "def f(g):\n    try:\n        g()\n    except (MissingError, ValueError):\n        raise\n",
        "EXC001",
        CONFIDENCE_UNRESOLVED,
        STATUS_UNKNOWN,
    ),
]
BOUNDARY_TOML = (
    "[[tool.shockharness.rules.exceptions.boundaries]]\n"
    'path = "src/**"\nlanguage = "python"\nexception = "ValueError"\n'
    'reason = "test boundary"\n'
)


def _only_finding(
    config: EffectiveConfig, language: str, source: str, rule_id: str
) -> tuple[str, str]:
    suffix = ".py" if language == "python" else ".js"
    result = analyze_text(f"src/case{suffix}", language, source, config, OPTIONS)
    found = [f for f in result.findings if f.rule_id == rule_id]
    assert len(found) == 1, [(f.rule_id, f.message) for f in result.findings]
    return found[0].confidence, found[0].status


@pytest.mark.parametrize(
    ("name", "language", "source", "rule_id", "confidence", "status"),
    CASES,
    ids=[c[0] for c in CASES],
)
def test_inventory_case(
    name: str,
    language: str,
    source: str,
    rule_id: str,
    confidence: str,
    status: str,
    strict_config: EffectiveConfig,
) -> None:
    assert _only_finding(strict_config, language, source, rule_id) == (confidence, status), name


@pytest.mark.parametrize(
    ("name", "language", "source", "rule_id", "confidence", "status"),
    BOUNDARY_CASES,
    ids=[c[0] for c in BOUNDARY_CASES],
)
def test_inventory_boundary_case(
    name: str,
    language: str,
    source: str,
    rule_id: str,
    confidence: str,
    status: str,
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(BOUNDARY_TOML)
    assert _only_finding(config, language, source, rule_id) == (confidence, status), name


# Every unknown finding of the golden corpus (strict, each fixture with its own settings).
CORPUS_UNKNOWN = [
    ("javascript/exc_promise_catch.js", "EXC001", 10, 12),
    ("python/def_mapping_get.py", "DEF002", 19, 13),
    ("python/def_mapping_get.py", "DEF002", 20, 12),
    ("python/def_mapping_get.py", "DEF002", 35, 13),
    ("python/exc_unresolved.py", "EXC001", 18, 5),
    ("python/exc_unresolved.py", "EXC001", 25, 5),
    ("python/exc_unresolved.py", "EXC001", 32, 5),
    ("python/exc_unresolved.py", "EXC001", 39, 5),
]


def test_golden_corpus_unknown_findings(tmp_path: Path) -> None:
    expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    unknown: list[tuple[str, str, int, int]] = []
    unresolved_rules: set[str] = set()
    for index, name in enumerate(sorted(expected)):
        root = tmp_path / str(index)
        root.mkdir()
        config = fixture_config(name, expected[name], root)
        text = (FIXTURES / name).read_text(encoding="utf-8")
        result = analyze_text(name, language_for_fixture(name), text, config, OPTIONS)
        for finding in result.findings:
            if finding.confidence == CONFIDENCE_UNRESOLVED:
                unresolved_rules.add(finding.rule_id)
            if finding.is_unknown:
                unknown.append((name, finding.rule_id, finding.span.line, finding.span.column))
    assert unknown == CORPUS_UNKNOWN
    assert unresolved_rules == {"EXC001"}
