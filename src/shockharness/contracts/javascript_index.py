"""JavaScript and TypeScript modules of the project as property contracts see them (P1b).

The counterpart of :mod:`.python_index`. A call is resolved through the calling file's
imports and module-level definitions to one of:

* a runtime declaration: an import whose specifier resolves to a ``runtime_module`` path
  (excluded or not) or package;
* a function of a project file, named ``path:export`` as in the catalog (§8.1). A default
  export is ``path:default``; re-exports are followed;
* a library callee: ``package:name``, ``package:default``, or a global (``fetch``,
  ``JSON.stringify``, ``document.write``);
* nothing the analysis can name (``unknown``).

A project file is one of the analyzed files, or a file under the analyzed root.

A method resolves through its receiver when the receiver is exact
(docs/proposal-receivers.md, R2): ``this.m()`` in a class no analyzed subclass overrides
``m`` in, a module-level object literal or ``new`` singleton (in its module or imported
by name), a local the function constructs, and ``new C().m()``. ``this`` in an object
literal's method is not exact: it depends on how the method is called.
"""

import posixpath
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Node

from shockharness.complexity.callgraph import JAVASCRIPT_GLOBALS
from shockharness.contracts.catalog import (
    CALLEE,
    DECLARATIONS,
    ENABLE,
    JAVASCRIPT,
    JAVASCRIPT_SUFFIXES,
    POSITION_SEPARATOR,
    PRODUCER,
    SECTION_PATH,
    TYPESCRIPT,
    is_javascript_path,
    split_sink_callee,
)
from shockharness.contracts.disk import DiskLog, new_log
from shockharness.contracts.python_index import LIBRARY, RUNTIME, UNIT, UNKNOWN
from shockharness.ir.javascript import parse_tree
from shockharness.ir.javascript_catches import node_text
from shockharness.ir.javascript_functions import (
    DEFAULT_EXPORT,
    STAR,
    collect_javascript_imports,
    dotted_name,
)
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.javascript_receivers import (
    CLASS_DECLARATIONS,
    JsClass,
    JsReceivers,
    module_receivers,
)
from shockharness.ir.model import IMPORT_MODULE, IMPORT_NAMES, IMPORT_REEXPORT
from shockharness.schema import ConfigIssue
from shockharness.source import SourceText

# A runtime declaration's reference: the marker, a colon and the function's name.
RUNTIME_MARKER = "<runtime>"
FUNCTION_NODES = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.FUNCTION_EXPRESSION,
        Kind.ARROW_FUNCTION,
        Kind.GENERATOR_FUNCTION,
        Kind.FUNCTION,
    }
)
DECLARED_FUNCTIONS = frozenset({Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION})
DECLARATIONS_OF_VALUES = frozenset({Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION})
INDEX_FILES = tuple(f"/index{suffix}" for suffix in JAVASCRIPT_SUFFIXES)
TYPESCRIPT_SOURCES = {".js": (".ts", ".tsx"), ".mjs": (".mts",), ".cjs": (".cts",)}
DEFAULT_KEYWORD = "default"
THIS = "this"
NAMESPACE = ""  # the imported "name" of a whole-module import


@dataclass(frozen=True)
class Imported:
    specifier: str
    name: str  # an export name, "default", or NAMESPACE for the whole module


@dataclass(frozen=True)
class JsModule:
    path: str
    source: SourceText
    root: Node
    imports: Mapping[str, Imported]  # local name -> what it binds
    definitions: Mapping[str, Node]  # module-level functions by local name ("default" too)
    exports: Mapping[str, str]  # export name -> local name
    reexports: Mapping[str, Imported]  # export name -> where it comes from
    star_exports: tuple[str, ...]  # export * from "..."
    values: frozenset[str]  # other module-level bindings
    receivers: JsReceivers  # its object literals, singletons and classes


@dataclass(frozen=True)
class JsUnitReceivers:
    """One unit's receivers: the class ``this`` is an instance of (an instance method of
    a module-level class), and the locals it constructs."""

    owner: JsClass | None
    constructed: Mapping[str, Node]


NO_JS_RECEIVERS = JsUnitReceivers(None, {})


@dataclass(frozen=True)
class JsTarget:
    kind: str
    reference: str
    why: str
    module: JsModule | None
    function: Node | None


