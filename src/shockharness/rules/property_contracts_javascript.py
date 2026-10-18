"""Property contracts, JavaScript and TypeScript (milestone P1b): PROP001, PROP003, PROP005,
PROP006, PROP007.

The counterpart of :mod:`.property_contracts`. Every function, arrow and method of a file
the rules apply to, and the module body, is walked once with
:mod:`shockharness.contracts.javascript_flow`. A call that resolves to a project function
(``path:export``) is checked against that function's own declared contract, one hop:

* the ``requires`` statements at the top of its body;
* the result set of its own returns, computed with every further project call inside it
  unknown.

A call whose resolved reference is a catalog sink (``path:export:N``, ``package:name:N``,
``fetch:0``) is checked at that argument. An assignment to a catalog target
(``el.innerHTML = v``) is checked at the value. Template literals and ``+`` chains are
composed by the catalog's rules.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tree_sitter import Node

from shockharness.contracts.catalog import (
    JAVASCRIPT,
    PRESERVES,
    PRESERVES_EXCEPT,
    PRODUCES,
    REQUIRES,
    TYPESCRIPT,
    CalleeSink,
    TargetSink,
    load_catalog,
    static_properties,
)
from shockharness.contracts.compose import Compositions
from shockharness.contracts.javascript_flow import (
    JsDeclaration,
    JsFlow,
    children,
    field,
    field_nodes,
    has_token,
    inner,
    run_js_unit,
)
from shockharness.contracts.javascript_index import (
    RUNTIME_MARKER,
    JsModule,
    JsProjectIndex,
    JsTarget,
)
from shockharness.contracts.python_flow import (
    EMPTY,
    UNBOUND,
    Env,
    Part,
    PropSet,
    lazy_unknown,
    unknown,
)
from shockharness.contracts.python_index import LIBRARY, RUNTIME, UNIT, UNKNOWN
from shockharness.contracts.report import (
    ASSIGNED,
    PASSED,
    ContractFile,
    Issue,
    Located,
    Reporter,
    Requirement,
    quoted,
)
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.javascript_catches import node_span, node_text, parameter_parts
from shockharness.ir.javascript_functions import (
    UNIT_TYPES,
    dotted_name,
    pattern_names,
    string_value,
)
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.rules.registry import PROP001, PROP003, PROP005, PROP006, PROP007
from shockharness.source import SourceText

# requires(value, ...) / produces(value, ...); preserves(result, source[, ...]).
VALUE_ONLY = 1
RESULT_AND_SOURCE = 2
RESULT_DECLARATIONS = (PRODUCES, PRESERVES, PRESERVES_EXCEPT)
ENABLE_ARGUMENTS = 2  # enable(mode, static_properties)
ENABLE_REFERENCE = f"{RUNTIME_MARKER}:enable"
JOIN = "join"
ASYNC = "async"
GENERATORS = frozenset({Kind.GENERATOR_FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION})
BINDING_DECLARATIONS = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.CLASS_DECLARATION,
    }
)
LANGUAGES = (JAVASCRIPT, TYPESCRIPT)


def own_nodes(top: Sequence[Node]) -> Iterator[Node]:
    """Every node of a unit's code; nested functions and classes are yielded, not entered."""
    pending = list(top)
    while len(pending) > 0:
        node = pending.pop()
        yield node
        if node.type not in UNIT_TYPES:
            pending.extend(node.named_children)


def _parameter_nodes(function: Node) -> list[Node]:
    """``(a, b)`` of a function, or the one parameter of ``x => ...``."""
    return [*inner(function, Field.PARAMETERS), *field_nodes(function, Field.PARAMETER)]


def _binds(target: Node) -> list[str]:
    """The names an identifier or a destructuring pattern binds."""
    if target.type == Kind.IDENTIFIER:
        return [node_text(target)]
    return pattern_names(target)


def _parameters(function: Node) -> list[str | None]:
    """Each positional parameter's name; None for a pattern or a rest parameter."""
    found: list[str | None] = []
    for parameter in _parameter_nodes(function):
        binding, _default = parameter_parts(parameter)
        name: str | None = None
        if binding.type == Kind.IDENTIFIER:
            name = node_text(binding)
        found.append(name)
    return found


