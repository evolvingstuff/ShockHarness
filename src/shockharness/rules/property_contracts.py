"""Property contracts, Python, milestone P1a: PROP001, PROP003, PROP006 and PROP007.

Every function of a file the rules apply to (and the module body) is walked once with
:mod:`shockharness.contracts.python_flow`. A call that resolves to a project function is
checked against that function's own declared contract, read directly (one hop, spec
§5.3): the ``requires`` at the top of its body, and the result set of its own returns,
computed with every further project call inside it unknown. A function with no
``produces``/``preserves`` declares no result: its result carries nothing. A call whose
resolved reference is a catalog sink (``callee:N``) is checked at that argument; a
keyword argument maps to its position for a project callee and is unknown for a library
callee. Contracts are inferred from the body, never from a separate declaration.
"""

import ast
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.contracts.catalog import (
    PRESERVES,
    PRESERVES_EXCEPT,
    PRODUCES,
    PYTHON,
    REQUIRES,
    CalleeSink,
    load_catalog,
    static_properties,
)
from shockharness.contracts.python_flow import (
    EMPTY,
    UNBOUND,
    Declaration,
    Env,
    PropSet,
    lazy_unknown,
    run_unit,
    unknown,
)
from shockharness.contracts.python_index import (
    LIBRARY,
    RUNTIME,
    UNIT,
    UNKNOWN,
    Module,
    ProjectIndex,
    Target,
)
from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.ir.model import CONFIDENCE_EXACT, Span
from shockharness.ir.python_catches import node_span
from shockharness.rules.registry import PROP001, PROP003, PROP005, PROP006, PROP007, RuleSpec
from shockharness.source import SourceText

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# requires(value, ...) / produces(value, ...); preserves(result, source[, ...]).
VALUE_ONLY = 1
RESULT_AND_SOURCE = 2
RESULT_DECLARATIONS = (PRODUCES, PRESERVES, PRESERVES_EXCEPT)
JOIN = "join"
ENABLE = "enable"
ENABLE_ARGUMENTS = 2  # enable(mode, static_properties)
SEVERITY_ERROR = "error"
SEVERITY_REVIEW = "review"


@dataclass(frozen=True)
class ContractFile:
    path: str
    source: SourceText
    applies: frozenset[str]  # the PROP rule IDs applied to this file


@dataclass(frozen=True)
class Issue:
    rule: RuleSpec
    node: ast.expr
    message: str
    # The rule whose scope decides whether it is reported: the rule itself, or PROP005
    # for a malformed enable(...) in a test bootstrap (PROP006 there, spec §6.2).
    scope: RuleSpec


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
    local: frozenset[str]  # names bound in a function: a call through one is unknown
    bound: frozenset[str]  # names the unit binds: unbound until a path binds them
    read: frozenset[str]  # names the unit reads
    parameters: tuple[str, ...]
    declarations: Mapping[ast.Call, Declaration]
    issues: tuple[Issue, ...]  # PROP003 and PROP006, from the declarations
    header: Header


@dataclass(frozen=True)
class Contract:
    positional: tuple[str, ...]
    keywords: frozenset[str]
    requirements: Mapping[str, frozenset[str]]
    result: PropSet


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


def _stored(statements: Sequence[ast.stmt]) -> set[str]:
    return {name for node in own_nodes(statements) for name in _bindings(node)}


def _import_local(alias: ast.alias) -> str:
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _declared_global(body: Sequence[ast.stmt]) -> set[str]:
    return {
        name
        for node in own_nodes(body)
        if isinstance(node, ast.Global | ast.Nonlocal)
        for name in node.names
    }


