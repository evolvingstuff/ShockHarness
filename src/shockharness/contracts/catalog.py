"""The property-contracts catalog (``rules.property_contracts``, spec milestones P1a, P1b).

Two kinds of check, at two moments:

* :func:`catalog_issues` is about the configuration alone (property names, sinks as a
  ``callee:N`` or an assignment ``target``, sinks and compositions naming catalog
  properties) and runs whenever a configuration is loaded, a committed one included;
* the reference checks (:mod:`shockharness.contracts.references`) resolve every producer
  and sink reference against the project's files (spec §8.1) before an analysis and in
  ``config validate``. A producer must be a function of the project; a sink callee in no
  project module (a Python library, a JavaScript package or global) is accepted.
"""

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.globs import compile_globset
from shockharness.rules.defaults import module_names
from shockharness.schema import ConfigIssue

SECTION_PATH = "rules.property_contracts"
PROPERTY_NAME = re.compile(r"[a-z][a-z0-9_]*")
PYTHON_REFERENCE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
# An assignment target (decision 43): an attribute on any receiver ("innerHTML" matches
# x.innerHTML = v), or a subscript of a receiver by its final identifier ("headers[]"
# matches headers[k] = v and req.headers[k] = v).
TARGET = re.compile(r"(?P<attribute>[A-Za-z_$][\w$]*)|(?P<receiver>[A-Za-z_$][\w$]*)\[\]")
POSITION_SEPARATOR = ":"
PYTHON = "python"
JAVASCRIPT = "javascript"
TYPESCRIPT = "typescript"
PYTHON_SUFFIX = ".py"
RUNTIME_STATIC = "static"
PACKAGE_INIT = "__init__.py"
SOURCE_DIRECTORY = "src"
JAVASCRIPT_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
# Which composition operations each language has (spec §5.2a).
OPERATIONS = {
    PYTHON: ("fstring", "concat", "format"),
    JAVASCRIPT: ("template_literal", "concat"),
    TYPESCRIPT: ("template_literal", "concat"),
}
LITERAL_SATISFIES = "literal_satisfies"
COMPLETE = "complete"
# Keys of a sink entry: a call or an assignment, and the optional producer.
CALLEE = "callee"
TARGET_KEY = "target"
PRODUCER = "producer"
# The four declarations of the runtime module (spec §4.1).
REQUIRES = "requires"
PRODUCES = "produces"
PRESERVES = "preserves"
PRESERVES_EXCEPT = "preserves_except"
DECLARATIONS = (REQUIRES, PRODUCES, PRESERVES, PRESERVES_EXCEPT)
ENABLE = "enable"
# A reference names a function (module.function) or a method (module.Class.method).
FUNCTION_PARTS = 1
METHOD_PARTS = 2
NAME_PARTS = (FUNCTION_PARTS, METHOD_PARTS)


@dataclass(frozen=True)
class ContractProperty:
    name: str
    producers: tuple[str, ...]
    runtime: str
    literal_satisfies: bool


@dataclass(frozen=True)
class CalleeSink:
    language: str
    callee: str  # the reference, without the position
    position: int
    requires: frozenset[str]
    reason: str
    producer: str | None


@dataclass(frozen=True)
class TargetSink:
    """An assignment: ``<any>.<attribute> = value`` or ``<receiver>[...] = value``."""

    language: str
    text: str  # as written in the catalog
    attribute: str | None
    receiver: str | None
    requires: frozenset[str]
    reason: str
    producer: str | None


@dataclass(frozen=True)
class Composition:
    language: str
    operation: str
    inputs_require: frozenset[str]
    produces: str
    reason: str


@dataclass(frozen=True)
class Catalog:
    properties: Mapping[str, ContractProperty]
    sinks: tuple[CalleeSink, ...]
    targets: tuple[TargetSink, ...]
    compositions: tuple[Composition, ...]
    runtime_modules: tuple[str, ...]
    allow_undeclared: bool


def split_sink_callee(text: str) -> tuple[str, int] | None:
    """``"app.cloud.send:0"`` -> (``"app.cloud.send"``, 0); None when malformed."""
    reference, separator, position = text.rpartition(POSITION_SEPARATOR)
    if separator == "" or reference == "" or not position.isdigit():
        return None
    return reference, int(position)


def _optional(entry: Mapping[str, Any], key: str) -> str | None:
    """An optional key of the schema: its text, or None when the entry does not set it."""
    found: str | None = None
    if key in entry:
        found = str(entry[key])
    return found