def _parameter_bindings(function: Node) -> set[str]:
    names: set[str] = set()
    for parameter in _parameter_nodes(function):
        binding, _default = parameter_parts(parameter)
        names.update(_binds(binding))
    return names


def _bindings(node: Node) -> list[str]:
    """The names one node binds in its unit."""
    if node.type == Kind.VARIABLE_DECLARATOR or node.type in BINDING_DECLARATIONS:
        return [name for target in field_nodes(node, Field.NAME) for name in _binds(target)]
    if node.type == Kind.CATCH_CLAUSE:
        return [name for target in field_nodes(node, Field.PARAMETER) for name in _binds(target)]
    return []


def _names(nodes: Sequence[Node]) -> set[str]:
    return {
        node_text(node)
        for node in own_nodes(nodes)
        if node.type in (Kind.IDENTIFIER, Kind.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN)
    }


def _body(function: Node) -> tuple[list[Node], list[Node]]:
    """(statements, [expression]): an arrow with an expression body returns it."""
    body = field_nodes(function, Field.BODY)
    if len(body) == 1 and body[0].type != Kind.STATEMENT_BLOCK:
        return [], body
    return [child for block in body for child in children(block)], []


@dataclass(frozen=True)
class JsHeader:
    requirements: Mapping[str, frozenset[str]]
    calls: frozenset[int]  # node ids of header requires calls
    misplaced: tuple[JsDeclaration, ...]


@dataclass(frozen=True)
class JsUnit:
    module: JsModule
    function: Node | None  # None: the module body
    body: Sequence[Node]
    expression: Sequence[Node]  # an arrow's expression body, which it returns
    local: frozenset[str]
    bound: frozenset[str]
    read: frozenset[str]
    parameters: tuple[str | None, ...]
    declarations: Mapping[int, JsDeclaration]  # by call node id
    issues: tuple[Issue, ...]
    header: JsHeader


@dataclass(frozen=True)
class JsContract:
    positional: tuple[str | None, ...]
    requirements: Mapping[str, frozenset[str]]
    result: PropSet


# -- declarations (PROP003, PROP006) ------------------------------------------------------


def _arity_issue(kind: str, arguments: Sequence[Node]) -> str:
    leading = RESULT_AND_SOURCE if kind in (PRESERVES, PRESERVES_EXCEPT) else VALUE_ONLY
    count = len(arguments)
    if any(argument.type == Kind.SPREAD_ELEMENT for argument in arguments):
        return f"{kind}(...) takes no spread argument"
    if count < leading:
        return f"{kind}(...) needs {'a result and a source' if leading > VALUE_ONLY else 'a value'}"
    if kind == PRESERVES and count != leading:
        return "preserves(result, source) takes exactly two arguments; use preserves_except"
    if kind in (PRODUCES, PRESERVES_EXCEPT) and count == leading:
        return f"{kind}(...) names no property"
    return ""


def parse_js_declaration(
    kind: str, call: Node, catalog: frozenset[str], allow_undeclared: bool
) -> tuple[JsDeclaration, list[Issue]]:
    arguments = tuple(inner(call, Field.ARGUMENTS))
    issues: list[Issue] = []
    arity = _arity_issue(kind, arguments)
    if arity != "":
        issues.append(Issue(PROP006, call, arity, PROP006))
    leading = RESULT_AND_SOURCE if kind in (PRESERVES, PRESERVES_EXCEPT) else VALUE_ONLY
    named: set[str] = set()
    for argument in arguments[leading:]:
        name = string_value(argument)
        if name is None:
            message = f"a property of {kind}(...) must be a string literal"
            issues.append(Issue(PROP006, argument, message, PROP006))
            continue
        if name not in catalog:
            message = f"{name!r} is not a property of the catalog"
            issues.append(Issue(PROP003, argument, message, PROP003))
            if not allow_undeclared:
                continue  # a misspelled property is never silently checked
        named.add(name)
    valid = not any(issue.rule is PROP006 for issue in issues)
    return JsDeclaration(kind, call, arguments, frozenset(named), valid), issues


