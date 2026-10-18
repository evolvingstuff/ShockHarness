"""What a Python method call's receiver is, read from the syntax alone
(docs/proposal-receivers.md, R1).

Each answer here is exact or absent, never a guess:

* a **module-level singleton** is a name the module binds exactly once, to a call of a
  plain or dotted name (``store = Store()``), and that no function rebinds through
  ``global``;
* a **constructed local** is a name a function binds exactly once, to such a call, and
  that is not a parameter;
* a **method's kind** says how a call through an instance or through the class supplies
  its leading parameters; a property is not a method.

Whether the called name is a project class is the consumer's question: the property
contracts index and the call graph resolve names differently.
"""

import ast
from collections import Counter
from collections.abc import Iterator, Sequence

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)

METHOD_INSTANCE = "instance"
METHOD_STATIC = "static"
METHOD_CLASS = "class"

# Decorators that make a function something other than a method of its class.
NOT_A_METHOD = frozenset({"property", "cached_property", "setter", "getter", "deleter"})
STATIC_DECORATOR = "staticmethod"
CLASS_DECORATOR = "classmethod"

# How a call reaches a method: through an instance (``obj.m()``, ``self.m()``) or through
# the class itself (``Class.m()``).
THROUGH_INSTANCE = "instance"
THROUGH_CLASS = "class"


def _own_nodes(statements: Sequence[ast.AST]) -> Iterator[ast.AST]:
    """Every node of a scope's body; nested functions, lambdas and classes are their own
    scopes (their definition node is yielded, not their contents)."""
    pending: list[ast.AST] = list(statements)
    while len(pending) > 0:
        node = pending.pop()
        yield node
        if not isinstance(node, SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _bound_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
        return [node.id]
    if isinstance(node, SCOPES) and not isinstance(node, ast.Lambda):
        return [node.name]
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [_alias_name(alias) for alias in node.names]
    if isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name is not None:
        return [node.name]
    return []


def _alias_name(alias: ast.alias) -> str:
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _binding_counts(statements: Sequence[ast.AST]) -> Counter[str]:
    return Counter(name for node in _own_nodes(statements) for name in _bound_names(node))


def is_dotted(node: ast.expr) -> bool:
    """A plain or dotted name: ``Store``, ``stores.Store``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _constructions(statements: Sequence[ast.AST]) -> dict[str, ast.expr]:
    """name -> the callee of each ``name = callee(...)`` / ``name: T = callee(...)``."""
    found: dict[str, ast.expr] = {}
    for node in _own_nodes(statements):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Call) and is_dotted(value.func):
            found[target.id] = value.func
    return found


def singleton_constructors(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level singletons: name -> the callee that built it."""
    rebound = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Global | ast.Nonlocal)
        for name in node.names
    }
    counts = _binding_counts(tree.body)
    return {
        name: callee
        for name, callee in _constructions(tree.body).items()
        if counts[name] == 1 and name not in rebound
    }


def parameter_names(arguments: ast.arguments) -> list[str]:
    names = [a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]]
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            names.append(extra.arg)
    return names


def constructed_locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.expr]:
    """A function's constructed locals: name -> the callee that built it."""
    declared = {
        name
        for node in _own_nodes(function.body)
        if isinstance(node, ast.Global | ast.Nonlocal)
        for name in node.names
    }
    counts = _binding_counts(function.body)
    excluded = declared | set(parameter_names(function.args))
    return {
        name: callee
        for name, callee in _constructions(function.body).items()
        if counts[name] == 1 and name not in excluded
    }


def _decorator_name(decorator: ast.expr) -> str:
    """The last identifier of a decorator: ``staticmethod``, ``setter`` of ``x.setter``."""
    node = decorator
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def method_kind(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """instance, static or class; None for a property (accessed, not called)."""
    names = {_decorator_name(d) for d in function.decorator_list}
    if len(names & NOT_A_METHOD) > 0:
        return None
    if STATIC_DECORATOR in names:
        return METHOD_STATIC
    if CLASS_DECORATOR in names:
        return METHOD_CLASS
    return METHOD_INSTANCE


def implicit_parameters(kind: str, through: str) -> int:
    """How many leading parameters the call supplies itself: ``self`` through an instance,
    ``cls`` either way, nothing for a static method or an instance method called through
    the class (the caller passes ``self``)."""
    if kind == METHOD_CLASS or (kind == METHOD_INSTANCE and through == THROUGH_INSTANCE):
        return 1
    return 0


def class_methods(node: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """The functions a class body defines; a later definition replaces an earlier one."""
    return {item.name: item for item in node.body if isinstance(item, FUNCTIONS)}


def receiver_parameter(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The parameter a method receives its instance or class in, when the body never
    rebinds it; None for a static method, a property or a method with no parameters."""
    kind = method_kind(function)
    if kind is None or kind == METHOD_STATIC:
        return None
    positional = [*function.args.posonlyargs, *function.args.args]
    if len(positional) == 0:
        return None
    name = positional[0].arg
    if _binding_counts(function.body)[name] > 0:
        return None
    return name