def _quoted(properties: frozenset[str]) -> str:
    return ", ".join(repr(p) for p in sorted(properties))


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
        differences.append(f"missing {_quoted(static - listed)}")
    if len(listed - static) > 0:
        differences.append(
            f"lists {_quoted(listed - static)}, which the catalog does not mark static"
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
) -> Header:
    """PROP007 for a requires on a parameter elsewhere; a parameter the body rebinds is a
    local after that, and a requires on it is a mid-body check."""
    parameters = frozenset(_parameters(function.args))
    requirements, calls = _header_requirements(function.body, parameters, declarations)
    fixed = parameters - _stored(function.body)
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
        self.units: dict[ast.AST, Unit] = {}
        self.contracts: dict[ast.AST, Contract] = {}

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
        if module.tree not in self.units:
            self.units[module.tree] = self._build_unit(module, None, module.tree.body)
        return self.units[module.tree]

    def function_unit(
        self, module: Module, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> Unit:
        if function not in self.units:
            self.units[function] = self._build_unit(module, function, function.body)
        return self.units[function]

    def _build_unit(
        self,
        module: Module,
        function: ast.FunctionDef | ast.AsyncFunctionDef | None,
        body: Sequence[ast.stmt],
    ) -> Unit:
        parameters: tuple[str, ...] = ()
        local: frozenset[str] = frozenset()  # module level: the module's own tables
        bound = _stored(body)
        if function is not None:
            parameters = tuple(_parameters(function.args))
            bound = bound - _declared_global(body)
            local = frozenset(bound | set(parameters))
        declarations, issues = self._declarations(module, body, local)
        header = Header({}, frozenset(), ())
        if function is not None:
            header = _header(function, declarations)
        read = frozenset(n.id for n in own_nodes(body) if isinstance(n, ast.Name))
        return Unit(
            module=module,
            function=function,
            body=body,
            local=local,
            bound=frozenset(bound),
            read=read,
            parameters=parameters,
            declarations=declarations,
            issues=tuple(issues),
            header=header,
        )

    def _declarations(
        self, module: Module, body: Sequence[ast.stmt], local: frozenset[str]
    ) -> tuple[dict[ast.Call, Declaration], list[Issue]]:
        declarations: dict[ast.Call, Declaration] = {}
        issues: list[Issue] = []
        for node in own_nodes(body):
            if not isinstance(node, ast.Call):
                continue
            target = self.index.callee(module, node.func, local)
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
        assert target.module is not None and target.function is not None, "a unit target"
        function = target.function
        if function not in self.contracts:
            unit = self.function_unit(target.module, function)
            arguments = function.args
            self.contracts[function] = Contract(
                positional=tuple(a.arg for a in [*arguments.posonlyargs, *arguments.args]),
                keywords=frozenset(a.arg for a in [*arguments.args, *arguments.kwonlyargs]),
                requirements=unit.header.requirements,
                result=self._result(unit, target.reference),
            )
        return self.contracts[function]

    def _result(self, unit: Unit, reference: str) -> PropSet:
        function = unit.function
        assert function is not None, "a function unit"
        if _is_generator(unit.body):
            return lazy_unknown(f"{reference} is a generator (generator semantics are P2)")
        if isinstance(function, ast.AsyncFunctionDef):
            return unknown(f"{reference} is async (await semantics are P2)")
        declared = [d for d in unit.declarations.values() if d.kind in RESULT_DECLARATIONS]
        if not any(d.valid for d in declared):
            return EMPTY  # no produces or preserves: the function declares no result
        hooks = UnitHooks(self, unit, None)
        return run_unit(hooks, unit.body, entry_state(unit))


def _is_generator(body: Sequence[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Yield | ast.YieldFrom) for node in own_nodes(body))


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
        env[name] = PropSet(required, exact=True, why="", lazy=False)
    return env


# -- checks (PROP001) ---------------------------------------------------------------------


class Reporter:
    def __init__(self, file: ContractFile, settings: Mapping[str, Any]) -> None:
        self.file = file
        self.severities = settings["severities"]
        self.allow_undeclared = settings["allow_undeclared"] is True
        self.found: dict[tuple[str, int, int, str], Finding] = {}

    def severity(self, rule: RuleSpec) -> str:
        severity = str(self.severities[rule.rule_id])
        if rule is PROP003 and self.allow_undeclared and severity == SEVERITY_ERROR:
            return SEVERITY_REVIEW  # the catalog accepted unlisted names (§7)
        return severity

    def add(self, rule: RuleSpec, node: ast.AST, message: str, status: str) -> None:
        if rule.rule_id in self.file.applies:
            self._record(rule, node, message, status)

    def add_issue(self, issue: Issue) -> None:
        if issue.scope.rule_id in self.file.applies:
            self._record(issue.rule, issue.node, issue.message, STATUS_VIOLATION)

    def _record(self, rule: RuleSpec, node: ast.AST, message: str, status: str) -> None:
        span = self._span(node)
        key = (rule.rule_id, span.line, span.column, message)
        if key in self.found:
            return  # a loop or a finally block walked twice
        self.found[key] = Finding(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            severity=self.severity(rule),
            path=self.file.path,
            span=span,
            message=message,
            evidence=ast.unparse(node),
            confidence=CONFIDENCE_EXACT,
            status=status,
            remediation=rule.remediation,
            safe_autofix=False,
            scope=None,
            suppression=None,
            fingerprint=None,
            baseline=None,
        )

    def _span(self, node: ast.AST) -> Span:
        assert isinstance(node, ast.expr | ast.stmt), "a located node"
        return node_span(self.file.source, node)

    def check(
        self, node: ast.AST, value: PropSet, required: frozenset[str], subject: str, where: str
    ) -> None:
        """PROP001 unless ``value`` carries ``required``: "<subject> <properties><where>"."""
        missing = required - value.known
        if len(missing) == 0:
            return
        stated = f"{subject} {_quoted(missing)}{where}"
        if value.exact:
            message = f"{stated}; the value passed here has {value.render()}"
            self.add(PROP001, node, message, STATUS_VIOLATION)
            return
        pronoun = "it" if len(missing) == 1 else "them"
        message = (
            f"{stated}; the analysis cannot tell whether the value passed here carries "
            f"{pronoun}: {value.why}"
        )
        self.add(PROP001, node, message, STATUS_UNKNOWN)


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


def _call_result(target: Target, contract: Contract | None, passed: Sequence[PropSet]) -> PropSet:
    """A resolved call's result set: the callee's own declared result (one hop), unknown
    for a further project call inside a callee, nothing for a library callee."""
    if contract is not None:
        return contract.result
    if target.kind == UNIT:
        return unknown(f"{target.reference} is a further call inside a callee (one hop)")
    if any(value.lazy for value in passed):
        return unknown(f"{target.reference} consumes a generator (generator semantics are P2)")
    return EMPTY  # a library or builtin callee carries nothing


class UnitHooks:
    """What calls do inside one unit. ``reporter`` None: computing a callee's own result
    set, where a further project call is unknown (one hop) and nothing is reported."""

    def __init__(self, analysis: Analysis, unit: Unit, reporter: Reporter | None) -> None:
        self.analysis = analysis
        self.unit = unit
        self.reporter = reporter

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
        self.reporter.check(
            declaration.call.args[0],
            value,
            declaration.properties,
            f"requires({subject}, ...) checks for",
            " here",
        )

    def call(
        self,
        call: ast.Call,
        arguments: Sequence[PropSet],
        keywords: Sequence[tuple[str | None, PropSet]],
        reporting: bool,
    ) -> PropSet:
        target = self.analysis.index.callee(self.unit.module, call.func, self.unit.local)
        if target.kind == UNKNOWN:
            return _unresolved(call, target)
        contract = None
        if target.kind == UNIT and self.reporter is not None:
            contract = self.analysis.contract(target)
        if self.reporter is not None and reporting:
            self._sinks(call, target, contract, arguments, keywords)
            if contract is not None:
                self._requirements(call, target, contract, arguments, keywords)
        return _call_result(target, contract, [*arguments, *(v for _name, v in keywords)])

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
            reason = sink.reason
            if sink.producer is not None:
                reason = f"{reason}; its producer is {sink.producer}"
            subject = f"sink {sink.callee}:{sink.position} requires"
            self.reporter.check(passed.node, passed.value, sink.requires, subject, f" ({reason})")

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
            subject = f"{target.reference} requires"
            self.reporter.check(passed.node, passed.value, required, subject, f" on {parameter}")


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)]


