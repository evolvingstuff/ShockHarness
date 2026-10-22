"""The settings of a .NET build that decide what the compiler checks (milestone G4): read
by TYPE002 (is null checking on?) and VERIFY003 (did a change turn a check down?).

Read with the standard library from the project files a revision holds: every
``*.csproj`` and ``Directory.Build.props`` (MSBuild properties) and every
``.editorconfig`` (analyzer severities), outside build output (``bin/``, ``obj/``) and
Godot's ``.godot/`` cache. MSBuild is not evaluated: a property is read as written, in
any ``PropertyGroup``, whatever its ``Condition``, and imports and ``$(...)`` references
are not followed. Comments are dropped first.

* ``Nullable``: ``enable`` or ``warnings`` turns the compiler's null checking on.
* ``TreatWarningsAsErrors``, ``CodeAnalysisTreatWarningsAsErrors``,
  ``EnableNETAnalyzers``, ``EnforceCodeStyleInBuild``: ``true`` turns a check on.
* ``WarningsAsErrors`` and ``NoWarn``: lists of codes (``;`` or ``,`` separated).
* ``AnalysisMode``, and the mode suffix of ``AnalysisLevel`` (``latest-all``): how many
  analyzer rules run, from ``all`` down to ``none``.
* ``.editorconfig``: ``dotnet_diagnostic.<ID>.severity``,
  ``dotnet_analyzer_diagnostic[.category-<C>].severity`` and the like, per section.
"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

PROJECT_SUFFIX = ".csproj"
PROPS_FILE = "Directory.Build.props"
EDITORCONFIG = ".editorconfig"
SKIPPED = frozenset({".git", "bin", "obj", ".godot", "node_modules", ".venv", "venv"})

XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
PROPERTY = re.compile(r"<(?P<name>[A-Za-z][\w.]*)(?:\s[^>]*)?>(?P<value>[^<]*)</(?P=name)\s*>")
CODES = re.compile(r"[;,\s]+")
REFERENCE = re.compile(r"\$\([^)]*\)")

NULLABLE = "Nullable"
NULLABLE_ON = frozenset({"enable", "warnings"})
TRUE = "true"
SWITCHES = (
    "TreatWarningsAsErrors",
    "CodeAnalysisTreatWarningsAsErrors",
    "EnableNETAnalyzers",
    "EnforceCodeStyleInBuild",
)
WARNINGS_AS_ERRORS = "WarningsAsErrors"
NO_WARN = "NoWarn"
ANALYSIS_MODE = "AnalysisMode"
ANALYSIS_LEVEL = "AnalysisLevel"
# Strictest first; a later level runs fewer rules or reports them more quietly.
ANALYSIS_ORDER = ("all", "recommended", "default", "minimum", "none")
SEVERITY_ORDER = ("error", "warning", "suggestion", "silent", "none")
SEVERITY_ALIASES = {"warn": "warning", "info": "suggestion", "hidden": "silent"}

SECTION = re.compile(r"^\s*\[(?P<glob>[^\]]*)\]\s*$")
ASSIGNMENT = re.compile(r"^\s*(?P<key>[^=#;]+?)\s*=\s*(?P<value>[^#;]*?)\s*(?:[#;].*)?$")
SEVERITY_KEY = re.compile(r"^dotnet_(?:analyzer_)?diagnostic(?:\.[^=]*)?\.severity$", re.I)


Properties = tuple[tuple[str, str], ...]  # (name, value) in document order


def file_name(path: str) -> str:
    _directory, _slash, name = path.rpartition("/")
    return name


def is_dotnet_settings(path: str) -> bool:
    name = file_name(path)
    return name.endswith(PROJECT_SUFFIX) or name in (PROPS_FILE, EDITORCONFIG)


def dotnet_setting_files(root: Path) -> Iterator[str]:
    """The relative paths of the .NET settings files under ``root``, in a stable order."""
    for current, directories, files in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in SKIPPED)
        for name in sorted(files):
            relative = (Path(current) / name).relative_to(root).as_posix()
            if is_dotnet_settings(relative):
                yield relative


def msbuild_properties(text: str) -> Properties:
    """Each property as written, in document order, comments dropped."""
    return tuple(
        (match.group("name"), match.group("value").strip())
        for match in PROPERTY.finditer(XML_COMMENT.sub("", text))
    )


def values(properties: Properties, name: str) -> list[str]:
    """The values a property is given, in document order (none when it is not set)."""
    return [value for written, value in properties if written == name]


def codes(values: list[str]) -> set[str]:
    """The codes of ``NoWarn``/``WarningsAsErrors`` values, ``$(NoWarn)`` references out."""
    return {
        code for value in values for code in CODES.split(REFERENCE.sub(" ", value)) if code != ""
    }


def nullable_on(properties: Properties) -> bool:
    """Null checking is on when any ``Nullable`` value turns it on."""
    return any(v.lower() in NULLABLE_ON for v in values(properties, NULLABLE))


def switched_on(properties: Properties) -> set[str]:
    """The checks a project turns on: ``Nullable=enable``, ``TreatWarningsAsErrors=true``."""
    nullable = [v.lower() for v in values(properties, NULLABLE)]
    found = {f"{NULLABLE}={v}" for v in nullable if v in NULLABLE_ON}
    found.update(
        f"{name}={TRUE}"
        for name in SWITCHES
        if any(v.lower() == TRUE for v in values(properties, name))
    )
    return found


def analysis_levels(properties: Properties) -> dict[str, str]:
    """``AnalysisMode`` and ``AnalysisLevel``'s mode, as one of :data:`ANALYSIS_ORDER`."""
    found: dict[str, str] = {}
    for value in values(properties, ANALYSIS_MODE):
        if value.lower() in ANALYSIS_ORDER:
            found[ANALYSIS_MODE] = value.lower()
    for value in values(properties, ANALYSIS_LEVEL):
        _version, _dash, mode = value.lower().rpartition("-")
        if mode in ANALYSIS_ORDER:
            found[ANALYSIS_LEVEL] = mode
    return found


def editorconfig_severities(text: str) -> dict[str, str]:
    """``"[*.cs] dotnet_diagnostic.CA1822.severity"`` -> ``"warning"``; an unknown
    severity is left out (not comparable)."""
    found: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        header = SECTION.match(line)
        if header is not None:
            section = header.group("glob")
            continue
        assignment = ASSIGNMENT.match(line)
        if assignment is None:
            continue
        key = assignment.group("key").strip()
        value = assignment.group("value").strip().lower()
        if value in SEVERITY_ALIASES:
            value = SEVERITY_ALIASES[value]
        if SEVERITY_KEY.match(key) is not None and value in SEVERITY_ORDER:
            found[f"[{section}] {key}"] = value
    return found
