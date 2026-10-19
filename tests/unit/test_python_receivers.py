"""The syntax-only receiver facts (docs/proposal-receivers.md, R1)."""

import ast
import textwrap

from shockharness.ir.python_receivers import (
    METHOD_CLASS,
    METHOD_INSTANCE,
    METHOD_STATIC,
    THROUGH_CLASS,
    THROUGH_INSTANCE,
    constructed_locals,
    implicit_parameters,
    method_kind,
    method_receivers,
    singleton_constructors,
)


def parse(source: str) -> ast.Module:
    return ast.parse(textwrap.dedent(source))


def names(found: dict[str, ast.expr]) -> dict[str, str]:
    return {name: ast.unparse(callee) for name, callee in found.items()}


def test_a_singleton_is_bound_once_to_a_call_and_never_rebound() -> None:
    tree = parse(
        """
        import stores
        store = stores.Store()
        twice = Store()
        twice = Store()
        later = Store()
        value = 3
        built = make()[0]
        if ready:
            guarded = Store()

        def reset():
            global later
            later = None
        """
    )
    assert names(singleton_constructors(tree)) == {
        "store": "stores.Store",
        "guarded": "Store",
    }


def test_a_constructed_local_is_bound_once_and_is_not_a_parameter() -> None:
    function = parse(
        """
        def f(given):
            local = Store()
            given = Store()
            again = Store()
            for again in items:
                pass
            with Store() as entered:
                pass

            def inner():
                hidden = Store()
        """
    ).body[0]
    assert isinstance(function, ast.FunctionDef)
    assert names(constructed_locals(function)) == {"local": "Store"}


def test_method_kinds_and_what_a_call_supplies() -> None:
    owner = parse(
        """
        class C:
            def plain(self, x): ...
            @staticmethod
            def static(x): ...
            @classmethod
            def make(cls, x): ...
            @property
            def size(self): ...
            @size.setter
            def size(self, value): ...
            def rebinds(self):
                self = other
        """
    ).body[0]
    assert isinstance(owner, ast.ClassDef)
    methods = {f.name: f for f in owner.body if isinstance(f, ast.FunctionDef)}
    assert method_kind(methods["plain"]) == METHOD_INSTANCE
    assert method_kind(methods["static"]) == METHOD_STATIC
    assert method_kind(methods["make"]) == METHOD_CLASS
    assert method_kind(methods["size"]) is None
    assert method_receivers(methods["plain"])[0] == "self"
    assert method_receivers(methods["make"])[0] == "cls"
    assert method_receivers(methods["static"])[0] is None
    assert method_receivers(methods["rebinds"])[0] is None
    assert implicit_parameters(METHOD_INSTANCE, THROUGH_INSTANCE) == 1
    assert implicit_parameters(METHOD_INSTANCE, THROUGH_CLASS) == 0
    assert implicit_parameters(METHOD_CLASS, THROUGH_CLASS) == 1
    assert implicit_parameters(METHOD_STATIC, THROUGH_INSTANCE) == 0