def _misplaced_message(declaration: Declaration) -> str:
    subject = ast.unparse(declaration.call.args[0])
    return (
        f"requires({subject}, ...) on a parameter is not at the top of the body (after a use "
        "of the parameter, or in a branch, loop, try or with); it is not part of the contract"
    )


def _file_findings(analysis: Analysis, module: Module, reporter: Reporter) -> None:
    units = [analysis.module_unit(module)]
    units.extend(analysis.function_unit(module, function) for function in _functions(module.tree))
    for unit in units:
        for issue in unit.issues:
            reporter.add_issue(issue)
        for declaration in unit.header.misplaced:
            reporter.add(
                PROP007, declaration.call, _misplaced_message(declaration), STATUS_VIOLATION
            )
        if PROP001.rule_id in reporter.file.applies:
            run_unit(UnitHooks(analysis, unit, reporter), unit.body, entry_state(unit))


def run_property_contracts(
    files: Sequence[ContractFile], index: ProjectIndex, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    analysis = Analysis(index, settings)
    found: dict[str, list[Finding]] = {}
    for file in files:
        module = index.by_path[file.path]
        if len(file.applies) == 0 or index.is_runtime(module):
            continue
        reporter = Reporter(file, settings)
        _file_findings(analysis, module, reporter)
        found[file.path] = sorted(reporter.found.values(), key=lambda f: f.sort_key())
    return found