def _flag(entry: Mapping[str, Any], key: str) -> bool:
    """An optional boolean key that is on only when written true."""
    return key in entry and entry[key] is True


def _property(entry: Mapping[str, Any]) -> ContractProperty:
    return ContractProperty(
        name=str(entry["name"]),
        producers=tuple(str(p) for p in entry["producers"]),
        runtime=str(entry["runtime"]),
        literal_satisfies=_flag(entry, LITERAL_SATISFIES),
    )


def _callee_sink(entry: Mapping[str, Any]) -> CalleeSink:
    split = split_sink_callee(str(entry[CALLEE]))
    assert split is not None, "catalog_issues rejects a malformed callee"
    return CalleeSink(
        language=str(entry["language"]),
        callee=split[0],
        position=split[1],
        requires=frozenset(str(r) for r in entry["requires"]),
        reason=str(entry["reason"]),
        producer=_optional(entry, PRODUCER),
    )


def _target_sink(entry: Mapping[str, Any]) -> TargetSink:
    match = TARGET.fullmatch(str(entry[TARGET_KEY]))
    assert match is not None, "catalog_issues rejects a malformed target"
    return TargetSink(
        language=str(entry["language"]),
        text=str(entry[TARGET_KEY]),
        attribute=match.group("attribute"),
        receiver=match.group("receiver"),
        requires=frozenset(str(r) for r in entry["requires"]),
        reason=str(entry["reason"]),
        producer=_optional(entry, PRODUCER),
    )


def _composition(entry: Mapping[str, Any]) -> Composition:
    return Composition(
        language=str(entry["language"]),
        operation=str(entry["operation"]),
        inputs_require=frozenset(str(r) for r in entry["inputs_require"]),
        produces=str(entry["produces"]),
        reason=str(entry["reason"]),
    )


def load_catalog(settings: Mapping[str, Any]) -> Catalog:
    """The catalog of a configuration that passed :func:`catalog_issues`."""
    properties = {str(entry["name"]): _property(entry) for entry in settings["properties"]}
    return Catalog(
        properties=properties,
        sinks=tuple(_callee_sink(e) for e in settings["sinks"] if CALLEE in e),
        targets=tuple(_target_sink(e) for e in settings["sinks"] if TARGET_KEY in e),
        compositions=tuple(_composition(e) for e in settings["compositions"]),
        runtime_modules=tuple(str(m) for m in settings["runtime_module"]),
        allow_undeclared=bool(settings["allow_undeclared"]),
    )


def _property_issues(entries: Sequence[Mapping[str, Any]]) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        name = str(entry["name"])
        where = f"{SECTION_PATH}.properties[{index}].name"
        if PROPERTY_NAME.fullmatch(name) is None:
            issues.append(ConfigIssue(where, f"{name!r} is not a lower_snake_case name"))
        if name in seen:
            issues.append(ConfigIssue(where, f"property {name!r} is listed twice"))
        seen.add(name)
    return issues


def _unknown_properties(
    where: str, listed: Sequence[Any], names: frozenset[str]
) -> list[ConfigIssue]:
    return [
        ConfigIssue(where, f"{name!r} is not a catalog property")
        for name in listed
        if str(name) not in names
    ]


def _sink_form_issue(where: str, entry: Mapping[str, Any]) -> ConfigIssue | None:
    if (CALLEE in entry) == (TARGET_KEY in entry):
        return ConfigIssue(
            where, "a sink names exactly one of callee (a call) or target (an assignment)"
        )
    if CALLEE in entry and split_sink_callee(str(entry[CALLEE])) is None:
        message = f"{entry[CALLEE]!r} is not <reference>:<position> (callee:N, by position)"
        return ConfigIssue(f"{where}.callee", message)
    if TARGET_KEY in entry and TARGET.fullmatch(str(entry[TARGET_KEY])) is None:
        message = (
            f"{entry[TARGET_KEY]!r} is not an attribute (innerHTML) or a subscript (headers[])"
        )
        return ConfigIssue(f"{where}.target", message)
    return None


def _sink_issues(entries: Sequence[Mapping[str, Any]], names: frozenset[str]) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for index, entry in enumerate(entries):
        where = f"{SECTION_PATH}.sinks[{index}]"
        form = _sink_form_issue(where, entry)
        if form is not None:
            issues.append(form)
        issues.extend(_unknown_properties(f"{where}.requires", entry["requires"], names))
    return issues


