"""The settings of other tools that a change can loosen (H2 part 2, VERIFY003).

Read with the standard library only (tomllib, json, configparser), from these files
at the analysis root: ``pyproject.toml`` ([tool.ruff], [tool.pytest.ini_options],
[tool.coverage.*]), ``ruff.toml`` / ``.ruff.toml``, ``setup.cfg`` / ``tox.ini`` /
``.flake8`` ([flake8], [tool:pytest] / [pytest], [coverage:*]), ``pytest.ini``,
``.coveragerc``, and ``.eslintrc.json`` / ``.eslintrc`` (JSON only; a YAML
``.eslintrc`` is reported as not comparable). Flat-config ``eslint.config.js`` and
``package.json`` ``eslintConfig`` are not read.

Each file becomes a :class:`ToolSettings`: sets of items per category, numbers, and
ESLint rule levels. :func:`tool_loosenings` says what got looser between two
versions of the same file: items added to an ignore-like category, items removed
from a select-like one, a lowered ``fail_under``, an ESLint rule turned down or
removed.
"""

import configparser
import json
import re
import shlex
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

TOOL_CONFIG_FILES = (
    "pyproject.toml",
    "ruff.toml",
    ".ruff.toml",
    "setup.cfg",
    "tox.ini",
    ".flake8",
    "pytest.ini",
    ".coveragerc",
    ".eslintrc.json",
    ".eslintrc",
)

# Adding an item to one of these turns a check off (or narrows what is tested or measured).
ADDED_IS_LOOSER = (
    "ruff.ignore",
    "ruff.extend-ignore",
    "ruff.per-file-ignores",
    "ruff.extend-per-file-ignores",
    "ruff.exclude",
    "ruff.extend-exclude",
    "flake8.ignore",
    "flake8.extend-ignore",
    "flake8.per-file-ignores",
    "flake8.exclude",
    "pytest.addopts",
    "pytest.norecursedirs",
    "coverage.omit",
    "coverage.exclude_lines",
    "coverage.exclude_also",
    "eslint.ignorePatterns",
)
# Removing an item from one of these turns a check off (or narrows what is tested).
REMOVED_IS_LOOSER = ("ruff.select", "ruff.extend-select", "pytest.testpaths")
FAIL_UNDER = "coverage.fail_under"
# Strictest first; a later level is looser. Numeric levels are read as strings.
ESLINT_LEVELS = {
    "2": "error",
    "error": "error",
    "1": "warn",
    "warn": "warn",
    "0": "off",
    "off": "off",
}
ESLINT_ORDER = ("error", "warn", "off")
# pytest options that deselect tests (with the value they take), and `-p no:<plugin>`.
PYTEST_SELECTION = ("-k", "-m", "--deselect", "--ignore", "--ignore-glob")
PYTEST_PLUGIN = "-p"
PLUGIN_DISABLE_PREFIX = "no:"
NUMBER = re.compile(r"\d+(\.\d+)?")
CODE_SEPARATORS = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class ToolSettings:
    sets: Mapping[str, frozenset[str]]
    numbers: Mapping[str, float]
    eslint_rules: Mapping[str, str]  # rule -> error | warn | off


@dataclass(frozen=True)
class ToolLoosening:
    category: str  # e.g. "ruff.per-file-ignores", "coverage.fail_under", "eslint.rules"
    item: str  # what was added, removed or lowered, as written
    message: str


class _Builder:
    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.numbers: dict[str, float] = {}
        self.eslint_rules: dict[str, str] = {}

    def add(self, category: str, items: Iterable[str]) -> None:
        if category not in self.sets:
            self.sets[category] = set()
        self.sets[category].update(item for item in items if item != "")

    def number(self, category: str, raw: Any) -> None:
        text = str(raw).strip()
        if NUMBER.fullmatch(text) is not None:
            self.numbers[category] = float(text)

    def build(self) -> ToolSettings:
        return ToolSettings(
            sets={key: frozenset(values) for key, values in self.sets.items()},
            numbers=dict(self.numbers),
            eslint_rules=dict(self.eslint_rules),
        )


def _codes(raw: Any) -> list[str]:
    """A list of codes from a TOML list or a comma/whitespace separated string."""
    if isinstance(raw, list):
        return [str(item).strip() for item in raw]
    return [part for part in CODE_SEPARATORS.split(str(raw)) if part != ""]


def _lines(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw]
    return [line.strip() for line in str(raw).splitlines() if line.strip() != ""]


