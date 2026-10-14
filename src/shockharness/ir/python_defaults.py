"""Default and fallback facts for Python (consumed by DEF001-DEF006).

Everything here is syntactic. A fact says that the source *substitutes a value
for something absent*; whether the substitution is legitimate is the rule's
decision, and whether the absent thing was required is the author's. Where the
analyzer cannot establish a type (the receiver of ``.get``) or an intent (the
right operand of ``or`` is a variable, not a constant) the fact says so with
``approximate`` confidence.

Recognized shapes:

* parameter defaults (positional, keyword-only, lambda) and dataclass field
  defaults (``x: int = 0``, ``field(default=...)``, ``field(default_factory=...)``);
* mapping fallbacks: ``m.get(k, v)``, ``m.setdefault(k, v)``, ``m.pop(k, v)``,
  ``getattr(o, a, v)``, ``m[k] if k in m else v``, and ``m.get(k)`` with no
  fallback (an implicit ``None``);
* truthiness fallbacks: ``x or v`` outside a boolean test, ``x if x else v``;
* nullish fallbacks: ``x if x is not None else v`` and the inverted form;
* configuration fallbacks: ``os.getenv("X", v)``, ``os.environ.get("X", v)``,
  ``os.environ.setdefault``, ``os.getenv("X") or v``, and the implicit ``None``
  of ``os.getenv("X")``;
* exception-to-default traces for DEF005: a handler whose one statement returns
  a module-level constant or calls a module-level helper that returns a literal
  (literal returns are already classified on the ``CatchFact``).
"""

import ast
import re
from dataclasses import dataclass

from shockharness.constants import (
    EVIDENCE_MAX_CHARS,
    GETATTR_WITH_FALLBACK_ARITY,
    LOOKUP_WITH_FALLBACK_ARITY,
)
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONTEXT_ARGUMENT,
    CONTEXT_ASSIGNMENT,
    CONTEXT_DECLARATION,
    CONTEXT_EXPRESSION,
    CONTEXT_RETURN,
    CONTEXT_TEST,
    FAMILY_CONFIGURATION,
    FAMILY_EXCEPTION,
    FAMILY_MAPPING,
    FAMILY_NULLISH,
    FAMILY_PARAMETER,
    FAMILY_TRUTHINESS,
    KIND_DATACLASS_FACTORY,
    KIND_DATACLASS_FIELD,
    KIND_ENV_GET,
    KIND_ENV_GET_IMPLICIT,
    KIND_ENV_NULLISH,
    KIND_ENV_TRUTHINESS,
    KIND_EXCEPTION_CONSTANT,
    KIND_EXCEPTION_HELPER,
    KIND_GETATTR,
    KIND_MAPPING_GET,
    KIND_MAPPING_GET_IMPLICIT,
    KIND_MEMBERSHIP_TERNARY,
    KIND_NULLISH_TERNARY,
    KIND_PARAMETER,
    KIND_TRUTHINESS_OR,
    KIND_TRUTHINESS_TERNARY,
    MODULE_SCOPE,
    DefaultFact,
)
from shockharness.ir.python_catches import (
    SCOPE_NODES,
    bound_name,
    dotted_name,
    is_literal_like,
    is_logging_statement,
    is_pass,
    node_span,
    scope_name,
)
from shockharness.source import SourceText

UPPER_CASE_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
EMPTY_CONSTRUCTORS = frozenset(
    {"dict", "list", "set", "tuple", "frozenset", "str", "bytes", "int", "float", "bool"}
)
MAPPING_ANNOTATIONS = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
        "Counter",
        "ChainMap",
    }
)
MAPPING_CONSTRUCTORS = frozenset({"dict", "defaultdict", "OrderedDict", "Counter", "ChainMap"})
DATACLASS_DECORATORS = frozenset({"dataclass"})
OVERLOAD_DECORATORS = frozenset({"overload"})
FIELD_FUNCTIONS = frozenset({"field"})
GET_METHODS = frozenset({"get", "setdefault", "pop"})
NONE_COMPARISONS = (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)
MISSING_WHEN_TRUE = (ast.Is, ast.Eq)
VALUE_EXPRESSIONS = (ast.Name, ast.Attribute, ast.Subscript, ast.Call)
ELLIPSIS_TEXT = "..."