def _composition_issues(
    entries: Sequence[Mapping[str, Any]], names: frozenset[str]
) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for index, entry in enumerate(entries):
        where = f"{SECTION_PATH}.compositions[{index}]"
        language, operation = str(entry["language"]), str(entry["operation"])
        if operation not in OPERATIONS[language]:
            allowed = ", ".join(OPERATIONS[language])
            issues.append(
                ConfigIssue(f"{where}.operation", f"{language} has {allowed}, not {operation!r}")
            )
        issues.extend(
            _unknown_properties(f"{where}.inputs_require", entry["inputs_require"], names)
        )
        issues.extend(_unknown_properties(f"{where}.produces", [entry["produces"]], names))
    return issues


def catalog_issues(values: Mapping[str, Any]) -> list[ConfigIssue]:
    """Configuration-only problems of the section (any configuration, enabled or not)."""
    settings = values["rules"]["property_contracts"]
    names = frozenset(str(entry["name"]) for entry in settings["properties"])
    issues = [
        *_property_issues(settings["properties"]),
        *_sink_issues(settings["sinks"], names),
        *_composition_issues(settings["compositions"], names),
    ]
    if settings["runtime_mode_required"] == "verify" and settings["registration_module"] == "":
        issues.append(
            ConfigIssue(
                f"{SECTION_PATH}.registration_module",
                'runtime_mode_required = "verify" needs the module that registers the '
                "predicates (PROP005 compares it with the catalog)",
            )
        )
    if settings["enabled"] is True and len(settings["runtime_module"]) == 0:
        issues.append(
            ConfigIssue(
                f"{SECTION_PATH}.runtime_module",
                "the family is enabled but names no runtime module, so no requires, produces "
                "or preserves call can be recognized; list where `shockharness contracts "
                "install` put the file",
            )
        )
    return issues


def complete_scope(settings: Mapping[str, Any], path: str) -> bool:
    """Whether ``complete`` applies to a file: ``enforcement = "complete"``, or a match of
    ``complete_paths`` (globs matched like ``overrides`` paths, spec §9)."""
    if settings["enforcement"] == COMPLETE:
        return True
    return compile_globset([str(glob) for glob in settings["complete_paths"]]).matches(path)


def static_properties(settings: Mapping[str, Any]) -> list[str]:
    """The catalog's ``runtime = "static"`` properties, sorted: the list a test bootstrap
    passes to ``enable`` (spec §6.2)."""
    return sorted(str(p["name"]) for p in settings["properties"] if p["runtime"] == RUNTIME_STATIC)


def is_javascript_path(text: str) -> bool:
    return text.endswith(JAVASCRIPT_SUFFIXES)


def python_runtime_modules(settings: Mapping[str, Any]) -> frozenset[str]:
    """The dotted names the Python runtime module is imported as: a project-relative
    ``.py`` path gives its module names (flat or src layout), a dotted name is itself.
    The file need not be analyzed or even included (§8)."""
    names: set[str] = set()
    for entry in settings["runtime_module"]:
        text = str(entry)
        if text.endswith(PYTHON_SUFFIX):
            names.update(module_names(text))
        elif not is_javascript_path(text):
            names.add(text)
    return frozenset(names)


def javascript_runtime_modules(settings: Mapping[str, Any]) -> frozenset[str]:
    """What a JavaScript import of the runtime resolves to: a project-relative path
    (``static/js/vendor/shockharness-contracts.js``), or a package specifier for a project
    that packages the file itself. Excluded paths count (§8)."""
    return frozenset(
        str(entry) for entry in settings["runtime_module"] if not str(entry).endswith(PYTHON_SUFFIX)
    )


def runtime_callees(settings: Mapping[str, Any]) -> frozenset[str]:
    """``module.requires`` and the other three for every runtime module name, when the
    family is enabled; RESULT001 permits these as statements (§10)."""
    if settings["enabled"] is not True:
        return frozenset()
    return frozenset(
        f"{module}.{name}" for module in python_runtime_modules(settings) for name in DECLARATIONS
    )


# -- references (§8.1) --------------------------------------------------------------------


def module_file(root: Path, module: Sequence[str]) -> Path | None:
    """The project file of a dotted module, in the flat or the src layout."""
    for base in (root, root / SOURCE_DIRECTORY):
        directory = base.joinpath(*module)
        candidates = (directory.with_suffix(PYTHON_SUFFIX), directory / PACKAGE_INIT)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def read_text(path: Path) -> tuple[str | None, str]:
    """(text, "") or (None, why)."""
    # Boundary (declared in .shockharness.toml): a project file named by the catalog.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path} cannot be read ({exc})"
    return text, ""