def js_unknown(why: str) -> JsTarget:
    return JsTarget(UNKNOWN, "", why, None, None)


def _library(reference: str) -> JsTarget:
    return JsTarget(LIBRARY, reference, "", None, None)


def _has_default(node: Node) -> bool:
    return any(not child.is_named and child.type == DEFAULT_KEYWORD for child in node.children)


@dataclass
class _Tables:
    definitions: dict[str, Node]
    exports: dict[str, str]
    values: set[str]


def _declarators(statement: Node, tables: _Tables) -> list[str]:
    """Module-level ``const f = () => ...`` (a function) or any other value binding."""
    names: list[str] = []
    for declarator in statement.named_children:
        if declarator.type != Kind.VARIABLE_DECLARATOR:
            continue
        name = declarator.child_by_field_name(Field.NAME)
        value = declarator.child_by_field_name(Field.VALUE)
        if name is None or name.type != Kind.IDENTIFIER:
            continue
        names.append(node_text(name))
        if value is not None and value.type in FUNCTION_NODES:
            tables.definitions[node_text(name)] = value
        else:
            tables.values.add(node_text(name))
    return names


def _declared(node: Node, tables: _Tables) -> list[str]:
    """The names a module-level declaration binds, recording functions and values."""
    if node.type in DECLARED_FUNCTIONS:
        name = node.child_by_field_name(Field.NAME)
        if name is not None:
            tables.definitions[node_text(name)] = node
            return [node_text(name)]
    if node.type in DECLARATIONS_OF_VALUES:
        return _declarators(node, tables)
    if node.type in CLASS_DECLARATIONS:
        name = node.child_by_field_name(Field.NAME)
        if name is not None:
            tables.values.add(node_text(name))  # a class: its methods resolve by receiver
            return [node_text(name)]
    return []


def _exported_name(specifier: Node) -> tuple[str, str] | None:
    """(exported name, local name) of ``{ a }`` or ``{ a as b }``."""
    name = specifier.child_by_field_name(Field.NAME)
    if name is None:
        return None
    alias = specifier.child_by_field_name(Field.ALIAS)
    if alias is None:
        return node_text(name), node_text(name)
    return node_text(alias), node_text(name)


def _export_value(value: Node, tables: _Tables) -> None:
    """``export default <function>`` or ``export default name``."""
    if value.type in FUNCTION_NODES:
        tables.definitions[DEFAULT_EXPORT] = value
        tables.exports[DEFAULT_EXPORT] = DEFAULT_EXPORT
    elif value.type == Kind.IDENTIFIER:
        tables.exports[DEFAULT_EXPORT] = node_text(value)


def _export_statement(statement: Node, tables: _Tables) -> None:
    if statement.child_by_field_name(Field.SOURCE) is not None:
        return  # a re-export: from the import facts
    declaration = statement.child_by_field_name(Field.DECLARATION)
    if declaration is not None:
        for name in _declared(declaration, tables):
            exported = name
            if _has_default(statement):
                exported = DEFAULT_EXPORT
            tables.exports[exported] = name
    value = statement.child_by_field_name(Field.VALUE)
    if value is not None:
        _export_value(value, tables)
    clauses = [c for c in statement.named_children if c.type == Kind.EXPORT_CLAUSE]
    for specifier in [s for clause in clauses for s in clause.named_children]:
        pair = _exported_name(specifier)
        if pair is not None:
            tables.exports[pair[0]] = pair[1]


def _tables(root: Node) -> _Tables:
    tables = _Tables({}, {}, set())
    for statement in root.named_children:
        if statement.type == Kind.EXPORT_STATEMENT:
            _export_statement(statement, tables)
        else:
            _declared(statement, tables)
    return tables


