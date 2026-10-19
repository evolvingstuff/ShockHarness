"""Property contracts, Python (milestones P1a, P1b): PROP001, PROP003, PROP005, PROP006,
PROP007.

Every function of a file the rules apply to (and the module body) is walked once with
:mod:`shockharness.contracts.python_flow`. A call that resolves to a project function is
checked against that function's own declared contract, read directly (one hop, spec
§5.3): the ``requires`` at the top of its body, and the result set of its own returns,
computed with every further project call inside it unknown. A function with no
``produces``/``preserves`` declares no result: its result carries nothing. A call whose
resolved reference is a catalog sink (``callee:N``) is checked at that argument; a
keyword argument maps to its position for a project callee and is unknown for a library
callee. An assignment to a catalog target (``obj.html = v``, ``headers[k] = v``) is checked
at the value. String literals, f-strings, concatenations and formats carry what the
catalog's ``literal_satisfies`` and composition rules say (:mod:`..contracts.compose`).
Contracts are inferred from the body, never from a separate declaration.
"""

import ast
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.contracts.catalog import (
    JAVASCRIPT,
    PRESERVES,
    PRESERVES_EXCEPT,
    PRODUCES,
    PYTHON,
    REQUIRES,
    TYPESCRIPT,
    CalleeSink,
    TargetSink,
    javascript_runtime_modules,
    load_catalog,
    python_runtime_modules,
    static_properties,
)
from shockharness.contracts.compose import Compositions
from shockharness.contracts.deps import Deps, Tracker
from shockharness.contracts.disk import DiskLog, new_log
from shockharness.contracts.javascript_index import JsProjectIndex
from shockharness.contracts.python_flow import (
    EMPTY,
    UNBOUND,
    Declaration,
    Env,
    Part,
    PropSet,
    Summary,
    coroutine,
    generator,
    known_set,
    run_unit,
    unknown,
)
from shockharness.contracts.python_index import (
    LIBRARY,
    NO_RECEIVERS,
    RUNTIME,
    UNIT,
    UNKNOWN,
    Module,
    ProjectIndex,
    Receivers,
    Target,
    receivers_of,
)
from shockharness.contracts.report import (
    ASSIGNED,
    PASSED,
    Considered,
    ContractFile,
    Issue,
    Located,
    Reporter,
    Requirement,
    inconsistent_returns,
    quoted,
)
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import Span
from shockharness.ir.python_catches import node_span
from shockharness.rules.defaults import module_names
from shockharness.rules.property_contracts_javascript import (
    javascript_considered,
    run_javascript_contracts,
)
from shockharness.rules.registry import (
    PROP001,
    PROP002,
    PROP003,
    PROP004,
    PROP005,
    PROP006,
    PROP007,
    PROP008,
)
from shockharness.source import SourceText

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# requires(value, ...) / produces(value, ...); preserves(result, source[, ...]).
VALUE_ONLY = 1
RESULT_AND_SOURCE = 2
RESULT_DECLARATIONS = (PRODUCES, PRESERVES, PRESERVES_EXCEPT)
JOIN = "join"
STATICMETHOD = "staticmethod"
SCRIPT_LANGUAGES = (JAVASCRIPT, TYPESCRIPT)
ENABLE = "enable"
ENABLE_ARGUMENTS = 2  # enable(mode, static_properties)


@dataclass(frozen=True)
class Header:
    """A function's parameter requirements: the requires statements at its top."""

    requirements: Mapping[str, frozenset[str]]
    calls: frozenset[ast.Call]
    misplaced: tuple[Declaration, ...]


@dataclass(frozen=True)
class Unit:
    module: Module
    function: ast.FunctionDef | ast.AsyncFunctionDef | None  # None: the module body
    body: Sequence[ast.stmt]
    nodes: tuple[ast.AST, ...]  # the unit's own nodes, collected once (own_nodes)
    stored: frozenset[str]  # every name the body binds (global declarations included)
    local: frozenset[str]  # names bound in a function: a call through one is unknown
    receivers: Receivers  # the method's self / cls and the locals it constructs
    bound: frozenset[str]  # names the unit binds: unbound until a path binds them
    read: frozenset[str]  # names the unit reads
    parameters: tuple[str, ...]
    declarations: Mapping[ast.Call, Declaration]
    issues: tuple[Issue, ...]  # PROP003 and PROP006, from the declarations
    header: Header
    # Parameters that require nothing, are never rebound, and are the source of a
    # preserves: the result is parametric in them (decision 48).
    parametric: frozenset[str]


@dataclass(frozen=True)
class Contract:
    positional: tuple[str, ...]
    keywords: frozenset[str]
    requirements: Mapping[str, frozenset[str]]
    parametric: frozenset[str]