def read_module(path: Path) -> tuple[ast.Module | None, str]:
    """(tree, "") or (None, why)."""
    text, why = read_text(path)
    if text is None:
        return None, why
    filename = str(path)
    # Boundary (declared in .shockharness.toml): the file's text is external input.
    try:
        tree = ast.parse(text, filename=filename)
    except SyntaxError as exc:
        return None, f"{path} does not parse ({exc.msg})"
    return tree, ""


def _defines(tree: ast.Module, names: Sequence[str]) -> bool:
    """``names`` is ``[function]`` or ``[Class, method]`` defined at module level."""
    definitions = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in tree.body:
        if not isinstance(node, definitions) or node.name != names[0]:
            continue
        if len(names) == FUNCTION_PARTS:
            return True
        if isinstance(node, ast.ClassDef):
            return any(
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == names[1]
                for child in node.body
            )
    return False


@dataclass(frozen=True)
class Resolution:
    """``project`` (a function or method of a project module), ``library`` (no project
    module matches), or ``missing`` (a project module that does not define it)."""

    kind: str
    detail: str


PROJECT = "project"
LIBRARY = "library"
MISSING = "missing"


def resolve_python_reference(root: Path, reference: str) -> Resolution:
    parts = reference.split(".")
    for name_parts in NAME_PARTS:
        if len(parts) <= name_parts:
            continue
        module = parts[: len(parts) - name_parts]
        path = module_file(root, module)
        if path is None:
            continue
        tree, why = read_module(path)
        if tree is None:
            return Resolution(MISSING, why)
        if _defines(tree, parts[len(parts) - name_parts :]):
            return Resolution(PROJECT, str(path))
        if name_parts == METHOD_PARTS:
            return Resolution(MISSING, f"{path} defines no {'.'.join(parts[len(module) :])}")
    return Resolution(LIBRARY, "")


def _reference_issue(
    root: Path, where: str, reference: str, must_be_project: bool
) -> ConfigIssue | None:
    if PYTHON_REFERENCE.fullmatch(reference) is None:
        return ConfigIssue(where, f"{reference!r} is not a dotted Python reference")
    resolution = resolve_python_reference(root, reference)
    if resolution.kind == MISSING:
        return ConfigIssue(where, f"{reference!r} does not resolve: {resolution.detail}")
    if must_be_project and resolution.kind == LIBRARY:
        return ConfigIssue(where, f"{reference!r} is not a function of this project")
    return None


def _python_references(settings: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    """(key path, reference, must be a project function) for every Python reference."""
    found: list[tuple[str, str, bool]] = []
    for index, entry in enumerate(settings["properties"]):
        for position, producer in enumerate(entry["producers"]):
            if POSITION_SEPARATOR in str(producer):
                continue  # path:export, a JavaScript producer (javascript_index)
            found.append(
                (f"{SECTION_PATH}.properties[{index}].producers[{position}]", str(producer), True)
            )
    for index, entry in enumerate(settings["sinks"]):
        if entry["language"] != PYTHON or CALLEE not in entry:
            continue
        split = split_sink_callee(str(entry[CALLEE]))
        if split is not None:
            found.append((f"{SECTION_PATH}.sinks[{index}].callee", split[0], False))
        if PRODUCER in entry:
            found.append((f"{SECTION_PATH}.sinks[{index}].producer", str(entry[PRODUCER]), True))
    return found


def _registration_issue(root: Path, settings: Mapping[str, Any]) -> ConfigIssue | None:
    """``registration_module`` names a project file: a dotted Python module or a path."""
    module = str(settings["registration_module"])
    if module == "":
        return None
    if is_javascript_path(module):
        exists = (root / module).is_file()
    else:
        exists = module_file(root, module.split(".")) is not None
    if exists:
        return None
    return ConfigIssue(f"{SECTION_PATH}.registration_module", f"{module!r} is not a project file")


def python_reference_issues(root: Path, values: Mapping[str, Any]) -> list[ConfigIssue]:
    """Unresolved Python references of an enabled section; nothing when it is off."""
    settings = values["rules"]["property_contracts"]
    if settings["enabled"] is not True:
        return []
    issues = [
        _registration_issue(root, settings),
        *(
            _reference_issue(root, where, reference, must_be_project)
            for where, reference, must_be_project in _python_references(settings)
        ),
    ]
    return [issue for issue in issues if issue is not None]