@dataclass(frozen=True)
class _EnvNames:
    """How this module can reach ``os.environ`` / ``os.getenv``, from its imports."""

    environ: frozenset[str]
    getenv: frozenset[str]


@dataclass(frozen=True)
class _ModuleIndex:
    env: _EnvNames
    mappings: frozenset[str]
    constants: dict[str, ast.expr]
    helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]


def _text(source: SourceText, node: ast.AST) -> str:
    segment = ast.get_source_segment(source.text, node) if isinstance(node, ast.expr) else None
    if segment is None:
        return type(node).__name__
    collapsed = " ".join(segment.split())
    if len(collapsed) > EVIDENCE_MAX_CHARS:
        return collapsed[: EVIDENCE_MAX_CHARS - len(ELLIPSIS_TEXT)] + ELLIPSIS_TEXT
    return collapsed


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)


def _mentions(container: ast.AST, target: ast.AST) -> bool:
    wanted = ast.dump(target)
    return any(ast.dump(node) == wanted for node in ast.walk(container))


def is_constant_shaped(expr: ast.expr | None) -> bool:
    """Literal-like, an UPPER_CASE name or attribute, or an empty builtin constructor call."""
    if expr is None:
        return True
    if is_literal_like(expr):
        return True
    if isinstance(expr, ast.Name):
        return UPPER_CASE_NAME.fullmatch(expr.id) is not None
    if isinstance(expr, ast.Attribute):
        return UPPER_CASE_NAME.fullmatch(expr.attr) is not None
    if isinstance(expr, ast.Call) and len(expr.args) == 0 and len(expr.keywords) == 0:
        return isinstance(expr.func, ast.Name) and expr.func.id in EMPTY_CONSTRUCTORS
    return False


BOOLEAN_BUILTINS = frozenset(
    {"isinstance", "issubclass", "hasattr", "callable", "bool", "any", "all"}
)


def _is_boolean_expression(expr: ast.expr) -> bool:
    """Comparison, Boolean operator, ``not``, Boolean constant, or a Boolean-returning builtin."""
    if isinstance(expr, ast.Compare | ast.BoolOp):
        return True
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return True
    if isinstance(expr, ast.Constant) and isinstance(expr.value, bool):
        return True
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in BOOLEAN_BUILTINS
    )


def _is_none(expr: ast.expr | None) -> bool:
    return expr is None or (isinstance(expr, ast.Constant) and expr.value is None)


def _decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _has_decorator(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, names: frozenset[str]
) -> bool:
    return any(_decorator_name(d) in names for d in node.decorator_list)


def _env_names(module: ast.Module) -> _EnvNames:
    environ: set[str] = set()
    getenv: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    bound = bound_name(alias)
                    environ.add(f"{bound}.environ")
                    getenv.add(f"{bound}.getenv")
        elif isinstance(node, ast.ImportFrom) and node.module == "os" and node.level == 0:
            for alias in node.names:
                bound = bound_name(alias)
                if alias.name == "environ":
                    environ.add(bound)
                elif alias.name == "getenv":
                    getenv.add(bound)
    return _EnvNames(frozenset(environ), frozenset(getenv))


def _annotation_root(annotation: ast.expr) -> str | None:
    target = annotation
    if isinstance(target, ast.Subscript):
        target = target.value
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_mapping_value(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Dict | ast.DictComp):
        return True
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id in MAPPING_CONSTRUCTORS
    return False