def _static_list(node: Node) -> frozenset[str] | None:
    if node.type != Kind.ARRAY:
        return None
    elements = children(node)
    names = [string_value(element) for element in elements]
    if any(name is None for name in names):
        return None
    return frozenset(name for name in names if name is not None)


def enable_issues(call: Node, static: frozenset[str]) -> list[Issue]:
    """PROP005: a test bootstrap's enable(mode, [...]) must list exactly the catalog's
    runtime = "static" properties; a list the analysis cannot read is PROP006 (§6.2)."""
    arguments = inner(call, Field.ARGUMENTS)
    if len(arguments) != ENABLE_ARGUMENTS or any(a.type == Kind.SPREAD_ELEMENT for a in arguments):
        message = "enable(mode, staticProperties) takes exactly two arguments"
        return [Issue(PROP006, call, message, PROP005)]
    listed = _static_list(arguments[1])
    if listed is None:
        message = (
            "the static properties of enable(...) must be a literal array of string literals, "
            "so they can be compared with the catalog"
        )
        return [Issue(PROP006, arguments[1], message, PROP005)]
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
    return [Issue(PROP005, arguments[1], message, PROP005)]


def _statement_requires(
    statement: Node, declarations: Mapping[int, JsDeclaration]
) -> JsDeclaration | None:
    if statement.type != Kind.EXPRESSION_STATEMENT:
        return None
    inner = children(statement)
    if len(inner) != 1 or inner[0].id not in declarations:
        return None
    declaration = declarations[inner[0].id]
    if declaration.kind != REQUIRES or not declaration.valid:
        return None
    return declaration


def _header(
    function: Node, body: Sequence[Node], declarations: Mapping[int, JsDeclaration]
) -> JsHeader:
    """PROP007 for a requires on a parameter elsewhere; a parameter the body rebinds is a
    local after that, and a requires on it is a mid-body check."""
    parameters = frozenset(name for name in _parameters(function) if name is not None)
    used: set[str] = set()
    requirements: dict[str, set[str]] = {}
    calls: set[int] = set()
    for statement in body:
        declaration = _statement_requires(statement, declarations)
        if declaration is not None:
            subject = declaration.arguments[0]
            name = node_text(subject)
            if subject.type == Kind.IDENTIFIER and name in parameters - used:
                if name not in requirements:
                    requirements[name] = set()
                requirements[name].update(declaration.properties)
                calls.add(declaration.call.id)
                continue
        used.update(_names([statement]))
    rebound = _rebound(body) & parameters
    misplaced = tuple(
        d
        for d in declarations.values()
        if d.kind == REQUIRES
        and d.valid
        and d.call.id not in calls
        and d.arguments[0].type == Kind.IDENTIFIER
        and node_text(d.arguments[0]) in parameters - rebound
    )
    required = {name: frozenset(properties) for name, properties in requirements.items()}
    return JsHeader(required, frozenset(calls), misplaced)


def _rebound(body: Sequence[Node]) -> set[str]:
    names: set[str] = set()
    for node in own_nodes(body):
        names.update(_bindings(node))
        if node.type in (Kind.ASSIGNMENT_EXPRESSION, Kind.AUGMENTED_ASSIGNMENT_EXPRESSION):
            left = field(node, Field.LEFT)
            if left is not None and left.type == Kind.IDENTIFIER:
                names.add(node_text(left))
    return names


# -- the analysis -------------------------------------------------------------------------