def build_module(path: str, text: str) -> JsModule:
    source = SourceText.from_text(text)
    root = parse_tree(text, path)
    tables = _tables(root)
    imports: dict[str, Imported] = {}
    reexports: dict[str, Imported] = {}
    stars: list[str] = []
    for fact in collect_javascript_imports(source, root):
        for imported, local in fact.names:
            if fact.kind == IMPORT_NAMES:
                imports[local] = Imported(fact.module, imported)
            elif fact.kind == IMPORT_MODULE and imported == "":
                imports[local] = Imported(fact.module, NAMESPACE)
            elif fact.kind == IMPORT_REEXPORT and imported == STAR and local == STAR:
                stars.append(fact.module)
            elif fact.kind == IMPORT_REEXPORT:
                reexports[local] = Imported(fact.module, imported)
    return JsModule(
        path=path,
        source=source,
        root=root,
        imports=imports,
        definitions=tables.definitions,
        exports=tables.exports,
        reexports=reexports,
        star_exports=tuple(stars),
        values=frozenset(tables.values - set(tables.definitions)),
        receivers=module_receivers(root),
    )


def _candidates(importer: str, specifier: str) -> list[str]:
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    joined = joined.lstrip("/")
    found = [joined, *(joined + suffix for suffix in JAVASCRIPT_SUFFIXES)]
    stem, suffix = posixpath.splitext(joined)
    if suffix in TYPESCRIPT_SOURCES:
        found.extend(stem + extension for extension in TYPESCRIPT_SOURCES[suffix])
    found.extend(joined + index for index in INDEX_FILES)
    return found


@dataclass(frozen=True)
class Specifier:
    kind: str  # RUNTIME, "path", LIBRARY (a package) or UNKNOWN
    target: str  # the path or the package
    why: str


PATH = "path"