def _per_file(raw: Any) -> list[str]:
    """``{"tests/*": ["S101"]}`` or flake8's ``tests/*:S101,E501`` lines -> ``pattern: CODE``."""
    items: list[str] = []
    if isinstance(raw, Mapping):
        for pattern, codes in raw.items():
            items.extend(f"{pattern}: {code}" for code in _codes(codes))
        return items
    for entry in re.split(r"[\n]+", str(raw)):
        pattern, separator, codes = entry.strip().rpartition(":")
        if separator == "" or pattern.strip() == "":
            continue
        items.extend(f"{pattern.strip()}: {code}" for code in _codes(codes))
    return items


def _shell_words(text: str) -> list[str]:
    """``addopts`` split like a shell would (``-k 'not slow'`` is two words)."""
    # Boundary (declared in .shockharness.toml): addopts is external text, and shlex
    # rejects unbalanced quotes; such a value is split on whitespace instead.
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _selection_options(raw: Any) -> list[str]:
    """The deselecting options in pytest ``addopts`` (a string split on whitespace, or a
    list), normalized as ``"-k expr"``, ``"--deselect id"``, ``"-p no:plugin"``."""
    tokens = list(raw) if isinstance(raw, list) else _shell_words(str(raw))
    found: list[str] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        name, equals, value = token.partition("=")
        if name in PYTEST_SELECTION or name == PYTEST_PLUGIN:
            if equals == "" and index + 1 < len(tokens):
                value = str(tokens[index + 1])
                index += 1
            if name != PYTEST_PLUGIN or value.startswith(PLUGIN_DISABLE_PREFIX):
                found.append(f"{name} {value}")
        elif token.startswith("-k") and token != "-k":
            found.append(f"-k {token.removeprefix('-k')}")
        index += 1
    return found


