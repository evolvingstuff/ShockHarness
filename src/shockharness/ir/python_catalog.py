"""API-catalog facts for Python (H5; consumed by PROCESS001, SLEEP001, RETRY001,
BATCH001, TYPE001 and STUB003 in rules/api_catalog.py).

Syntax only, per function scope (nested functions, lambdas and classes are their own):

* **process calls**: calls whose last callee segment is a process API name (``run``,
  ``call``, ``check_call``, ``check_output``, ``Popen``, ``system``, ``popen``,
  ``getoutput``, ``getstatusoutput``); the rule keeps those whose resolved callee is in its
  catalog. Recorded: ``shell=True``, whether the command is interpolated (an f-string with
  values, ``+`` or ``%`` with a non-literal, ``.format(...)``), ``check=``, whether the
  result is thrown away, and whether the function reads ``.returncode``;
* **sleeps**: calls whose last segment is ``sleep``, with whether they sit in a loop;
* **retries**: ``while True`` whose body catches an exception in a handler that never
  raises, returns or breaks; ``@retry`` / ``@retry(...)`` without a stop argument and
  ``@backoff.on_exception`` / ``on_predicate`` without ``max_tries`` / ``max_time``;
* **batch loops**: a ``for`` loop whose body has a ``try`` with a handler that only
  passes, continues or logs;
* **type escapes**: ``Any`` in an annotation (parameters, returns, annotated
  assignments) and ``cast(...)`` (``typing.cast`` or a bare ``cast`` imported from it);
* **constant predicates**: a function named as a check whose body only returns ``True``.
"""

import ast
import re

from shockharness.ir.model import (
    CHECK_ABSENT,
    CHECK_FALSE,
    CHECK_TRUE,
    OPEN_READ,
    OPEN_UNKNOWN,
    OPEN_WRITE,
    RETRY_DECORATOR,
    RETRY_LOOP,
    TYPE_ESCAPE_ANY,
    TYPE_ESCAPE_CAST,
    BatchLoop,
    CatalogFacts,
    ClassDecl,
    ConstantPredicate,
    OpenMode,
    ProcessCall,
    RetryFact,
    SleepCall,
    TypeEscape,
)
from shockharness.ir.python_async import scope_nodes
from shockharness.ir.python_catches import dotted_name, excerpt, is_logging_statement, node_span
from shockharness.source import SourceText

PROCESS_NAMES = frozenset(
    {
        "run",
        "call",
        "check_call",
        "check_output",
        "Popen",
        "system",
        "popen",
        "getoutput",
        "getstatusoutput",
    }
)
SLEEP = "sleep"
RETURNCODE = "returncode"
RETRY_DECORATORS = frozenset({"retry"})
BACKOFF_DECORATORS = frozenset({"on_exception", "on_predicate"})
RETRY_STOPS = frozenset({"stop", "stop_max_attempt_number", "tries", "attempts", "max_attempts"})
BACKOFF_STOPS = frozenset({"max_tries", "max_time"})
LOOPS = (ast.For, ast.AsyncFor, ast.While)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
ANY = "Any"
TYPING = "typing"
CAST = "cast"
FORMAT = "format"
PREDICATE = re.compile(
    r"^(is|has|can|should)_|^(check|validate|verify|authori[sz]e|authenticate|allow)"
)


def _last(callee: str) -> str:
    _receiver, _dot, last = callee.rpartition(".")
    return last


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


SLEEP_DELAY_KEYWORDS = ("delay", "seconds", "secs")


def _zero_delay(call: ast.Call) -> bool:
    """``sleep(0)`` / ``sleep(0.0)`` / ``sleep(delay=0)``: a yield, not a wait."""
    delays = [*call.args[:1], *(k.value for k in call.keywords if k.arg in SLEEP_DELAY_KEYWORDS)]
    return any(
        isinstance(d, ast.Constant) and not isinstance(d.value, bool) and d.value == 0
        for d in delays
    )


def _is_true(expr: ast.expr | None) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is True


def _interpolated(expr: ast.expr) -> bool:
    """A string command built from non-literal parts."""
    if isinstance(expr, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) for part in expr.values)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add | ast.Mod):
        return not (isinstance(expr.left, ast.Constant) and isinstance(expr.right, ast.Constant))
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
        return expr.func.attr == FORMAT
    return False