def _mapping_names(module: ast.Module) -> frozenset[str]:
    """Names bound to a dict display/constructor or annotated as a mapping, anywhere in the module.

    Not scoped (like the exception symbol table): a name that is a mapping in one
    function is taken as a mapping everywhere, which only ever raises confidence
    from approximate to exact.
    """
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Assign) and _is_mapping_value(node.value):
            for target in node.targets:
                text = dotted_name(target)
                if text is not None:
                    names.add(text)
        elif isinstance(node, ast.AnnAssign):
            text = dotted_name(node.target)
            if text is None:
                continue
            if _annotation_root(node.annotation) in MAPPING_ANNOTATIONS or _is_mapping_value(
                node.value
            ):
                names.add(text)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            if _annotation_root(node.annotation) in MAPPING_ANNOTATIONS:
                names.add(node.arg)
    return frozenset(names)


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _returns_constant(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    """The constant a one-statement helper returns, or ``None`` when it is not such a helper."""
    body = [s for s in function.body if not _is_docstring(s)]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    value = body[0].value
    if value is None:
        return ast.Constant(value=None)
    if is_constant_shaped(value):
        return value
    return None


def _index_module(module: ast.Module) -> _ModuleIndex:
    constants: dict[str, ast.expr] = {}
    helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for stmt in module.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name) and is_constant_shaped(stmt.value):
                constants[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.value is not None and is_constant_shaped(stmt.value):
                constants[stmt.target.id] = stmt.value
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            helpers[stmt.name] = stmt
    return _ModuleIndex(_env_names(module), _mapping_names(module), constants, helpers)


class _Collector:
    def __init__(self, source: SourceText, module: ast.Module) -> None:
        self.source = source
        self.index = _index_module(module)
        self.facts: list[DefaultFact] = []
        # Nodes already explained by an enclosing fact (e.g. the ``.get`` inside
        # ``os.environ.get("X") or v``); they produce no fact of their own.
        self.claimed: set[int] = set()

    # -- helpers -------------------------------------------------------------------

    def _add(
        self,
        node: ast.AST,
        scope: str,
        family: str,
        kind: str,
        subject: str,
        fallback: ast.expr | None,
        context: str,
        confidence: str,
        detail: str,
    ) -> None:
        assert isinstance(node, ast.expr | ast.excepthandler)
        fallback_text = "None"
        if fallback is not None:
            fallback_text = _text(self.source, fallback)
        self.facts.append(
            DefaultFact(
                span=node_span(self.source, node),
                scope=scope,
                family=family,
                kind=kind,
                subject=subject,
                fallback=fallback_text,
                fallback_constant=is_constant_shaped(fallback),
                context=context,
                confidence=confidence,
                detail=detail,
            )
        )

    def _confidence_for(self, fallback: ast.expr | None) -> str:
        return CONFIDENCE_EXACT if is_constant_shaped(fallback) else CONFIDENCE_APPROXIMATE

    def _env_variable(self, expr: ast.expr) -> str | None:
        """``"X"`` text when ``expr`` reads environment variable X, else ``None``."""
        if isinstance(expr, ast.Call):
            callee = dotted_name(expr.func)
            if callee is None:
                return None
            is_getenv = callee in self.index.env.getenv
            is_environ_get = (
                isinstance(expr.func, ast.Attribute)
                and expr.func.attr in GET_METHODS
                and dotted_name(expr.func.value) in self.index.env.environ
            )
            if (is_getenv or is_environ_get) and len(expr.args) >= 1:
                return _text(self.source, expr.args[0])
            return None
        if isinstance(expr, ast.Subscript):
            if dotted_name(expr.value) in self.index.env.environ:
                return _text(self.source, expr.slice)
        return None

    def _is_known_mapping(self, receiver: ast.expr) -> bool:
        if isinstance(receiver, ast.Dict | ast.DictComp):
            return True
        text = dotted_name(receiver)
        return text is not None and text in self.index.mappings

    # -- parameters and dataclass fields -------------------------------------------------

    def _parameter_defaults(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, scope: str
    ) -> None:
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        defaults: list[tuple[ast.arg, ast.expr]] = []
        offset = len(positional) - len(args.defaults)
        for index, default in enumerate(args.defaults):
            defaults.append((positional[offset + index], default))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if default is not None:
                defaults.append((arg, default))
        overload = not isinstance(node, ast.Lambda) and _has_decorator(node, OVERLOAD_DECORATORS)
        owner = "lambda" if isinstance(node, ast.Lambda) else f"{node.name}()"
        for arg, default in defaults:
            if overload and isinstance(default, ast.Constant) and default.value is Ellipsis:
                continue  # typing.overload stubs spell "has a default" as ``...``
            self._add(
                default,
                scope,
                FAMILY_PARAMETER,
                KIND_PARAMETER,
                arg.arg,
                default,
                CONTEXT_DECLARATION,
                CONFIDENCE_EXACT,
                f"parameter {arg.arg!r} of {owner} has a default value",
            )

    def _dataclass_fields(self, node: ast.ClassDef, scope: str) -> None:
        if not _has_decorator(node, DATACLASS_DECORATORS):
            return
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or stmt.value is None:
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            if _annotation_root(stmt.annotation) == "ClassVar":
                continue
            name = stmt.target.id
            value = stmt.value
            if isinstance(value, ast.Call) and _decorator_name(value.func) in FIELD_FUNCTIONS:
                keywords = {k.arg: k.value for k in value.keywords if k.arg is not None}
                if "default_factory" in keywords:
                    factory = keywords["default_factory"]
                    self._add(
                        factory,
                        scope,
                        FAMILY_PARAMETER,
                        KIND_DATACLASS_FACTORY,
                        name,
                        factory,
                        CONTEXT_DECLARATION,
                        CONFIDENCE_EXACT,
                        f"dataclass field {name!r} of {node.name} has a default_factory",
                    )
                elif "default" in keywords:
                    default = keywords["default"]
                    self._add(
                        default,
                        scope,
                        FAMILY_PARAMETER,
                        KIND_DATACLASS_FIELD,
                        name,
                        default,
                        CONTEXT_DECLARATION,
                        CONFIDENCE_EXACT,
                        f"dataclass field {name!r} of {node.name} has field(default=...)",
                    )
                continue
            self._add(
                value,
                scope,
                FAMILY_PARAMETER,
                KIND_DATACLASS_FIELD,
                name,
                value,
                CONTEXT_DECLARATION,
                CONFIDENCE_EXACT,
                f"dataclass field {name!r} of {node.name} has a default value",
            )

    # -- calls -------------------------------------------------------------------------------

    def _call(self, node: ast.Call, parent: ast.AST | None, scope: str, context: str) -> None:
        if id(node) in self.claimed:
            return
        callee = dotted_name(node.func)
        if callee is None:
            return
        positional = node.args
        if (
            callee == "getattr"
            and len(positional) == GETATTR_WITH_FALLBACK_ARITY
            and len(node.keywords) == 0
        ):
            subject = f"{_text(self.source, positional[0])}.{_text(self.source, positional[1])}"
            self._add(
                node,
                scope,
                FAMILY_MAPPING,
                KIND_GETATTR,
                subject,
                positional[GETATTR_WITH_FALLBACK_ARITY - 1],
                context,
                CONFIDENCE_EXACT,
                "getattr with a third argument substitutes the fallback for a missing attribute",
            )
            return
        variable = self._env_variable(node)
        if variable is not None:
            keywords = {k.arg for k in node.keywords}
            explicit = len(positional) >= LOOKUP_WITH_FALLBACK_ARITY or "default" in keywords
            method = node.func.attr if isinstance(node.func, ast.Attribute) else "getenv"
            fallback: ast.expr | None = None
            if len(positional) >= LOOKUP_WITH_FALLBACK_ARITY:
                fallback = positional[1]
            else:
                for keyword in node.keywords:
                    if keyword.arg == "default":
                        fallback = keyword.value
            if explicit:
                self._add(
                    node,
                    scope,
                    FAMILY_CONFIGURATION,
                    KIND_ENV_GET,
                    variable,
                    fallback,
                    context,
                    CONFIDENCE_EXACT,
                    f"{callee}(...) substitutes a fallback when environment variable "
                    f"{variable} is unset ({method})",
                )
            elif method in ("get", "getenv") and not _compares_to_none(parent):
                self._add(
                    node,
                    scope,
                    FAMILY_CONFIGURATION,
                    KIND_ENV_GET_IMPLICIT,
                    variable,
                    None,
                    context,
                    CONFIDENCE_EXACT,
                    f"{callee}({variable}) yields None when the variable is unset; "
                    "nothing here establishes that it is optional",
                )
            return
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in GET_METHODS:
            return
        if len(node.keywords) != 0:
            return
        method = node.func.attr
        receiver = node.func.value
        known = self._is_known_mapping(receiver)
        confidence = CONFIDENCE_EXACT if known else CONFIDENCE_APPROXIMATE
        receiver_note = (
            "" if known else "; the receiver's type is not established, so this is approximate"
        )
        subject = _text(self.source, receiver)
        if len(positional) >= 1:
            subject = f"{subject}[{_text(self.source, positional[0])}]"
        if len(positional) == LOOKUP_WITH_FALLBACK_ARITY:
            self._add(
                node,
                scope,
                FAMILY_MAPPING,
                KIND_MAPPING_GET,
                subject,
                positional[1],
                context,
                confidence,
                f".{method}(key, fallback) substitutes the fallback for a missing key"
                + receiver_note,
            )
        elif len(positional) == 1 and method == "get":
            if isinstance(parent, ast.Await) or _compares_to_none(parent):
                return
            key_shaped = isinstance(positional[0], ast.Constant) and isinstance(
                positional[0].value, str
            )
            if not known and not key_shaped:
                return  # ``client.get(url)``: nothing says this is a mapping lookup at all
            self._add(
                node,
                scope,
                FAMILY_MAPPING,
                KIND_MAPPING_GET_IMPLICIT,
                subject,
                None,
                context,
                confidence,
                ".get(key) yields None for a missing key; nothing here establishes that the "
                "key is optional" + receiver_note,
            )

    # -- boolean and conditional expressions ---------------------------------------------

    def _bool_or(self, node: ast.BoolOp, scope: str, context: str) -> None:
        if not isinstance(node.op, ast.Or) or context == CONTEXT_TEST:
            return
        fallback = node.values[len(node.values) - 1]
        first = node.values[0]
        variable = self._env_variable(first)
        if variable is not None:
            self.claimed.add(id(first))
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_TRUTHINESS,
                variable,
                fallback,
                context,
                self._confidence_for(fallback),
                f"'or' replaces an unset or empty environment variable {variable} with a fallback",
            )
            return
        if any(_is_boolean_expression(v) for v in node.values):
            return  # ``a in s or b == c``: Boolean logic, not a value substitution
        constant = is_constant_shaped(fallback)
        if not constant and context not in (CONTEXT_ASSIGNMENT, CONTEXT_RETURN):
            return
        if isinstance(first, ast.Call):
            self.claimed.add(id(first))  # ``m.get(k) or v``: the or is the finding
        subject = " or ".join(_text(self.source, v) for v in node.values[: len(node.values) - 1])
        detail = (
            "'or' substitutes a constant for every falsy value of the left operand "
            "(None, 0, '', empty containers alike)"
            if constant
            else f"'or' in {context} position may be a fallback or a legitimate alternative; "
            "the right operand is not a constant, so this is approximate"
        )
        self._add(
            node,
            scope,
            FAMILY_TRUTHINESS,
            KIND_TRUTHINESS_OR,
            subject,
            fallback,
            context,
            CONFIDENCE_EXACT if constant else CONFIDENCE_APPROXIMATE,
            detail,
        )

    def _if_exp(self, node: ast.IfExp, scope: str, context: str) -> None:
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            op = test.ops[0]
            right = test.comparators[0]
            if isinstance(op, NONE_COMPARISONS):
                self._nullish_ternary(node, test.left, right, op, scope, context)
                return
            if isinstance(op, ast.In | ast.NotIn):
                self._membership_ternary(node, test.left, right, op, scope, context)
                return
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, VALUE_EXPRESSIONS) and _same(test.operand, node.orelse):
                self._truthiness_ternary(node, test.operand, node.body, scope, context)
            return
        if isinstance(test, VALUE_EXPRESSIONS) and _same(test, node.body):
            self._truthiness_ternary(node, test, node.orelse, scope, context)

    def _truthiness_ternary(
        self, node: ast.IfExp, subject: ast.expr, fallback: ast.expr, scope: str, context: str
    ) -> None:
        variable = self._env_variable(subject)
        if variable is not None:
            self._claim_all(subject)
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_TRUTHINESS,
                variable,
                fallback,
                context,
                self._confidence_for(fallback),
                f"conditional expression replaces an unset or empty environment variable "
                f"{variable} with a fallback",
            )
            return
        self._claim_all(subject)
        self._add(
            node,
            scope,
            FAMILY_TRUTHINESS,
            KIND_TRUTHINESS_TERNARY,
            _text(self.source, subject),
            fallback,
            context,
            self._confidence_for(fallback),
            "'x if x else v' substitutes a value for every falsy x, exactly like 'x or v'",
        )

    def _claim_all(self, subject: ast.expr) -> None:
        for inner in ast.walk(subject):
            if isinstance(inner, ast.Call):
                self.claimed.add(id(inner))

    def _claim_matching(self, container: ast.expr, subject: ast.expr) -> None:
        """Claim calls in ``container`` that repeat a call of ``subject``."""
        wanted = {ast.dump(inner) for inner in ast.walk(subject) if isinstance(inner, ast.Call)}
        for inner in ast.walk(container):
            if isinstance(inner, ast.Call) and ast.dump(inner) in wanted:
                self.claimed.add(id(inner))

    def _nullish_ternary(
        self,
        node: ast.IfExp,
        left: ast.expr,
        right: ast.expr,
        op: ast.cmpop,
        scope: str,
        context: str,
    ) -> None:
        if _is_none(right):
            subject = left
        elif _is_none(left):
            subject = right
        else:
            return
        missing, present = (
            (node.body, node.orelse)
            if isinstance(op, MISSING_WHEN_TRUE)
            else (node.orelse, node.body)
        )
        if _is_none(missing):
            return  # ``None if x is None else f(x)`` propagates absence; it substitutes nothing
        if not _mentions(present, subject):
            return  # a choice between two values, not a fallback for ``subject``
        self._claim_all(subject)
        self._claim_matching(present, subject)
        variable = self._env_variable(subject)
        if variable is not None:
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_NULLISH,
                variable,
                missing,
                context,
                self._confidence_for(missing),
                f"conditional expression substitutes a fallback when environment variable "
                f"{variable} is unset",
            )
            return
        self._add(
            node,
            scope,
            FAMILY_NULLISH,
            KIND_NULLISH_TERNARY,
            _text(self.source, subject),
            missing,
            context,
            self._confidence_for(missing),
            "conditional expression on 'is None' substitutes a value when the subject is missing",
        )

    def _membership_ternary(
        self,
        node: ast.IfExp,
        key: ast.expr,
        mapping: ast.expr,
        op: ast.cmpop,
        scope: str,
        context: str,
    ) -> None:
        present, missing = (
            (node.body, node.orelse) if isinstance(op, ast.In) else (node.orelse, node.body)
        )
        if not isinstance(present, ast.Subscript):
            return
        if not (_same(present.value, mapping) and _same(present.slice, key)):
            return
        subject = f"{_text(self.source, mapping)}[{_text(self.source, key)}]"
        if dotted_name(mapping) in self.index.env.environ:
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_GET,
                _text(self.source, key),
                missing,
                context,
                self._confidence_for(missing),
                "membership test on os.environ substitutes a fallback for an unset variable",
            )
            return
        self._add(
            node,
            scope,
            FAMILY_MAPPING,
            KIND_MEMBERSHIP_TERNARY,
            subject,
            missing,
            context,
            self._confidence_for(missing),
            "'m[k] if k in m else v' is m.get(k, v) spelled out; it substitutes a value for a "
            "missing key",
        )

    # -- exception-to-default traces --------------------------------------------------------

    def _handler_trace(self, handler: ast.ExceptHandler, scope: str) -> None:
        statements = [s for s in handler.body if not is_pass(s) and not is_logging_statement(s)]
        if len(statements) != 1 or not isinstance(statements[0], ast.Return):
            return
        value = statements[0].value
        if value is None or is_literal_like(value):
            return  # literal returns are classified on the CatchFact (return_fallback)
        if isinstance(value, ast.Call) and is_constant_shaped(value):
            self._add(
                handler,
                scope,
                FAMILY_EXCEPTION,
                KIND_EXCEPTION_CONSTANT,
                _text(self.source, value),
                value,
                CONTEXT_RETURN,
                CONFIDENCE_EXACT,
                f"handler fabricates an empty value in place: return {_text(self.source, value)}",
            )
            return
        if isinstance(value, ast.Name):
            if value.id in self.index.constants:
                constant = self.index.constants[value.id]
                self._add(
                    handler,
                    scope,
                    FAMILY_EXCEPTION,
                    KIND_EXCEPTION_CONSTANT,
                    value.id,
                    constant,
                    CONTEXT_RETURN,
                    CONFIDENCE_APPROXIMATE,
                    f"handler returns {value.id}, bound at module level to "
                    f"{_text(self.source, constant)} (static trace; rebinding is not followed)",
                )
            return
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            name = value.func.id
            if name not in self.index.helpers:
                return
            returned = _returns_constant(self.index.helpers[name])
            if returned is None:
                return
            self._add(
                handler,
                scope,
                FAMILY_EXCEPTION,
                KIND_EXCEPTION_HELPER,
                _text(self.source, value),
                returned,
                CONTEXT_RETURN,
                CONFIDENCE_APPROXIMATE,
                f"handler delegates to {name}(), a module-level helper whose body is "
                f"'return {_text(self.source, returned)}' (static trace)",
            )

    # -- traversal ---------------------------------------------------------------------------

    def visit(self, node: ast.AST, parent: ast.AST | None, scope: str, context: str) -> str:
        """Record facts for ``node``; return the scope its children belong to."""
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            self._parameter_defaults(node, child_scope)
        elif isinstance(node, ast.ClassDef):
            self._dataclass_fields(node, child_scope)
        elif isinstance(node, ast.Call):
            self._call(node, parent, scope, context)
        elif isinstance(node, ast.BoolOp):
            self._bool_or(node, scope, context)
        elif isinstance(node, ast.IfExp):
            self._if_exp(node, scope, context)
        elif isinstance(node, ast.ExceptHandler):
            self._handler_trace(node, scope)
        return child_scope