def _table(document: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """``document[key]`` when it is a table, else ``None`` (the tool is not configured)."""
    if key in document and isinstance(document[key], Mapping):
        return document[key]
    return None


def _ruff(builder: _Builder, table: Mapping[str, Any]) -> None:
    sections = [table]
    lint = _table(table, "lint")
    if lint is not None:
        sections.append(lint)
    for section in sections:
        for key in (
            "ignore",
            "extend-ignore",
            "select",
            "extend-select",
            "exclude",
            "extend-exclude",
        ):
            if key in section:
                builder.add(f"ruff.{key}", _codes(section[key]))
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            if key in section:
                builder.add(f"ruff.{key}", _per_file(section[key]))


def _pytest(builder: _Builder, table: Mapping[str, Any]) -> None:
    if "addopts" in table:
        builder.add("pytest.addopts", _selection_options(table["addopts"]))
    for key in ("testpaths", "norecursedirs"):
        if key in table:
            builder.add(f"pytest.{key}", _codes(table[key]))


def _coverage(builder: _Builder, run: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    for section in (run, report):
        if "omit" in section:
            builder.add("coverage.omit", _lines(section["omit"]))
    for key in ("exclude_lines", "exclude_also"):
        if key in report:
            builder.add(f"coverage.{key}", _lines(report[key]))
    if "fail_under" in report:
        builder.number(FAIL_UNDER, report["fail_under"])


def _toml(name: str, text: str) -> tuple[ToolSettings | None, str | None]:
    # Boundary (declared in .shockharness.toml): a tool's configuration file is external input.
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return None, f"{name} is not valid TOML: {exc}"
    builder = _Builder()
    if name != "pyproject.toml":
        _ruff(builder, document)
        return builder.build(), None
    tool = _table(document, "tool")
    if tool is None:
        return builder.build(), None
    ruff = _table(tool, "ruff")
    if ruff is not None:
        _ruff(builder, ruff)
    pytest_table = _table(tool, "pytest")
    if pytest_table is not None:
        ini_options = _table(pytest_table, "ini_options")
        if ini_options is not None:
            _pytest(builder, ini_options)
    coverage = _table(tool, "coverage")
    if coverage is not None:
        run = _table(coverage, "run")
        report = _table(coverage, "report")
        _coverage(builder, _or_empty(run), _or_empty(report))
    return builder.build(), None


def _or_empty(table: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """A coverage section that is absent configures nothing."""
    if table is None:
        return {}
    return table


def _ini(name: str, text: str) -> tuple[ToolSettings | None, str | None]:
    parser = configparser.ConfigParser(interpolation=None)
    # Boundary (declared in .shockharness.toml): a tool's configuration file is external input.
    try:
        parser.read_string(text, source=name)
    except configparser.Error as exc:
        return None, f"{name} is not a valid INI file: {exc}"
    builder = _Builder()
    _flake8(builder, _section(parser, "flake8"))
    for section in ("pytest", "tool:pytest"):
        if parser.has_section(section):
            _pytest(builder, _section(parser, section))
    run_section, report_section = "coverage:run", "coverage:report"
    if name == ".coveragerc":
        run_section, report_section = "run", "report"
    _coverage(builder, _section(parser, run_section), _section(parser, report_section))
    return builder.build(), None


def _section(parser: configparser.ConfigParser, name: str) -> dict[str, str]:
    """An INI section's keys; an absent section configures nothing."""
    if not parser.has_section(name):
        return {}
    return dict(parser[name])


def _flake8(builder: _Builder, section: Mapping[str, str]) -> None:
    for key in ("ignore", "extend-ignore", "exclude"):
        if key in section:
            builder.add(f"flake8.{key}", _codes(section[key]))
    if "per-file-ignores" in section:
        builder.add("flake8.per-file-ignores", _per_file(section["per-file-ignores"]))


def _eslint_level_key(raw: Any) -> str:
    """The severity word or number of a rule setting (``"warn"``, ``["error", {...}]``)."""
    value = raw[0] if isinstance(raw, list) and len(raw) > 0 else raw
    return str(value).strip().lower()


def _eslint(name: str, text: str) -> tuple[ToolSettings | None, str | None]:
    # Boundary (declared in .shockharness.toml): a tool's configuration file is external input.
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{name} is not JSON (a YAML .eslintrc is not compared): {exc}"
    builder = _Builder()
    if not isinstance(document, Mapping):
        return builder.build(), None
    rules = _table(document, "rules")
    if rules is not None:
        for rule, raw in rules.items():
            key = _eslint_level_key(raw)
            if key in ESLINT_LEVELS:  # an unknown level is not comparable: left out
                builder.eslint_rules[str(rule)] = ESLINT_LEVELS[key]
    if "ignorePatterns" in document:
        builder.add("eslint.ignorePatterns", _codes(document["ignorePatterns"]))
    return builder.build(), None


def read_tool_settings(name: str, text: str) -> tuple[ToolSettings | None, str | None]:
    """Parse one of :data:`TOOL_CONFIG_FILES`. Returns (settings, error); one is set."""
    if name in ("pyproject.toml", "ruff.toml", ".ruff.toml"):
        return _toml(name, text)
    if name in (".eslintrc.json", ".eslintrc"):
        return _eslint(name, text)
    return _ini(name, text)


def _difference(settings: ToolSettings, other: ToolSettings, category: str) -> frozenset[str]:
    """The items ``settings`` configures for ``category`` that ``other`` does not."""
    if category not in settings.sets:
        return frozenset()  # configures nothing there, so nothing beyond other
    if category not in other.sets:
        return settings.sets[category]
    return settings.sets[category] - other.sets[category]


def _set_loosenings(before: ToolSettings, after: ToolSettings) -> list[ToolLoosening]:
    found: list[ToolLoosening] = []
    for category in ADDED_IS_LOOSER:
        for item in sorted(_difference(after, before, category)):
            found.append(ToolLoosening(category, item, f"{category} now includes {item!r}"))
    for category in REMOVED_IS_LOOSER:
        for item in sorted(_difference(before, after, category)):
            found.append(ToolLoosening(category, item, f"{category} no longer includes {item!r}"))
    return found


def _fail_under(before: ToolSettings, after: ToolSettings) -> list[ToolLoosening]:
    if FAIL_UNDER not in before.numbers:
        return []
    old_bar = before.numbers[FAIL_UNDER]
    if FAIL_UNDER not in after.numbers:
        new_bar = "removed"
    elif after.numbers[FAIL_UNDER] < old_bar:
        new_bar = f"{after.numbers[FAIL_UNDER]:g}"
    else:
        return []
    return [
        ToolLoosening(FAIL_UNDER, new_bar, f"{FAIL_UNDER} lowered from {old_bar:g} to {new_bar}")
    ]


def _eslint_loosenings(before: ToolSettings, after: ToolSettings) -> list[ToolLoosening]:
    found: list[ToolLoosening] = []
    off = ESLINT_ORDER[len(ESLINT_ORDER) - 1]
    for rule, old_level in sorted(before.eslint_rules.items()):
        if old_level == off:
            continue
        if rule not in after.eslint_rules:
            message = f"eslint rule {rule!r} ({old_level}) was removed"
            found.append(ToolLoosening("eslint.rules", rule, message))
            continue
        new_level = after.eslint_rules[rule]
        if ESLINT_ORDER.index(new_level) > ESLINT_ORDER.index(old_level):
            message = f"eslint rule {rule!r} turned down from {old_level} to {new_level}"
            found.append(ToolLoosening("eslint.rules", rule, message))
    return found


def tool_loosenings(before: ToolSettings, after: ToolSettings) -> list[ToolLoosening]:
    """What ``after`` turns off or narrows compared with ``before``."""
    return [
        *_set_loosenings(before, after),
        *_fail_under(before, after),
        *_eslint_loosenings(before, after),
    ]