def _check(call: ast.Call) -> str:
    value = _keyword(call, "check")
    if value is None:
        return CHECK_ABSENT
    if _is_true(value):
        return CHECK_TRUE
    return CHECK_FALSE


def _handler_gives_up(handler: ast.ExceptHandler) -> bool:
    """The handler raises, returns or breaks somewhere (outside nested scopes)."""
    stack: list[ast.AST] = list(handler.body)
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Raise | ast.Return | ast.Break):
            return True
        if isinstance(node, SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def _swallowing(handler: ast.ExceptHandler) -> bool:
    """The handler only passes, continues or logs."""
    return all(
        isinstance(statement, ast.Pass | ast.Continue) or is_logging_statement(statement)
        for statement in handler.body
    )


def _tries(body: list[ast.stmt]) -> list[ast.Try | ast.TryStar]:
    """``try`` statements in ``body``, at any depth outside nested scopes and loops."""
    found: list[ast.Try | ast.TryStar] = []
    stack: list[ast.AST] = list(body)
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Try | ast.TryStar):
            found.append(node)
        if isinstance(node, (*SCOPES, *LOOPS)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


class _Scope:
    def __init__(self, source: SourceText, scope: ast.AST) -> None:
        self.source = source
        self.nodes = scope_nodes(scope)
        self.parents = {id(node): parent for node, parent in self.nodes}
        self.reads_status = any(
            isinstance(node, ast.Attribute) and node.attr == RETURNCODE for node, _ in self.nodes
        )

    def _in_loop(self, node: ast.AST) -> bool:
        current = node
        while id(current) in self.parents:
            current = self.parents[id(current)]
            if isinstance(current, LOOPS):
                return True
        return False

    def _discarded(self, call: ast.Call) -> bool:
        parent = self.parents[id(call)]
        if isinstance(parent, ast.Await):
            parent = self.parents[id(parent)]
        return isinstance(parent, ast.Expr)

    def _returned(self, call: ast.Call) -> bool:
        """``return subprocess.run(...)``, or ``result = ...`` and later ``return result``."""
        parent = self.parents[id(call)]
        if isinstance(parent, ast.Await):
            parent = self.parents[id(parent)]
        if isinstance(parent, ast.Return):
            return True
        if not isinstance(parent, ast.Assign) or len(parent.targets) != 1:
            return False
        target = parent.targets[0]
        if not isinstance(target, ast.Name):
            return False
        return any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Name)
            and node.value.id == target.id
            for node, _parent in self.nodes
        )

    def calls(self) -> tuple[list[ProcessCall], list[SleepCall]]:
        processes: list[ProcessCall] = []
        sleeps: list[SleepCall] = []
        for node, _parent in self.nodes:
            if not isinstance(node, ast.Call):
                continue
            callee = dotted_name(node.func)
            if callee is None:
                continue
            last = _last(callee)
            if last == SLEEP:
                sleeps.append(
                    SleepCall(
                        callee,
                        excerpt(node),
                        self._in_loop(node),
                        _zero_delay(node),
                        node_span(self.source, node),
                    )
                )
            elif last in PROCESS_NAMES:
                command = node.args[0] if len(node.args) > 0 else _keyword(node, "args")
                processes.append(
                    ProcessCall(
                        callee=callee,
                        text=excerpt(node),
                        shell=_is_true(_keyword(node, "shell")),
                        interpolated=command is not None and _interpolated(command),
                        check=_check(node),
                        discarded=self._discarded(node),
                        status_read=self.reads_status,
                        returned=self._returned(node),
                        span=node_span(self.source, node),
                    )
                )
        return processes, sleeps

    def loops(self) -> tuple[list[RetryFact], list[BatchLoop]]:
        retries: list[RetryFact] = []
        batches: list[BatchLoop] = []
        for node, _parent in self.nodes:
            if isinstance(node, ast.While) and _is_true(node.test):
                handlers = [h for t in _tries(node.body) for h in t.handlers]
                if any(not _handler_gives_up(h) for h in handlers):
                    retries.append(
                        RetryFact(
                            RETRY_LOOP,
                            "",
                            "while True: ... except: ...",
                            node_span(self.source, node),
                        )
                    )
            elif isinstance(node, ast.For | ast.AsyncFor):
                handlers = [h for t in _tries(node.body) for h in t.handlers]
                if any(_swallowing(h) for h in handlers):
                    header = f"for {ast.unparse(node.target)} in {ast.unparse(node.iter)}: ..."
                    batches.append(
                        BatchLoop(" ".join(header.split()), node_span(self.source, node))
                    )
        return retries, batches