def own_nodes(statements: Sequence[ast.stmt]) -> Iterator[ast.AST]:
    """Every node of a unit's body; nested functions, lambdas and classes are their own
    units (their definition node is yielded, not their contents)."""
    pending: list[ast.AST] = list(statements)
    while len(pending) > 0:
        node = pending.pop()
        yield node
        if not isinstance(node, SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _parameters(arguments: ast.arguments) -> list[str]:
    names = [a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]]
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            names.append(extra.arg)
    return names


def _bindings(node: ast.AST) -> list[str]:
    """The names one node binds in its unit."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
        return [node.id]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [_import_local(alias) for alias in node.names]
    if isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name is not None:
        return [node.name]
    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return [node.rest]
    return []


def _import_local(alias: ast.alias) -> str:
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _declared_global(nodes: Sequence[ast.AST]) -> set[str]:
    return {
        name for node in nodes if isinstance(node, ast.Global | ast.Nonlocal) for name in node.names
    }


# -- declarations (PROP003, PROP006) ------------------------------------------------------


def _arity_issue(kind: str, call: ast.Call) -> str:
    leading = RESULT_AND_SOURCE if kind in (PRESERVES, PRESERVES_EXCEPT) else VALUE_ONLY
    count = len(call.args)
    if len(call.keywords) > 0 or any(isinstance(a, ast.Starred) for a in call.args):
        return f"{kind}(...) takes positional arguments only, no keyword or starred argument"
    if count < leading:
        return f"{kind}(...) needs {'a result and a source' if leading > VALUE_ONLY else 'a value'}"
    if kind == PRESERVES and count != leading:
        return "preserves(result, source) takes exactly two arguments; use preserves_except"
    if kind in (PRODUCES, PRESERVES_EXCEPT) and count == leading:
        return f"{kind}(...) names no property"
    return ""


def parse_declaration(
    kind: str, call: ast.Call, catalog: frozenset[str], allow_undeclared: bool
) -> tuple[Declaration, list[Issue]]:
    issues: list[Issue] = []
    arity = _arity_issue(kind, call)
    if arity != "":
        issues.append(Issue(PROP006, call, arity, PROP006))
    leading = RESULT_AND_SOURCE if kind in (PRESERVES, PRESERVES_EXCEPT) else VALUE_ONLY
    named: set[str] = set()
    for argument in call.args[leading:]:
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            issues.append(
                Issue(
                    PROP006,
                    argument,
                    f"a property of {kind}(...) must be a string literal",
                    PROP006,
                )
            )
            continue
        if argument.value not in catalog:
            issues.append(
                Issue(
                    PROP003,
                    argument,
                    f"{argument.value!r} is not a property of the catalog",
                    PROP003,
                )
            )
            if not allow_undeclared:
                continue  # a misspelled property is never silently checked
        named.add(argument.value)
    valid = not any(issue.rule is PROP006 for issue in issues)
    return Declaration(kind, call, frozenset(named), valid), issues


def _static_list(node: ast.expr) -> frozenset[str] | None:
    """The names of a literal list of string literals; None for anything else."""
    if not isinstance(node, ast.List):
        return None
    names = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(names) != len(node.elts):
        return None
    return frozenset(names)


def enable_issues(call: ast.Call, static: frozenset[str]) -> list[Issue]:
    """PROP005: a test bootstrap's enable(mode, [...]) must list exactly the catalog's
    runtime = "static" properties; a list the analysis cannot read is PROP006 (§6.2)."""
    if len(call.args) != ENABLE_ARGUMENTS or len(call.keywords) > 0:
        message = "enable(mode, static_properties) takes exactly two positional arguments"
        return [Issue(PROP006, call, message, PROP005)]
    listed = _static_list(call.args[1])
    if listed is None:
        message = (
            "the static properties of enable(...) must be a literal list of string literals, "
            "so they can be compared with the catalog"
        )
        return [Issue(PROP006, call.args[1], message, PROP005)]
    if listed == static:
        return []
    differences = []
    if len(static - listed) > 0:
        differences.append(f"missing {quoted(static - listed)}")
    if len(listed - static) > 0:
        differences.append(
            f"lists {quoted(listed - static)}, which the catalog does not mark static"
        )
    message = (
        f'enable(...) disagrees with the catalog\'s runtime = "static" properties: '
        f"{'; '.join(differences)} (`shockharness contracts static-properties` prints the list)"
    )
    return [Issue(PROP005, call.args[1], message, PROP005)]


def _statement_requires(
    statement: ast.stmt, declarations: Mapping[ast.Call, Declaration]
) -> Declaration | None:
    if not isinstance(statement, ast.Expr | ast.Assign) or not isinstance(
        statement.value, ast.Call
    ):
        return None
    if statement.value not in declarations:
        return None
    declaration = declarations[statement.value]
    if declaration.kind != REQUIRES or not declaration.valid:
        return None
    return declaration


def _without_docstring(body: Sequence[ast.stmt]) -> Sequence[ast.stmt]:
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return body[1:]
    return body


def _header_requirements(
    body: Sequence[ast.stmt],
    parameters: frozenset[str],
    declarations: Mapping[ast.Call, Declaration],
) -> tuple[dict[str, set[str]], set[ast.Call]]:
    """The requires statements on parameters before any other use of them."""
    used: set[str] = set()
    requirements: dict[str, set[str]] = {}
    calls: set[ast.Call] = set()
    for statement in _without_docstring(body):
        declaration = _statement_requires(statement, declarations)
        if declaration is not None:
            subject = declaration.call.args[0]
            if isinstance(subject, ast.Name) and subject.id in parameters - used:
                if subject.id not in requirements:
                    requirements[subject.id] = set()
                requirements[subject.id].update(declaration.properties)
                calls.add(declaration.call)
                continue
        used.update(n.id for n in ast.walk(statement) if isinstance(n, ast.Name))
    return requirements, calls


def _header(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    declarations: Mapping[ast.Call, Declaration],
    stored: frozenset[str],
) -> Header:
    """PROP007 for a requires on a parameter elsewhere; a parameter the body rebinds is a
    local after that, and a requires on it is a mid-body check."""
    parameters = frozenset(_parameters(function.args))
    requirements, calls = _header_requirements(function.body, parameters, declarations)
    fixed = parameters - stored
    misplaced = tuple(
        d
        for d in declarations.values()
        if d.kind == REQUIRES
        and d.valid
        and d.call not in calls
        and isinstance(d.call.args[0], ast.Name)
        and d.call.args[0].id in fixed
    )
    required = {name: frozenset(properties) for name, properties in requirements.items()}
    return Header(required, frozenset(calls), misplaced)


# -- the analysis -------------------------------------------------------------------------


class Analysis:
    def __init__(self, index: ProjectIndex, settings: Mapping[str, Any]) -> None:
        self.index = index
        catalog = load_catalog(settings)
        self.catalog = frozenset(catalog.properties)
        self.allow_undeclared = catalog.allow_undeclared
        self.static = frozenset(static_properties(settings))
        self.sinks = self._sinks(catalog.sinks)
        self.targets = tuple(target for target in catalog.targets if target.language == PYTHON)
        self.compositions = Compositions(catalog, PYTHON)
        self.max_depth = int(settings["max_depth"])
        self.producers = {
            name: frozenset(entry.producers) for name, entry in catalog.properties.items()
        }
        self.units: dict[ast.AST, Unit] = {}
        self.unit_deps: dict[ast.AST, Deps] = {}
        self.contracts: dict[tuple[ast.AST, int], Contract] = {}
        self.results: dict[tuple[ast.AST, int, tuple[tuple[str, PropSet], ...]], PropSet] = {}
        self.result_deps: dict[tuple[ast.AST, int, tuple[tuple[str, PropSet], ...]], Deps] = {}
        self.computing: set[ast.AST] = set()

    def _sinks(self, sinks: Sequence[CalleeSink]) -> dict[str, list[CalleeSink]]:
        found: dict[str, list[CalleeSink]] = {}
        for sink in sinks:
            if sink.language != PYTHON:
                continue
            target = self.index.resolve(sink.callee, frozenset())
            if target.kind not in (UNIT, LIBRARY):
                continue  # a reference config validate accepted but the index cannot name
            if target.reference not in found:
                found[target.reference] = []
            found[target.reference].append(sink)
        return found

    def module_unit(self, module: Module) -> Unit:
        return self._unit(module, module.tree, None, module.tree.body)

    def function_unit(
        self, module: Module, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> Unit:
        return self._unit(module, function, function, function.body)

    def _unit(
        self,
        module: Module,
        key: ast.AST,
        function: ast.FunctionDef | ast.AsyncFunctionDef | None,
        body: Sequence[ast.stmt],
    ) -> Unit:
        """A memoized unit; its dependencies (its module, what its calls resolved to) go
        to whoever asks for it."""
        tracker = self.index.tracker
        if key in self.units:
            tracker.add(self.unit_deps[key])
            return self.units[key]
        tracker.push()
        tracker.path(module.path)
        self.units[key] = self._build_unit(module, function, body)
        self.unit_deps[key] = tracker.pop()
        return self.units[key]

    def _build_unit(
        self,
        module: Module,
        function: ast.FunctionDef | ast.AsyncFunctionDef | None,
        body: Sequence[ast.stmt],
    ) -> Unit:
        parameters: tuple[str, ...] = ()
        local: frozenset[str] = frozenset()  # module level: the module's own tables
        receivers = NO_RECEIVERS
        nodes = tuple(own_nodes(body))
        stored = frozenset(name for node in nodes for name in _bindings(node))
        bound = stored
        if function is not None:
            parameters = tuple(_parameters(function.args))
            bound = stored - _declared_global(nodes)
            local = frozenset(bound | set(parameters))
            receivers = receivers_of(_owner(module.tree, function), function)
        declarations, issues = self._declarations(module, nodes, local, receivers)
        header = Header({}, frozenset(), ())
        if function is not None:
            header = _header(function, declarations, stored)
        read = frozenset(n.id for n in nodes if isinstance(n, ast.Name))
        return Unit(
            module=module,
            function=function,
            body=body,
            nodes=nodes,
            stored=stored,
            local=local,
            receivers=receivers,
            bound=frozenset(bound),
            read=read,
            parameters=parameters,
            declarations=declarations,
            issues=tuple(issues),
            header=header,
            parametric=_parametric(function, stored, declarations, header),
        )

    def _declarations(
        self,
        module: Module,
        nodes: Sequence[ast.AST],
        local: frozenset[str],
        receivers: Receivers,
    ) -> tuple[dict[ast.Call, Declaration], list[Issue]]:
        declarations: dict[ast.Call, Declaration] = {}
        issues: list[Issue] = []
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            target = self.index.callee(module, node.func, local, receivers)
            owner, _dot, kind = target.reference.rpartition(".")
            if owner in self.index.runtime and kind == ENABLE:
                issues.extend(enable_issues(node, self.static))
                continue
            if target.kind != RUNTIME:
                continue
            declaration, found = parse_declaration(kind, node, self.catalog, self.allow_undeclared)
            declarations[node] = declaration
            issues.extend(found)
        return declarations, issues

    def contract(self, target: Target) -> Contract:
        """A resolved callee's parameters and the requirements at the top of its body. A
        method called through an instance supplies its ``self`` (``target.implicit``):
        the call's arguments start at the next parameter."""
        assert target.module is not None and target.function is not None, "a unit target"
        function = target.function
        key = (function, target.implicit)
        if key in self.contracts:
            self.index.tracker.add(self.unit_deps[function])
        if key not in self.contracts:
            unit = self.function_unit(target.module, function)
            arguments = function.args
            positional = [a.arg for a in [*arguments.posonlyargs, *arguments.args]]
            supplied = frozenset(positional[: target.implicit])
            self.contracts[key] = Contract(
                positional=tuple(positional[target.implicit :]),
                keywords=frozenset(a.arg for a in [*arguments.args, *arguments.kwonlyargs])
                - supplied,
                requirements=unit.header.requirements,
                parametric=unit.parametric - supplied,
            )
        return self.contracts[key]

    def result(self, target: Target, crossings: int, passed: Mapping[str, PropSet]) -> PropSet:
        """What a call of ``target`` gives, ``crossings`` calls away from the checked unit:
        its own returns, with its further calls followed up to ``max_depth`` (§5.3)."""
        assert target.module is not None and target.function is not None, "a unit target"
        function = target.function
        if crossings > self.max_depth:
            return unknown(
                f"{target.reference} is more than max_depth = {self.max_depth} calls away"
            )
        key = (function, crossings, tuple(sorted(passed.items())))
        tracker = self.index.tracker
        if key in self.results:
            tracker.add(self.result_deps[key])
            return self.results[key]
        if function in self.computing:
            return unknown(f"{target.reference} calls itself (recursion is not followed)")
        self.computing.add(function)
        tracker.push()
        unit = self.function_unit(target.module, function)
        hooks = UnitHooks(self, unit, None, crossings, passed)
        summary = run_unit(hooks, unit.body, entry_state(unit))
        self.computing.discard(function)
        self.results[key] = _shaped(unit, summary)
        self.result_deps[key] = tracker.pop()
        return self.results[key]

    def producer_issues(self, unit: Unit) -> list[Issue]:
        """PROP002: a produces of a property whose catalog producers do not include the
        enclosing function (only properties with a non-empty producers list)."""
        names = self._names(unit)
        issues: list[Issue] = []
        for declaration in unit.declarations.values():
            if declaration.kind != PRODUCES or not declaration.valid:
                continue
            for name in sorted(declaration.properties & frozenset(self.producers)):
                allowed = self.producers[name]  # an undeclared name has no producers to break
                if len(allowed) > 0 and len(allowed & names) == 0:
                    message = (
                        f"produces(..., {name!r}) outside its declared producers "
                        f"({', '.join(sorted(allowed))})"
                    )
                    issues.append(Issue(PROP002, declaration.call, message, PROP002))
        return issues

    def _names(self, unit: Unit) -> frozenset[str]:
        """The dotted references that name a unit: module.function, module.Class.method."""
        if unit.function is None:
            return frozenset()
        qualname = _qualname(unit.module.tree, unit.function)
        if qualname is None:
            return frozenset()
        return frozenset(f"{name}.{qualname}" for name in module_names(unit.module.path))