def _compares_to_none(parent: ast.AST | None) -> bool:
    if not isinstance(parent, ast.Compare) or len(parent.ops) != 1:
        return False
    return isinstance(parent.ops[0], NONE_COMPARISONS) and (
        _is_none(parent.comparators[0]) or _is_none(parent.left)
    )


def _child_context(parent: ast.AST, field: str, inherited: str) -> str:
    """The syntactic context a child in ``field`` of ``parent`` sits in."""
    if isinstance(parent, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
        return CONTEXT_ASSIGNMENT if field == "value" else CONTEXT_EXPRESSION
    if isinstance(parent, ast.Return):
        return CONTEXT_RETURN
    if isinstance(parent, ast.Lambda):
        return CONTEXT_RETURN if field == "body" else CONTEXT_EXPRESSION
    if isinstance(parent, ast.If | ast.While | ast.Assert):
        return CONTEXT_TEST if field == "test" else CONTEXT_EXPRESSION
    if isinstance(parent, ast.IfExp):
        return CONTEXT_TEST if field == "test" else inherited
    if isinstance(parent, ast.BoolOp):
        return CONTEXT_TEST if isinstance(parent.op, ast.And) else inherited
    if isinstance(parent, ast.UnaryOp):
        return CONTEXT_TEST if isinstance(parent.op, ast.Not) else inherited
    if isinstance(parent, ast.Compare):
        return CONTEXT_TEST
    if isinstance(parent, ast.Call):
        return CONTEXT_ARGUMENT if field in ("args", "keywords") else CONTEXT_EXPRESSION
    if isinstance(parent, ast.keyword):
        return CONTEXT_ARGUMENT
    if isinstance(parent, ast.Dict):
        return CONTEXT_ASSIGNMENT if field == "values" else CONTEXT_EXPRESSION
    if isinstance(parent, ast.comprehension):
        return CONTEXT_TEST if field == "ifs" else CONTEXT_EXPRESSION
    if isinstance(parent, ast.Await | ast.Yield | ast.YieldFrom | ast.Starred):
        return inherited
    return CONTEXT_EXPRESSION


def collect_python_defaults(source: SourceText, module: ast.Module) -> tuple[DefaultFact, ...]:
    collector = _Collector(source, module)
    stack: list[tuple[ast.AST, ast.AST | None, str, str]] = [
        (module, None, MODULE_SCOPE, CONTEXT_EXPRESSION)
    ]
    while len(stack) > 0:
        node, parent, scope, context = stack.pop()
        child_scope = collector.visit(node, parent, scope, context)
        for field, value in ast.iter_fields(node):
            child_context = _child_context(node, field, context)
            if isinstance(value, ast.AST):
                stack.append((value, node, child_scope, child_context))
            elif isinstance(value, list):
                for item in reversed(value):
                    if isinstance(item, ast.AST):
                        stack.append((item, node, child_scope, child_context))
    facts = collector.facts
    facts.sort(key=lambda fact: (fact.span, fact.family, fact.kind))
    return tuple(facts)