class JsAnalysis:
    def __init__(self, index: JsProjectIndex, settings: Mapping[str, Any]) -> None:
        self.index = index
        catalog = load_catalog(settings)
        self.catalog = frozenset(catalog.properties)
        self.allow_undeclared = catalog.allow_undeclared
        self.static = frozenset(static_properties(settings))
        self.sinks = self._sinks(catalog.sinks)
        self.targets = tuple(t for t in catalog.targets if t.language in LANGUAGES)
        self.compositions = Compositions(catalog, JAVASCRIPT)
        # Keyed by (path, node id): a node id is unique within one file's tree.
        self.units: dict[tuple[str, int], JsUnit] = {}
        self.contracts: dict[tuple[str, int], JsContract] = {}

    def _sinks(self, sinks: Sequence[CalleeSink]) -> dict[str, list[CalleeSink]]:
        found: dict[str, list[CalleeSink]] = {}
        for sink in sinks:
            if sink.language not in LANGUAGES:
                continue
            target = self.index.resolve(sink.callee)
            if target.kind not in (UNIT, LIBRARY):
                continue  # a reference config validate accepted but the index cannot name
            if target.reference not in found:
                found[target.reference] = []
            found[target.reference].append(sink)
        return found

    def unit(self, module: JsModule, function: Node | None) -> JsUnit:
        node = module.root
        if function is not None:
            node = function
        key = (module.path, node.id)
        if key not in self.units:
            self.units[key] = self._build(module, function)
        return self.units[key]

    def _build(self, module: JsModule, function: Node | None) -> JsUnit:
        body, expression = children(module.root), []
        parameters: tuple[str | None, ...] = ()
        local: frozenset[str] = frozenset()  # module level: the module's own tables
        if function is not None:
            body, expression = _body(function)
            parameters = tuple(_parameters(function))
        top = [*body, *expression]
        bound = {name for node in own_nodes(top) for name in _bindings(node)}
        if function is not None:
            bound |= _parameter_bindings(function)
            local = frozenset(bound)
        declarations, issues = self._declarations(module, top, local)
        header = JsHeader({}, frozenset(), ())
        if function is not None:
            header = _header(function, body, declarations)
        return JsUnit(
            module=module,
            function=function,
            body=body,
            expression=expression,
            local=local,
            bound=frozenset(bound),
            read=frozenset(_names(top)),
            parameters=parameters,
            declarations=declarations,
            issues=tuple(issues),
            header=header,
        )

    def _declarations(
        self, module: JsModule, top: Sequence[Node], local: frozenset[str]
    ) -> tuple[dict[int, JsDeclaration], list[Issue]]:
        declarations: dict[int, JsDeclaration] = {}
        issues: list[Issue] = []
        for node in own_nodes(top):
            function = field(node, Field.FUNCTION) if node.type == Kind.CALL_EXPRESSION else None
            if function is None:
                continue
            target = self.index.callee(module, function, local)
            if target.reference == ENABLE_REFERENCE:
                issues.extend(enable_issues(node, self.static))
                continue
            if target.kind != RUNTIME:
                continue
            _marker, _colon, kind = target.reference.rpartition(":")
            declaration, found = parse_js_declaration(
                kind, node, self.catalog, self.allow_undeclared
            )
            declarations[node.id] = declaration
            issues.extend(found)
        return declarations, issues

    def contract(self, target: JsTarget) -> JsContract:
        assert target.module is not None and target.function is not None, "a unit target"
        function = target.function
        key = (target.module.path, function.id)
        if key not in self.contracts:
            unit = self.unit(target.module, function)
            self.contracts[key] = JsContract(
                positional=unit.parameters,
                requirements=unit.header.requirements,
                result=self._result(unit, target.reference),
            )
        return self.contracts[key]

    def _result(self, unit: JsUnit, reference: str) -> PropSet:
        function = unit.function
        assert function is not None, "a function unit"
        if function.type in GENERATORS:
            return lazy_unknown(f"{reference} is a generator (generator semantics are P2)")
        if has_token(function, ASYNC):
            return unknown(f"{reference} is async (await semantics are P2)")
        declared = [d for d in unit.declarations.values() if d.kind in RESULT_DECLARATIONS]
        if not any(d.valid for d in declared):
            return EMPTY  # no produces or preserves: the function declares no result
        return run(JsUnitHooks(self, unit, None), unit)