class JsProjectIndex:
    """Project modules by path, loaded on demand; analyzed files win over disk."""

    def __init__(
        self,
        root: Path,
        analyzed: Mapping[str, str],
        runtime: frozenset[str],
        disk: DiskLog,
    ) -> None:
        self.root = root
        self.disk = disk  # every probe and read of a file that is not analyzed
        self.runtime = runtime
        self.texts = dict(analyzed)
        self.modules: dict[str, JsModule | None] = {}
        self.unreadable: dict[str, str] = {}
        self.ancestry: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}
        self.definers: dict[str, list[tuple[JsModule, JsClass]]] | None = None

    def is_runtime(self, path: str) -> bool:
        return path in self.runtime

    def module(self, path: str) -> JsModule | None:
        if path not in self.modules:
            self.modules[path] = self._load(path)
        return self.modules[path]

    def _load(self, path: str) -> JsModule | None:
        if path in self.texts:
            return build_module(path, self.texts[path])
        text, why = self.disk.read_text(self.root / path)
        if text is None:
            self.unreadable[path] = why
            return None
        return build_module(path, text)

    def _exists(self, path: str) -> bool:
        return path in self.texts or self.disk.is_file(self.root / path)

    def specifier(self, importer: str, specifier: str) -> Specifier:
        if not specifier.startswith((".", "/")):
            if specifier in self.runtime:
                return Specifier(RUNTIME, specifier, "")
            return Specifier(LIBRARY, specifier, "")
        candidates = _candidates(importer, specifier)
        for candidate in candidates:
            if candidate in self.runtime:
                return Specifier(RUNTIME, candidate, "")
        for candidate in candidates:
            if self._exists(candidate):
                return Specifier(PATH, candidate, "")
        return Specifier(UNKNOWN, "", f"{specifier!r} from {importer} is not a project file")

    def imported(self, importer: str, imported: Imported, seen: frozenset[str]) -> JsTarget:
        found = self.specifier(importer, imported.specifier)
        if found.kind == RUNTIME:
            if imported.name in DECLARATIONS or imported.name == ENABLE:
                kind = RUNTIME if imported.name in DECLARATIONS else LIBRARY
                return JsTarget(kind, f"{RUNTIME_MARKER}:{imported.name}", "", None, None)
            return _library(f"{RUNTIME_MARKER}:{imported.name}")
        if found.kind == LIBRARY:
            return _library(f"{found.target}:{imported.name}")
        if found.kind == UNKNOWN:
            return js_unknown(found.why)
        return self.export(found.target, imported.name, seen)

    def export(self, path: str, name: str, seen: frozenset[str]) -> JsTarget:
        key = f"{path}:{name}"
        if key in seen:
            return js_unknown(f"the exports of {key} form a cycle")
        module = self.module(path)
        if module is None:
            return js_unknown(self.unreadable[path])
        if name in module.exports:
            return self.local(module, module.exports[name], seen | {key})
        if name in module.reexports:
            return self.imported(path, module.reexports[name], seen | {key})
        for specifier in module.star_exports:
            found = self.imported(path, Imported(specifier, name), seen | {key})
            if found.kind != UNKNOWN:
                return found
        return js_unknown(f"{path} exports no {name}")

    def local(self, module: JsModule, name: str, seen: frozenset[str]) -> JsTarget:
        if name in module.definitions:
            return JsTarget(UNIT, f"{module.path}:{name}", "", module, module.definitions[name])
        if name in module.imports:
            return self.imported(module.path, module.imports[name], seen)
        return js_unknown(f"{module.path}:{name} is not a function")

    def resolve(self, reference: str) -> JsTarget:
        """A catalog reference: ``path:export``, ``package:name`` or a global name."""
        path, separator, name = reference.rpartition(POSITION_SEPARATOR)
        if separator == "":
            return _library(reference)
        if is_javascript_path(path):
            return self.export(path, name, frozenset())
        return _library(reference)

    def callee(
        self,
        module: JsModule,
        function: Node,
        local: frozenset[str],
        receivers: JsUnitReceivers,
    ) -> JsTarget:
        dotted = dotted_name(function)
        if dotted is None:
            return self._on_new(module, function)
        root, _dot, rest = dotted.partition(".")
        if rest != "" and "." not in rest:
            method = self._local_receiver(module, root, rest, receivers)
            if method is not None:
                return method
        if root in local:
            return js_unknown(f"{dotted}(...) is called on a local value, not resolved")
        return self._module_name(module, root, rest, dotted)

    def _module_name(self, module: JsModule, root: str, rest: str, dotted: str) -> JsTarget:
        """A call through a module-level name: an import, a definition, a value."""
        if root in module.imports:
            return self._through_import(module, module.imports[root], rest, dotted)
        if root in module.definitions and rest == "":
            return self.local(module, root, frozenset())
        if rest != "" and "." not in rest and root in module.values:
            return self.on_value(module, root, rest)
        if root in module.values or root in module.definitions:
            return js_unknown(f"{dotted}(...) is called on a module-level value, not resolved")
        if root in JAVASCRIPT_GLOBALS:
            return _library(dotted)
        return js_unknown(f"{dotted} is not imported or defined")

    def _through_import(
        self, module: JsModule, imported: Imported, rest: str, dotted: str
    ) -> JsTarget:
        if rest == "":
            name = DEFAULT_EXPORT if imported.name == NAMESPACE else imported.name
            return self.imported(module.path, Imported(imported.specifier, name), frozenset())
        if "." in rest:
            return js_unknown(f"{dotted}(...) is not a module function")
        found = self.specifier(module.path, imported.specifier)
        if imported.name == NAMESPACE or (
            found.kind == LIBRARY and imported.name == DEFAULT_EXPORT
        ):
            # ns.f() of a namespace import; Pkg.f() of a package's default export
            return self.imported(module.path, Imported(imported.specifier, rest), frozenset())
        if found.kind == PATH and imported.name != DEFAULT_EXPORT:
            target = self.module(found.target)
            if target is not None and imported.name in target.exports:
                return self.on_value(target, target.exports[imported.name], rest)
        return js_unknown(f"{dotted}(...) is a method of an imported value, not resolved")

    # -- methods through their receivers (docs/proposal-receivers.md, R2) ---------------

    def _on_new(self, module: JsModule, function: Node) -> JsTarget:
        """``new C(...).m()``; any other computed callee is unknown."""
        if function.type == Kind.MEMBER_EXPRESSION:
            receiver = function.child_by_field_name(Field.OBJECT)
            prop = function.child_by_field_name(Field.PROPERTY)
            if receiver is not None and prop is not None and receiver.type == Kind.NEW_EXPRESSION:
                constructor = receiver.child_by_field_name(Field.CONSTRUCTOR)
                if constructor is not None and dotted_name(constructor) is not None:
                    return self.on_instance(module, constructor, node_text(prop))
        return js_unknown("the callee is computed")

    def _local_receiver(
        self, module: JsModule, root: str, method: str, receivers: JsUnitReceivers
    ) -> JsTarget | None:
        """``this.m()`` in a class's instance method, ``local.m()`` on a constructed
        local; None for any other root."""
        if root == THIS and receivers.owner is not None:
            return self.through_this(module, receivers.owner, method)
        if root == THIS:
            return js_unknown(
                f"this.{method}(...): this is not an instance of a module-level class here "
                "(in an object literal's method it depends on how the method is called)"
            )
        if root in receivers.constructed:
            return self.on_instance(module, receivers.constructed[root], method)
        return None

    def on_value(self, module: JsModule, name: str, method: str) -> JsTarget:
        """``name.method()`` on a module-level value of ``module``."""
        receivers = module.receivers
        if name in receivers.objects:
            objects = receivers.objects[name]
            if method in objects.methods:
                node = objects.methods[method]
                reference = f"{module.path}:{name}.{method}"
                return JsTarget(UNIT, reference, "", module, node)
            return js_unknown(f"{module.path}:{name} has no method {method} the analysis can see")
        if name in receivers.singletons:
            return self.on_instance(module, receivers.singletons[name], method)
        return js_unknown(f"{name}.{method}(...) is called on a module-level value, not resolved")

    def on_instance(self, module: JsModule, constructor: Node, method: str) -> JsTarget:
        found = self.class_of(module, node_text(constructor))
        if found is None:
            return js_unknown(
                f"{method}(...) is called on an instance of {node_text(constructor)}, which "
                "is not a project class"
            )
        return self.method(found[0], found[1], method)

    def class_of(self, module: JsModule, name: str) -> tuple[JsModule, JsClass] | None:
        """The project class ``name`` (plain, or ``ns.Class`` through a namespace import)
        names in ``module``."""
        root, _dot, rest = name.partition(".")
        if rest == "" and root in module.receivers.classes:
            return module, module.receivers.classes[root]
        if root not in module.imports or "." in rest:
            return None
        imported = module.imports[root]
        exported = _exported(imported, rest)
        if exported is None:
            return None
        return self._exported_class(module, imported.specifier, exported)

    def _exported_class(
        self, module: JsModule, specifier: str, exported: str
    ) -> tuple[JsModule, JsClass] | None:
        """The class a project module exports as ``exported``."""
        found = self.specifier(module.path, specifier)
        if found.kind != PATH:
            return None
        target = self.module(found.target)
        if target is None or exported not in target.exports:
            return None
        local = target.exports[exported]
        if local not in target.receivers.classes:
            return None
        return target, target.receivers.classes[local]

    def method(self, module: JsModule, owner: JsClass, name: str) -> JsTarget:
        found = self._lookup(module, owner, name, frozenset())
        if found is None:
            return js_unknown(f"{module.path}:{owner.name} defines no method {name}")
        return found

    def _lookup(
        self, module: JsModule, owner: JsClass, name: str, seen: frozenset[tuple[str, str]]
    ) -> JsTarget | None:
        """``name`` in ``owner`` or its project base; None when neither defines it;
        unknown when a base the analysis cannot read might."""
        key = (module.path, owner.name)
        if key in seen:
            return js_unknown(f"the bases of {module.path}:{owner.name} form a cycle")
        if name in owner.methods:
            reference = f"{module.path}:{owner.name}.{name}"
            return JsTarget(UNIT, reference, "", module, owner.methods[name])
        if owner.base is None:
            return None
        parent = None
        if dotted_name(owner.base) is not None:
            parent = self.class_of(module, node_text(owner.base))
        if parent is None:
            return js_unknown(
                f"{module.path}:{owner.name} does not define {name}, and its base "
                f"{node_text(owner.base)} is not a project class"
            )
        return self._lookup(parent[0], parent[1], name, seen | {key})

    def through_this(self, module: JsModule, owner: JsClass, method: str) -> JsTarget:
        """``this.method()``: the class's method, unless an analyzed subclass overrides
        it (``this`` may be an instance of that subclass)."""
        target = self.method(module, owner, method)
        if target.kind != UNIT:
            return target
        overriding = self._overriding(module, owner, method)
        if overriding is not None:
            return js_unknown(
                f"{module.path}:{owner.name}.{method} is overridden in {overriding}; this "
                "may be an instance of it"
            )
        return target

    def _ancestors(self, module: JsModule, owner: JsClass) -> frozenset[tuple[str, str]]:
        key = (module.path, owner.name)
        if key not in self.ancestry:
            self.ancestry[key] = frozenset()  # a cycle in the bases ends here
            found: set[tuple[str, str]] = set()
            parent = None
            if owner.base is not None and dotted_name(owner.base) is not None:
                parent = self.class_of(module, node_text(owner.base))
            if parent is not None:
                found.add((parent[0].path, parent[1].name))
                found.update(self._ancestors(parent[0], parent[1]))
            self.ancestry[key] = frozenset(found)
        return self.ancestry[key]

    def _overriding(self, module: JsModule, owner: JsClass, name: str) -> str | None:
        """An analyzed class deriving from ``owner`` whose own body defines ``name``."""
        key = (module.path, owner.name)
        if self.definers is None:
            self.definers = self._definers()
        if name not in self.definers:
            return None
        for candidate, other in self.definers[name]:
            if key in self._ancestors(candidate, other):
                return f"{candidate.path}:{other.name}"
        return None

    def _definers(self) -> dict[str, list[tuple[JsModule, JsClass]]]:
        """Method name -> the analyzed module-level classes whose bodies define it."""
        found: dict[str, list[tuple[JsModule, JsClass]]] = {}
        for path in sorted(self.texts):
            candidate = self.module(path)
            if candidate is None:
                continue
            for other in candidate.receivers.classes.values():
                for method in other.methods:
                    if method not in found:
                        found[method] = []
                    found[method].append((candidate, other))
        return found