def _decorator_retries(
    source: SourceText, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[RetryFact]:
    found: list[RetryFact] = []
    for decorator in node.decorator_list:
        target = decorator
        keywords: set[str | None] = set()
        if isinstance(decorator, ast.Call):
            target = decorator.func
            keywords = {k.arg for k in decorator.keywords}
        callee = dotted_name(target)
        if callee is None:
            continue
        last = _last(callee)
        unbounded = (last in RETRY_DECORATORS and len(keywords & RETRY_STOPS) == 0) or (
            last in BACKOFF_DECORATORS and len(keywords & BACKOFF_STOPS) == 0
        )
        if unbounded:
            found.append(
                RetryFact(
                    RETRY_DECORATOR, callee, f"@{excerpt(decorator)}", node_span(source, decorator)
                )
            )
    return found


def _annotations(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, FUNCTIONS):
        arguments = node.args
        every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        every.extend(a for a in (arguments.vararg, arguments.kwarg) if a is not None)
        found = [a.annotation for a in every if a.annotation is not None]
        if node.returns is not None:
            found.append(node.returns)
        return found
    if isinstance(node, ast.AnnAssign):
        return [node.annotation]
    return []


def _is_any(part: ast.AST) -> bool:
    return (isinstance(part, ast.Name) and part.id == ANY) or (
        isinstance(part, ast.Attribute) and part.attr == ANY
    )


def _any_escapes(source: SourceText, annotation: ast.expr) -> list[TypeEscape]:
    return [
        TypeEscape(TYPE_ESCAPE_ANY, excerpt(annotation), node_span(source, part))
        for part in ast.walk(annotation)
        if isinstance(part, ast.expr) and _is_any(part)
    ]


def _type_escapes(source: SourceText, module: ast.Module) -> list[TypeEscape]:
    found: list[TypeEscape] = []
    for node in ast.walk(module):
        for annotation in _annotations(node):
            found.extend(_any_escapes(source, annotation))
        if isinstance(node, ast.Call):
            callee = dotted_name(node.func)
            if callee in (CAST, f"{TYPING}.{CAST}"):
                found.append(TypeEscape(TYPE_ESCAPE_CAST, excerpt(node), node_span(source, node)))
    return found


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _method_owners(module: ast.Module) -> dict[int, str]:
    """The class of every function defined directly in a class body."""
    owners: dict[int, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef):
            owners.update((id(member), node.name) for member in node.body)
    return owners


def _constant_predicates(source: SourceText, module: ast.Module) -> list[ConstantPredicate]:
    owners = _method_owners(module)
    found: list[ConstantPredicate] = []
    for node in ast.walk(module):
        if not isinstance(node, FUNCTIONS) or PREDICATE.match(node.name) is None:
            continue
        body = [s for s in node.body if not _is_docstring(s)]
        if len(body) == 1 and isinstance(body[0], ast.Return) and _is_true(body[0].value):
            owner: str | None = None
            if id(node) in owners:
                owner = owners[id(node)]
            found.append(ConstantPredicate(node.name, owner, node_span(source, node)))
    return found


def _classes(source: SourceText, module: ast.Module) -> list[ClassDecl]:
    found: list[ClassDecl] = []
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef):
            bases = [dotted_name(base) for base in node.bases]
            names = tuple(base for base in bases if base is not None)
            found.append(ClassDecl(node.name, names, node_span(source, node)))
    return found


