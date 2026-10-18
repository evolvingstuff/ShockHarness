"""The property-contracts catalog (``rules.property_contracts``, spec milestone P1a).

Two kinds of check, at two moments:

* :func:`catalog_issues` is about the configuration alone (property names, the sink
  ``callee:N`` form, sinks naming catalog properties) and runs whenever a configuration
  is loaded, a committed one included;
* :func:`reference_issues` resolves every Python producer and sink reference against the
  project's files (spec §8.1) and runs before an analysis and in ``config validate``. A
  producer must be a function of the project; a sink callee whose module is not a project
  module is a library callee and is accepted. JavaScript references are checked in P1b.
"""

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.rules.defaults import module_names
from shockharness.schema import ConfigIssue

SECTION_PATH = "rules.property_contracts"
PROPERTY_NAME = re.compile(r"[a-z][a-z0-9_]*")
PYTHON_REFERENCE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
POSITION_SEPARATOR = ":"
PYTHON = "python"
PYTHON_SUFFIX = ".py"
PACKAGE_INIT = "__init__.py"
SOURCE_DIRECTORY = "src"
JAVASCRIPT_SUFFIXES = (".js", ".mjs", ".ts")
# The four declarations of the runtime module (spec §4.1).
REQUIRES = "requires"
PRODUCES = "produces"
PRESERVES = "preserves"
PRESERVES_EXCEPT = "preserves_except"
DECLARATIONS = (REQUIRES, PRODUCES, PRESERVES, PRESERVES_EXCEPT)
# A reference names a function (module.function) or a method (module.Class.method).
FUNCTION_PARTS = 1
METHOD_PARTS = 2
NAME_PARTS = (FUNCTION_PARTS, METHOD_PARTS)


@dataclass(frozen=True)
class ContractProperty:
    name: str
    producers: tuple[str, ...]
    runtime: str


@dataclass(frozen=True)
class CalleeSink:
    language: str
    callee: str  # the dotted reference, without the position
    position: int
    requires: frozenset[str]
    reason: str
    producer: str | None


@dataclass(frozen=True)
class Catalog:
    properties: Mapping[str, ContractProperty]
    sinks: tuple[CalleeSink, ...]
    runtime_modules: tuple[str, ...]
    allow_undeclared: bool


def split_sink_callee(text: str) -> tuple[str, int] | None:
    """``"app.cloud.send:0"`` -> (``"app.cloud.send"``, 0); None when malformed."""
    reference, separator, position = text.rpartition(POSITION_SEPARATOR)
    if separator == "" or reference == "" or not position.isdigit():
        return None
    return reference, int(position)


def load_catalog(settings: Mapping[str, Any]) -> Catalog:
    """The catalog of a configuration that passed :func:`catalog_issues`."""
    properties = {
        str(entry["name"]): ContractProperty(
            name=str(entry["name"]),
            producers=tuple(str(p) for p in entry["producers"]),
            runtime=str(entry["runtime"]),
        )
        for entry in settings["properties"]
    }
    sinks: list[CalleeSink] = []
    for entry in settings["sinks"]:
        split = split_sink_callee(str(entry["callee"]))
        assert split is not None, "catalog_issues rejects a malformed callee"
        producer: str | None = None
        if "producer" in entry:
            producer = str(entry["producer"])
        sinks.append(
            CalleeSink(
                language=str(entry["language"]),
                callee=split[0],
                position=split[1],
                requires=frozenset(str(r) for r in entry["requires"]),
                reason=str(entry["reason"]),
                producer=producer,
            )
        )
    return Catalog(
        properties=properties,
        sinks=tuple(sinks),
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


def _sink_issues(entries: Sequence[Mapping[str, Any]], names: frozenset[str]) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for index, entry in enumerate(entries):
        where = f"{SECTION_PATH}.sinks[{index}]"
        if split_sink_callee(str(entry["callee"])) is None:
            issues.append(
                ConfigIssue(
                    f"{where}.callee",
                    f"{entry['callee']!r} is not <reference>:<position> (callee:N, by position)",
                )
            )
        for required in entry["requires"]:
            if str(required) not in names:
                issues.append(
                    ConfigIssue(f"{where}.requires", f"{required!r} is not a catalog property")
                )
    return issues


def catalog_issues(values: Mapping[str, Any]) -> list[ConfigIssue]:
    """Configuration-only problems of the section (any configuration, enabled or not)."""
    settings = values["rules"]["property_contracts"]
    names = frozenset(str(entry["name"]) for entry in settings["properties"])
    issues = [
        *_property_issues(settings["properties"]),
        *_sink_issues(settings["sinks"], names),
    ]
    if settings["enabled"] is True and len(python_runtime_modules(settings)) == 0:
        issues.append(
            ConfigIssue(
                f"{SECTION_PATH}.runtime_module",
                "the family is enabled but names no Python runtime module, so no requires, "
                "produces or preserves call can be recognized; list where `shockharness "
                "contracts install` put the file",
            )
        )
    return issues


def python_runtime_modules(settings: Mapping[str, Any]) -> frozenset[str]:
    """The dotted names the Python runtime module is imported as: a project-relative
    ``.py`` path gives its module names (flat or src layout), a dotted name is itself;
    JavaScript paths are P1b. The file need not be analyzed or even included (§8)."""
    names: set[str] = set()
    for entry in settings["runtime_module"]:
        text = str(entry)
        if text.endswith(PYTHON_SUFFIX):
            names.update(module_names(text))
        elif not text.endswith(JAVASCRIPT_SUFFIXES):
            names.add(text)
    return frozenset(names)


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


def read_module(path: Path) -> tuple[ast.Module | None, str]:
    """(tree, "") or (None, why)."""
    # Boundary (declared in .shockharness.toml): a project file named by the catalog.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path} cannot be read ({exc})"
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
                continue  # path:export, a JavaScript producer (checked in P1b)
            found.append(
                (f"{SECTION_PATH}.properties[{index}].producers[{position}]", str(producer), True)
            )
    for index, entry in enumerate(settings["sinks"]):
        if entry["language"] != PYTHON:
            continue
        split = split_sink_callee(str(entry["callee"]))
        if split is not None:
            found.append((f"{SECTION_PATH}.sinks[{index}].callee", split[0], False))
        if "producer" in entry:
            found.append((f"{SECTION_PATH}.sinks[{index}].producer", str(entry["producer"]), True))
    return found


def reference_issues(root: Path, values: Mapping[str, Any]) -> list[ConfigIssue]:
    """Unresolved Python references of an enabled section; nothing when it is off."""
    settings = values["rules"]["property_contracts"]
    if settings["enabled"] is not True:
        return []
    issues = [
        _reference_issue(root, where, reference, must_be_project)
        for where, reference, must_be_project in _python_references(settings)
    ]
    return [issue for issue in issues if issue is not None]