def _exported(imported: Imported, rest: str) -> str | None:
    """The export ``imported.rest`` names: ``rest`` of a namespace import, the imported
    name itself when there is no ``rest``."""
    if imported.name == NAMESPACE:
        return rest
    if rest != "":
        return None
    return imported.name


# -- references (§8.1) --------------------------------------------------------------------


def _producer_issue(index: JsProjectIndex, where: str, reference: str) -> ConfigIssue | None:
    path, _separator, _name = reference.rpartition(POSITION_SEPARATOR)
    if not is_javascript_path(path):
        return ConfigIssue(where, f"{reference!r} is not a function of this project")
    found = index.resolve(reference)
    if found.kind != UNIT:
        return ConfigIssue(where, f"{reference!r} does not resolve: {found.why}")
    return None


def _callee_issue(index: JsProjectIndex, where: str, reference: str) -> ConfigIssue | None:
    path, _separator, _name = reference.rpartition(POSITION_SEPARATOR)
    if not is_javascript_path(path):
        return None  # a package callee or a global
    found = index.resolve(reference)
    if found.kind == UNKNOWN:
        return ConfigIssue(where, f"{reference!r} does not resolve: {found.why}")
    return None


def _producer_references(settings: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    found: list[tuple[str, str, bool]] = []
    for index, entry in enumerate(settings["properties"]):
        for position, producer in enumerate(entry["producers"]):
            if POSITION_SEPARATOR in str(producer):
                key = f"{SECTION_PATH}.properties[{index}].producers[{position}]"
                found.append((key, str(producer), True))
    return found


def _sink_references(settings: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    found: list[tuple[str, str, bool]] = []
    for index, entry in enumerate(settings["sinks"]):
        if entry["language"] not in (JAVASCRIPT, TYPESCRIPT):
            continue
        split = None
        if CALLEE in entry:
            split = split_sink_callee(str(entry[CALLEE]))
        if split is not None:
            found.append((f"{SECTION_PATH}.sinks[{index}].callee", split[0], False))
        if PRODUCER in entry:
            found.append((f"{SECTION_PATH}.sinks[{index}].producer", str(entry[PRODUCER]), True))
    return found


def _references(settings: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    """(key path, reference, must be a project function) for every JavaScript reference."""
    return [*_producer_references(settings), *_sink_references(settings)]


def javascript_reference_issues(root: Path, values: Mapping[str, Any]) -> list[ConfigIssue]:
    settings = values["rules"]["property_contracts"]
    index = JsProjectIndex(root, {}, frozenset(), new_log(root))
    issues: list[ConfigIssue | None] = []
    for where, reference, must_be_project in _references(settings):
        check = _producer_issue if must_be_project else _callee_issue
        issues.append(check(index, where, reference))
    return [issue for issue in issues if issue is not None]


def own_children(node: Node) -> Sequence[Node]:
    return [child for child in node.named_children if child.type != Kind.COMMENT]