def _owner(
    tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> ast.ClassDef | None:
    """The module-level class whose body defines ``function``."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and function in node.body:
            return node
    return None


def _qualname(tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for node in tree.body:
        if node is function:
            return function.name
        if isinstance(node, ast.ClassDef) and function in node.body:
            return f"{node.name}.{function.name}"
    return None


def _shaped(unit: Unit, summary: Summary) -> PropSet:
    """A generator function gives a generator of its items, an async function a
    coroutine of its result (§5.2c), any other function its result."""
    if _is_generator(unit.nodes):
        return generator(summary.items)
    if isinstance(unit.function, ast.AsyncFunctionDef):
        return coroutine(summary.result)
    return summary.result


def _is_generator(nodes: Sequence[ast.AST]) -> bool:
    return any(isinstance(node, ast.Yield | ast.YieldFrom) for node in nodes)


def entry_state(unit: Unit) -> Env:
    """Every name the unit reads or binds. A parameter starts with what the function
    requires of it (under ``declared``, nothing when it has no requires); a name the unit
    binds starts unbound; any other name (a global, an enclosing function's local) is
    unknown."""
    env: Env = {
        name: unknown(f"{name} is not a local value of this unit")
        for name in unit.read - unit.bound
    }
    for name in unit.bound:
        env[name] = UNBOUND
    for name in unit.parameters:
        env[name] = EMPTY
    for name, required in unit.header.requirements.items():
        env[name] = known_set(required)
    return env


# -- checks (PROP001) ---------------------------------------------------------------------


@dataclass(frozen=True)
class Passed:
    value: PropSet
    node: ast.AST


def _positional_argument(
    call: ast.Call, arguments: Sequence[PropSet], position: int
) -> Passed | None:
    for index, node in enumerate(call.args):
        if isinstance(node, ast.Starred):
            return Passed(unknown("the argument is passed through *args"), node)
        if index == position:
            return Passed(arguments[index], node)
    return None


def _argument(
    call: ast.Call,
    arguments: Sequence[PropSet],
    keywords: Sequence[tuple[str | None, PropSet]],
    position: int | None,
    parameter: str | None,
) -> Passed | None:
    """The argument at ``position``, or the keyword named ``parameter`` (a project
    callee's parameter at that position); None when it is not passed."""
    if position is not None:
        passed = _positional_argument(call, arguments, position)
        if passed is not None:
            return passed
    for (name, value), keyword in zip(keywords, call.keywords, strict=True):
        if name is not None and name == parameter:
            return Passed(value, keyword.value)
    if any(name is None for name, _value in keywords):
        return Passed(unknown("the argument may be passed through **kwargs"), call)
    if parameter is None and len(keywords) > 0:
        why = "a keyword argument to a library callee cannot be matched to a position"
        return Passed(unknown(why), call)
    return None


def _unresolved(call: ast.Call, target: Target) -> PropSet:
    if isinstance(call.func, ast.Attribute) and call.func.attr == JOIN:
        return unknown("a .join build (not a composition in this release)")
    return unknown(target.why)


def _library_result(target: Target, passed: Sequence[PropSet]) -> PropSet:
    """A library or builtin call carries nothing, unless it consumes a generator."""
    if any(value.lazy for value in passed):
        return unknown(f"{target.reference} consumes a generator (only a for loop binds its items)")
    return EMPTY  # a library or builtin callee carries nothing


def _parametric(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    rebound: frozenset[str],
    declarations: Mapping[ast.Call, Declaration],
    header: Header,
) -> frozenset[str]:
    """Parameters that require nothing (no requires, or requires(x) with no property),
    that the body never rebinds, and that a preserves names as its source."""
    if function is None:
        return frozenset()
    open_parameters = {
        name
        for name in _parameters(function.args)
        if name not in header.requirements or len(header.requirements[name]) == 0
    }
    sources = {
        d.call.args[1].id
        for d in declarations.values()
        if d.kind in (PRESERVES, PRESERVES_EXCEPT)
        and d.valid
        and isinstance(d.call.args[1], ast.Name)
    }
    return frozenset((open_parameters - rebound) & sources)


def _parametric_arguments(
    call: ast.Call,
    contract: Contract,
    arguments: Sequence[PropSet],
    keywords: Sequence[tuple[str | None, PropSet]],
) -> dict[str, PropSet]:
    """The caller's set for each of the callee's parametric parameters (EMPTY when the
    argument is not passed: the parameter's default is a literal)."""
    found: dict[str, PropSet] = {}
    for parameter in sorted(contract.parametric):
        position = None
        if parameter in contract.positional:
            position = contract.positional.index(parameter)
        named = parameter if parameter in contract.keywords else None
        found[parameter] = EMPTY
        passed = _argument(call, arguments, keywords, position, named)
        if passed is not None:
            found[parameter] = passed.value
    return found


def _reason(sink: CalleeSink | TargetSink) -> str:
    if sink.producer is not None:
        return f"{sink.reason}; its producer is {sink.producer}"
    return sink.reason


def _final_name(node: ast.expr) -> str | None:
    """The receiver's final identifier: ``headers`` of ``req.headers`` and of ``headers``."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _matches(sink: TargetSink, target: ast.expr) -> bool:
    """``<any>.attribute = v`` or ``receiver[...] = v``."""
    if isinstance(target, ast.Attribute):
        return sink.attribute == target.attr
    if isinstance(target, ast.Subscript):
        return sink.receiver is not None and sink.receiver == _final_name(target.value)
    return False


class UnitHooks:
    """What calls do inside one unit, ``crossings`` calls away from the checked unit (0 for
    the unit itself). ``reporter`` None: computing a callee's result; nothing is reported."""

    def __init__(
        self,
        analysis: Analysis,
        unit: Unit,
        reporter: Reporter | None,
        crossings: int,
        arguments: Mapping[str, PropSet],
    ) -> None:
        self.analysis = analysis
        self.unit = unit
        self.reporter = reporter
        self.crossings = crossings
        self.arguments = arguments  # the caller's sets for the parametric parameters

    def passed(self, name: str) -> PropSet | None:
        found: PropSet | None = None
        if name in self.arguments:
            found = self.arguments[name]
        return found

    def literal(self) -> PropSet:
        return self.analysis.compositions.literal_set()

    def compose(self, operation: str, parts: Sequence[Part]) -> PropSet:
        return self.analysis.compositions.compose(operation, parts)

    def assigned(
        self, target: ast.expr, value: ast.expr, value_set: PropSet, reporting: bool
    ) -> None:
        if self.reporter is None or not reporting:
            return
        for sink in self.analysis.targets:
            if _matches(sink, target):
                stated = Requirement(f"sink {sink.text} requires", f" ({_reason(sink)})", ASSIGNED)
                self.reporter.check(value, value_set, sink.requires, stated)

    def is_declaration(self, call: ast.Call) -> bool:
        return call in self.unit.declarations

    def declaration(self, call: ast.Call) -> Declaration:
        return self.unit.declarations[call]

    def checks_requires(self, declaration: Declaration) -> bool:
        header = self.unit.header
        return declaration.call not in header.calls and declaration not in header.misplaced

    def requirement(self, declaration: Declaration, value: PropSet, reporting: bool) -> None:
        if self.reporter is None or not reporting:
            return
        subject = ast.unparse(declaration.call.args[0])
        stated = Requirement(f"requires({subject}, ...) checks for", " here", PASSED)
        self.reporter.check(declaration.call.args[0], value, declaration.properties, stated)

    def call(
        self,
        call: ast.Call,
        arguments: Sequence[PropSet],
        keywords: Sequence[tuple[str | None, PropSet]],
        reporting: bool,
    ) -> PropSet:
        unit = self.unit
        target = self.analysis.index.callee(unit.module, call.func, unit.local, unit.receivers)
        if target.kind == UNKNOWN:
            return _unresolved(call, target)
        contract = None
        if target.kind == UNIT:
            contract = self.analysis.contract(target)
        if self.reporter is not None and reporting:
            self._sinks(call, target, contract, arguments, keywords)
            if contract is not None:
                self._requirements(call, target, contract, arguments, keywords)
        if contract is not None:
            passed = _parametric_arguments(call, contract, arguments, keywords)
            return self.analysis.result(target, self.crossings + 1, passed)
        return _library_result(target, [*arguments, *(v for _name, v in keywords)])

    def _sinks(
        self,
        call: ast.Call,
        target: Target,
        contract: Contract | None,
        arguments: Sequence[PropSet],
        keywords: Sequence[tuple[str | None, PropSet]],
    ) -> None:
        assert self.reporter is not None, "reporting"
        if target.reference not in self.analysis.sinks:
            return
        for sink in self.analysis.sinks[target.reference]:
            parameter = None
            if contract is not None and sink.position < len(contract.positional):
                parameter = contract.positional[sink.position]
            passed = _argument(call, arguments, keywords, sink.position, parameter)
            if passed is None:
                continue
            subject = f"sink {sink.callee}:{sink.position} requires"
            stated = Requirement(subject, f" ({_reason(sink)})", PASSED)
            self.reporter.check(passed.node, passed.value, sink.requires, stated)

    def _requirements(
        self,
        call: ast.Call,
        target: Target,
        contract: Contract,
        arguments: Sequence[PropSet],
        keywords: Sequence[tuple[str | None, PropSet]],
    ) -> None:
        assert self.reporter is not None, "reporting"
        for parameter, required in sorted(contract.requirements.items()):
            position = None
            if parameter in contract.positional:
                position = contract.positional.index(parameter)
            named = parameter if parameter in contract.keywords else None
            passed = _argument(call, arguments, keywords, position, named)
            if passed is None:
                continue
            stated = Requirement(f"{target.reference} requires", f" on {parameter}", PASSED)
            self.reporter.check(passed.node, passed.value, required, stated)


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)]


def _misplaced_message(declaration: Declaration) -> str:
    subject = ast.unparse(declaration.call.args[0])
    return (
        f"requires({subject}, ...) on a parameter is not at the top of the body (after a use "
        "of the parameter, or in a branch, loop, try or with); it is not part of the contract"
    )


def _declaration_findings(analysis: Analysis, unit: Unit, reporter: Reporter) -> None:
    """PROP002, PROP003, PROP005-PROP007: what the unit's declarations say by themselves."""
    for issue in [*unit.issues, *analysis.producer_issues(unit)]:
        reporter.add_issue(issue)
    for declaration in unit.header.misplaced:
        reporter.add(PROP007, declaration.call, _misplaced_message(declaration), STATUS_VIOLATION)


def _contract_unit(tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A module-level function or a method of a module-level class (PROP008's units)."""
    return _qualname(tree, function) is not None


def _checked_parameters(
    tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[ast.arg]:
    """Every parameter, except a method's self or cls (a staticmethod has neither)."""
    arguments = function.args
    found = [*arguments.posonlyargs, *arguments.args]
    in_class = _qualname(tree, function) != function.name
    static = any(isinstance(d, ast.Name) and d.id == STATICMETHOD for d in function.decorator_list)
    if in_class and not static and len(found) > 0:
        found = found[1:]
    found.extend(arguments.kwonlyargs)
    found.extend(extra for extra in (arguments.vararg, arguments.kwarg) if extra is not None)
    return found


def _declared_return(unit: Unit, value: ast.expr) -> bool:
    if isinstance(value, ast.Constant) and value.value is None:
        return True  # return None: no result to declare
    if not isinstance(value, ast.Call) or value not in unit.declarations:
        return False
    declaration = unit.declarations[value]
    return declaration.kind in RESULT_DECLARATIONS and declaration.valid


def _complete_findings(unit: Unit, reporter: Reporter) -> None:
    """PROP008 (complete): a parameter with no requires, a return with no produces or
    preserves, in a module-level function or a method."""
    function = unit.function
    if function is None or not _contract_unit(unit.module.tree, function):
        return
    for parameter in _checked_parameters(unit.module.tree, function):
        if parameter.arg not in unit.header.requirements:
            message = (
                f"{function.name}: parameter {parameter.arg} has no requires; under complete "
                f'every parameter declares what it must carry (requires({parameter.arg}, "p")) '
                f"or that it needs nothing (requires({parameter.arg}))"
            )
            reporter.add(PROP008, parameter, message, STATUS_VIOLATION)
    for node in unit.nodes:
        if isinstance(node, ast.Return) and node.value is not None:
            if not _declared_return(unit, node.value):
                message = (
                    f"this return of {function.name} has no produces or preserves; under "
                    "complete every return declares what its result carries"
                )
                reporter.add(PROP008, node, message, STATUS_VIOLATION)


def _flow_findings(analysis: Analysis, unit: Unit, reporter: Reporter) -> None:
    """PROP001 and PROP004: one walk of the unit, reporting."""
    summary = run_unit(UnitHooks(analysis, unit, reporter, 0, {}), unit.body, entry_state(unit))
    if unit.function is None:
        return
    for node, message in inconsistent_returns(unit.function.name, summary.returns):
        reporter.add(PROP004, node, message, STATUS_VIOLATION)


def _file_findings(analysis: Analysis, module: Module, reporter: Reporter) -> None:
    units = [analysis.module_unit(module)]
    units.extend(analysis.function_unit(module, function) for function in _functions(module.tree))
    walked = {PROP001.rule_id, PROP004.rule_id} & reporter.file.applies
    for unit in units:
        _declaration_findings(analysis, unit, reporter)
        if reporter.file.complete and PROP008.rule_id in reporter.file.applies:
            _complete_findings(unit, reporter)
        if len(walked) > 0:
            _flow_findings(analysis, unit, reporter)


def _arg_span(source: SourceText, node: ast.arg) -> Span:
    end_line = node.end_lineno
    end_column = node.end_col_offset
    assert end_line is not None and end_column is not None, "a parsed parameter has an end"
    return Span(
        line=node.lineno,
        column=source.column_from_byte_offset(node.lineno, node.col_offset),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, end_column),
    )


def _locator(source: SourceText) -> Callable[[object], Located]:
    def locate(node: object) -> Located:
        if isinstance(node, ast.arg):
            return Located(_arg_span(source, node), node.arg)
        assert isinstance(node, ast.expr | ast.stmt), "a located Python node"
        return Located(node_span(source, node), ast.unparse(node))

    return locate


def run_property_contracts(
    files: Sequence[ContractFile],
    index: ProjectIndex,
    settings: Mapping[str, Any],
    deps: dict[str, Deps],
) -> dict[str, list[Finding]]:
    """Each file's findings; ``deps`` receives what each file's findings depend on."""
    tracker = index.tracker
    tracker.push()
    analysis = Analysis(index, settings)  # resolves the catalog's sinks, for every file
    shared = tracker.pop()
    found: dict[str, list[Finding]] = {}
    for file in files:
        module = index.by_path[file.path]
        if len(file.applies) == 0 or index.is_runtime(module):
            continue
        reporter = Reporter(file, settings, _locator(file.source))
        index.tracker.push()
        index.tracker.add(shared)
        index.tracker.path(file.path)
        _file_findings(analysis, module, reporter)
        deps[file.path] = index.tracker.pop()
        found[file.path] = sorted(reporter.found.values(), key=lambda f: f.sort_key())
    return found


def property_contract_findings(
    files: Sequence[ContractFile],
    sources: Mapping[str, tuple[str, SourceText]],
    root: Path,
    settings: Mapping[str, Any],
    disk: DiskLog,
    deps: dict[str, Deps],
) -> dict[str, list[Finding]]:
    """Both languages: each file's language decides its index and its checks. ``sources``
    are every analyzed file, where resolved callees' contracts are read first (``files``
    may be only some of them); ``disk`` logs every other file the indexes probe or read,
    and ``deps`` receives what each file's findings depend on."""
    found: dict[str, list[Finding]] = {}
    python_files = [file for file in files if file.language == PYTHON]
    if len(python_files) > 0:
        # Each of these files parsed in the per-file phase; the same text parses again.
        trees = {
            path: ast.parse(source.text, filename=path)
            for path, (language, source) in sources.items()
            if language == PYTHON
        }
        modules = python_runtime_modules(settings)
        index = ProjectIndex(root, trees, modules, disk, Tracker())
        found.update(run_property_contracts(python_files, index, settings, deps))
    script_files = [file for file in files if file.language in SCRIPT_LANGUAGES]
    if len(script_files) > 0:
        texts = {
            path: source.text
            for path, (language, source) in sources.items()
            if language in SCRIPT_LANGUAGES
        }
        runtime = javascript_runtime_modules(settings)
        scripts = JsProjectIndex(root, texts, runtime, disk, Tracker())
        found.update(run_javascript_contracts(script_files, scripts, settings, deps))
    return found


def _python_considered(analysis: Analysis, module: Module, path: str) -> list[Considered]:
    units = [analysis.module_unit(module)]
    units.extend(analysis.function_unit(module, function) for function in _functions(module.tree))
    return [
        Considered(path, declaration.call.lineno, ast.unparse(declaration.call))
        for unit in units
        for declaration in unit.declarations.values()
        if declaration.kind == REQUIRES and declaration.valid and len(declaration.call.args) == 1
    ]


def considered_declarations(
    files: Sequence[ContractFile],
    sources: Mapping[str, tuple[str, SourceText]],
    root: Path,
    settings: Mapping[str, Any],
) -> list[Considered]:
    """Every no-property ``requires(x)`` in the files under complete (§9's sorry count)."""
    found: list[Considered] = []
    python_files = [f for f in files if f.language == PYTHON and f.complete]
    if len(python_files) > 0:
        trees = {
            path: ast.parse(source.text, filename=path)
            for path, (language, source) in sources.items()
            if language == PYTHON
        }
        modules = python_runtime_modules(settings)
        index = ProjectIndex(root, trees, modules, new_log(root), Tracker())
        analysis = Analysis(index, settings)
        for file in python_files:
            found.extend(_python_considered(analysis, index.by_path[file.path], file.path))
    script_files = [f for f in files if f.language in SCRIPT_LANGUAGES and f.complete]
    if len(script_files) > 0:
        texts = {
            path: source.text
            for path, (language, source) in sources.items()
            if language in SCRIPT_LANGUAGES
        }
        runtime = javascript_runtime_modules(settings)
        scripts = JsProjectIndex(root, texts, runtime, new_log(root), Tracker())
        found.extend(javascript_considered(script_files, scripts, settings))
    return sorted(found, key=lambda c: (c.path, c.line))