# CALL001: ``open`` calls whose mode decides whether they write.
OPEN = "open"
MODE_KEYWORD = "mode"
# A mode string ("r", "wb", "a+", "x", tarfile's "w:gz"); w, a, x or + writes.
MODE_SYNTAX = re.compile(r"[rwxa][bt+]*(:\w+)?")
WRITE_MODE = re.compile(r"[wax+]")
# os.open flags by name: any of these writes; flags naming none of them read.
WRITE_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL"})
FLAG_PREFIX = "O_"
# Modules whose ``open`` takes the mode second, like the builtin; any other ``.open``
# (``Path.open``) takes it first.
MODULE_OPENS = frozenset({"io", "codecs", "gzip", "bz2", "lzma", "os", "tarfile", "dbm", "shelve"})


def _mode_position(call: ast.Call) -> tuple[ast.expr | None, bool]:
    """(the mode argument, whether the call is a method whose first argument is the mode)."""
    for keyword in call.keywords:
        if keyword.arg == MODE_KEYWORD:
            return keyword.value, False
    func = call.func
    second = isinstance(func, ast.Name) or (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in MODULE_OPENS
    )
    index = 1 if second else 0
    if len(call.args) <= index:
        return None, not second
    return call.args[index], not second


def _flag_mode(expr: ast.expr) -> str | None:
    """How ``os.open`` flags open the file, from their names; None when they are not flags."""
    names = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(expr)
        if isinstance(node, ast.Attribute | ast.Name)
    }
    flags = {name for name in names if name.startswith(FLAG_PREFIX)}
    if len(flags) == 0:
        return None
    return OPEN_WRITE if len(flags & WRITE_FLAGS) > 0 else OPEN_READ


def _mode_of(mode: ast.expr, method_first: bool) -> str:
    flags = _flag_mode(mode)
    if flags is not None:
        return flags
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        if MODE_SYNTAX.fullmatch(mode.value) is not None:
            return OPEN_WRITE if WRITE_MODE.search(mode.value) is not None else OPEN_READ
    if method_first:
        return OPEN_READ  # another API's first argument (Image.open(fp)), not a mode
    return OPEN_UNKNOWN


def _open_mode(source: SourceText, call: ast.Call) -> OpenMode | None:
    func = call.func
    named = isinstance(func, ast.Name) and func.id == OPEN
    method = isinstance(func, ast.Attribute) and func.attr == OPEN
    if not named and not method:
        return None
    mode, method_first = _mode_position(call)
    if mode is None:
        return OpenMode(node_span(source, call), OPEN_READ)
    return OpenMode(node_span(source, call), _mode_of(mode, method_first))


def collect_python_catalog(source: SourceText, module: ast.Module) -> CatalogFacts:
    processes: list[ProcessCall] = []
    sleeps: list[SleepCall] = []
    retries: list[RetryFact] = []
    batches: list[BatchLoop] = []
    scopes: list[ast.AST] = [module]
    scopes.extend(node for node in ast.walk(module) if isinstance(node, SCOPES))
    for scope in scopes:
        facts = _Scope(source, scope)
        scope_processes, scope_sleeps = facts.calls()
        processes.extend(scope_processes)
        sleeps.extend(scope_sleeps)
        scope_retries, scope_batches = facts.loops()
        retries.extend(scope_retries)
        batches.extend(scope_batches)
        if isinstance(scope, FUNCTIONS):
            retries.extend(_decorator_retries(source, scope))
    return CatalogFacts(
        process_calls=tuple(sorted(processes, key=lambda p: (p.span, p.callee))),
        sleeps=tuple(sorted(sleeps, key=lambda s: (s.span, s.callee))),
        retries=tuple(sorted(retries, key=lambda r: (r.span, r.kind))),
        batch_loops=tuple(sorted(batches, key=lambda b: b.span)),
        type_escapes=tuple(sorted(_type_escapes(source, module), key=lambda t: (t.span, t.kind))),
        constant_predicates=tuple(
            sorted(_constant_predicates(source, module), key=lambda c: c.span)
        ),
        classes=tuple(sorted(_classes(source, module), key=lambda c: c.span)),
        open_modes=tuple(
            sorted(
                (
                    found
                    for node in ast.walk(module)
                    if isinstance(node, ast.Call)
                    and (found := _open_mode(source, node)) is not None
                ),
                key=lambda o: o.span,
            )
        ),
    )