def entry_state(unit: JsUnit) -> Env:
    """Every name the unit reads or binds (see the Python counterpart)."""
    env: Env = {
        name: unknown(f"{name} is not a local value of this unit")
        for name in unit.read - unit.bound
    }
    for name in unit.bound:
        env[name] = UNBOUND
    if unit.function is not None:
        for name in _parameter_bindings(unit.function):
            env[name] = EMPTY
    for name, required in unit.header.requirements.items():
        env[name] = PropSet(required, exact=True, why="", lazy=False)
    return env


def run(hooks: "JsUnitHooks", unit: JsUnit) -> PropSet:
    if len(unit.expression) == 0:
        return run_js_unit(hooks, unit.body, entry_state(unit))
    flow = JsFlow(hooks)
    return flow.expression(unit.expression[0], entry_state(unit))


# -- checks (PROP001) ---------------------------------------------------------------------


@dataclass(frozen=True)
class Passed:
    value: PropSet
    node: Node


def _argument(call: Node, arguments: Sequence[PropSet], position: int) -> Passed | None:
    """The argument at ``position``; None when it is not passed."""
    for index, node in enumerate(inner(call, Field.ARGUMENTS)):
        if node.type == Kind.SPREAD_ELEMENT:
            return Passed(unknown("the argument is passed through a spread"), node)
        if index == position:
            return Passed(arguments[index], node)
    return None


def _reason(sink: CalleeSink | TargetSink) -> str:
    if sink.producer is not None:
        return f"{sink.reason}; its producer is {sink.producer}"
    return sink.reason


def _matches(sink: TargetSink, target: Node) -> bool:
    """``<any>.attribute = v`` or ``receiver[...] = v``."""
    if target.type == Kind.MEMBER_EXPRESSION:
        prop = field(target, Field.PROPERTY)
        return prop is not None and sink.attribute == node_text(prop)
    if target.type == Kind.SUBSCRIPT_EXPRESSION:
        receiver = field(target, Field.OBJECT)
        return (
            sink.receiver is not None
            and receiver is not None
            and sink.receiver == dotted_name(receiver)
        )
    return False


def _unresolved(call: Node, target: JsTarget) -> PropSet:
    names = [
        node_text(prop)
        for function in field_nodes(call, Field.FUNCTION)
        for prop in field_nodes(function, Field.PROPERTY)
    ]
    if names == [JOIN]:
        return unknown("a .join build (not a composition in this release)")
    return unknown(target.why)


def _call_result(
    target: JsTarget, contract: JsContract | None, passed: Sequence[PropSet]
) -> PropSet:
    if contract is not None:
        return contract.result
    if target.kind == UNIT:
        return unknown(f"{target.reference} is a further call inside a callee (one hop)")
    if any(value.lazy for value in passed):
        return unknown(f"{target.reference} consumes a generator (generator semantics are P2)")
    return EMPTY  # a library callee or a global carries nothing


class JsUnitHooks:
    """What calls do inside one unit. ``reporter`` None: computing a callee's own result
    set, where a further project call is unknown (one hop) and nothing is reported."""

    def __init__(self, analysis: JsAnalysis, unit: JsUnit, reporter: Reporter | None) -> None:
        self.analysis = analysis
        self.unit = unit
        self.reporter = reporter

    def literal(self) -> PropSet:
        return self.analysis.compositions.literal_set()

    def compose(self, operation: str, parts: Sequence[Part]) -> PropSet:
        return self.analysis.compositions.compose(operation, parts)

    def assigned(self, target: Node, value: Node, value_set: PropSet, reporting: bool) -> None:
        if self.reporter is None or not reporting:
            return
        for sink in self.analysis.targets:
            if _matches(sink, target):
                stated = Requirement(f"sink {sink.text} requires", f" ({_reason(sink)})", ASSIGNED)
                self.reporter.check(value, value_set, sink.requires, stated)

    def is_declaration(self, call: Node) -> bool:
        return call.id in self.unit.declarations

    def declaration(self, call: Node) -> JsDeclaration:
        return self.unit.declarations[call.id]

    def checks_requires(self, declaration: JsDeclaration) -> bool:
        header = self.unit.header
        return declaration.call.id not in header.calls and declaration not in header.misplaced

    def requirement(self, declaration: JsDeclaration, value: PropSet, reporting: bool) -> None:
        if self.reporter is None or not reporting:
            return
        subject = node_text(declaration.arguments[0])
        stated = Requirement(f"requires({subject}, ...) checks for", " here", PASSED)
        self.reporter.check(declaration.arguments[0], value, declaration.properties, stated)

    def call(self, call: Node, arguments: Sequence[PropSet], reporting: bool) -> PropSet:
        function = field(call, Field.FUNCTION)
        assert function is not None, "a call has a callee"
        target = self.analysis.index.callee(self.unit.module, function, self.unit.local)
        if target.kind == UNKNOWN:
            return _unresolved(call, target)
        contract = None
        if target.kind == UNIT and self.reporter is not None:
            contract = self.analysis.contract(target)
        if self.reporter is not None and reporting:
            self._sinks(call, target, arguments)
            if contract is not None:
                self._requirements(call, target, contract, arguments)
        return _call_result(target, contract, arguments)

    def _sinks(self, call: Node, target: JsTarget, arguments: Sequence[PropSet]) -> None:
        assert self.reporter is not None, "reporting"
        if target.reference not in self.analysis.sinks:
            return
        for sink in self.analysis.sinks[target.reference]:
            passed = _argument(call, arguments, sink.position)
            if passed is None:
                continue
            subject = f"sink {sink.callee}:{sink.position} requires"
            stated = Requirement(subject, f" ({_reason(sink)})", PASSED)
            self.reporter.check(passed.node, passed.value, sink.requires, stated)

    def _requirements(
        self, call: Node, target: JsTarget, contract: JsContract, arguments: Sequence[PropSet]
    ) -> None:
        assert self.reporter is not None, "reporting"
        for parameter, required in sorted(contract.requirements.items()):
            passed = _argument(call, arguments, contract.positional.index(parameter))
            if passed is None:
                continue
            stated = Requirement(f"{target.reference} requires", f" on {parameter}", PASSED)
            self.reporter.check(passed.node, passed.value, required, stated)


def _misplaced_message(declaration: JsDeclaration) -> str:
    subject = node_text(declaration.arguments[0])
    return (
        f"requires({subject}, ...) on a parameter is not at the top of the body (after a use "
        "of the parameter, or in a branch, loop, try or block); it is not part of the contract"
    )


def _functions(root: Node) -> list[Node]:
    found: list[Node] = []
    pending = [root]
    while len(pending) > 0:
        node = pending.pop()
        if (
            node.type in UNIT_TYPES
            and field(node, Field.BODY) is not None
            and node.type
            not in (
                Kind.CLASS_DECLARATION,
                Kind.CLASS,
            )
        ):
            found.append(node)
        pending.extend(node.named_children)
    return found


def _file_findings(analysis: JsAnalysis, module: JsModule, reporter: Reporter) -> None:
    units = [analysis.unit(module, None)]
    units.extend(analysis.unit(module, function) for function in _functions(module.root))
    for unit in units:
        for issue in unit.issues:
            reporter.add_issue(issue)
        for declaration in unit.header.misplaced:
            reporter.add(
                PROP007, declaration.call, _misplaced_message(declaration), STATUS_VIOLATION
            )
        if PROP001.rule_id in reporter.file.applies:
            run(JsUnitHooks(analysis, unit, reporter), unit)


def _locator(source: SourceText) -> Callable[[object], Located]:
    def locate(node: object) -> Located:
        assert isinstance(node, Node), "a located tree-sitter node"
        return Located(node_span(source, node), " ".join(node_text(node).split()))

    return locate


def run_javascript_contracts(
    files: Sequence[ContractFile], index: JsProjectIndex, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    analysis = JsAnalysis(index, settings)
    found: dict[str, list[Finding]] = {}
    for file in files:
        module = index.module(file.path)
        if module is None or len(file.applies) == 0 or index.is_runtime(file.path):
            continue
        reporter = Reporter(file, settings, _locator(module.source))
        _file_findings(analysis, module, reporter)
        found[file.path] = sorted(reporter.found.values(), key=lambda f: f.sort_key())
    return found
