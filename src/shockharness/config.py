"""Configuration loading: discovery, precedence, validation, merge, digest.

Sources (highest first): explicit ``--config`` path, ``.shockharness.toml`` or
``shockharness.toml`` in the root (both present is an error), ``[tool.shockharness]``
in ``pyproject.toml``, bundled defaults. Exactly one user source applies. A
shadowed ``pyproject.toml`` table is reported in ``notes`` rather than silently
ignored.

Layers (lowest first): bundled defaults < the selected built-in profile
(``profile = "..."``; an overlay shipped as package data) < the user source <
the two command-line overrides (``--profile``, ``--parse-errors``). Every key
records the layer it came from in ``origins``.

Nothing here reads environment variables or executes configuration content.
"""

import copy
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from shockharness.errors import ConfigError
from shockharness.globs import validate_glob
from shockharness.rules import registry
from shockharness.rules.defaults import loosened_modes
from shockharness.schema import (
    NAMED_CONSTANT_MODES,
    PROFILE_STRICT,
    PROFILES,
    SECTION_SEVERITIES,
    ConfigIssue,
    boundary_exceptions,
    validate_shape,
)

TOOL_TABLE = ("tool", "shockharness")
DEDICATED_FILENAME = ".shockharness.toml"
DEDICATED_FILENAMES = (DEDICATED_FILENAME, "shockharness.toml")
PYPROJECT_FILENAME = "pyproject.toml"
PROFILE_KEY = "profile"
PARSE_ERRORS_KEY = "parse_errors"
UNSUPPORTED_SOURCES_KEY = "unsupported_sources"
UNSUPPORTED_FAIL = "fail"
UNSUPPORTED_WARN = "warn"
UNSUPPORTED_IGNORE = "ignore"
PROFILES_PACKAGE = "shockharness.profiles"
# Sections that carry a `severity` cap (see rules/severity.py), with the rules they cover.
SEVERITY_SECTIONS: Mapping[str, str] = {
    "magic_numbers": "MAGIC001",
    "exceptions": "EXC001-EXC003",
    "defaults": "DEF001-DEF006",
}

# A boundary names one exception class: a dotted identifier path, never a wildcard.
EXCEPTION_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")

NAMED_CONSTANT_ALLOW = NAMED_CONSTANT_MODES[1]

TIER_CLI = "cli"
TIER_DEDICATED = "dedicated"
TIER_PYPROJECT = "pyproject"
TIER_BUNDLED = "bundled"
# Origin labels for the two layers that are not sources: the profile overlay
# (``profile:<name>``) and the command-line overrides.
ORIGIN_PROFILE_PREFIX = "profile:"
ORIGIN_CLI_OVERRIDE = "cli_override"

SUPPORTED_EXTENSIONS: Mapping[str, str] = {
    ".py": registry.PYTHON,
    ".js": registry.JAVASCRIPT,
    ".mjs": registry.JAVASCRIPT,
    ".cjs": registry.JAVASCRIPT,
}


@dataclass(frozen=True)
class ConfigSource:
    tier: str
    path: str


@dataclass(frozen=True)
class CliOverrides:
    """The only configuration keys the command line may override.

    ``--profile`` replaces the profile layer (the repository's own keys still apply on
    top of it); ``--parse-errors`` decides whether syntax failures fail the run. Both
    are recorded in ``origins`` as ``cli_override`` and in ``notes``.
    """

    profile: str | None
    parse_errors: str | None


NO_OVERRIDES = CliOverrides(profile=None, parse_errors=None)


@dataclass(frozen=True)
class EffectiveConfig:
    values: Mapping[str, Any]
    source: ConfigSource
    origins: Mapping[str, str]
    notes: tuple[str, ...]
    deviations: tuple[str, ...]
    digest: str

    def section(self, dotted: str) -> Mapping[str, Any]:
        node: Any = self.values
        for key in dotted.split("."):
            node = node[key]
        return node

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": {"tier": self.source.tier, "path": self.source.path},
            "digest": self.digest,
            "notes": list(self.notes),
            "deviations": list(self.deviations),
            "origins": dict(sorted(self.origins.items())),
            "values": json.loads(json.dumps(self.values)),
        }


def _read_toml(path: Path) -> dict[str, Any]:
    # Boundary (declared in .shockharness.toml): reading and decoding a config file.
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read configuration file: {exc}", str(path)) from exc
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"configuration file is not valid UTF-8: {exc}", str(path)) from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}", str(path)) from exc


def _extract_tool_table(document: Mapping[str, Any], origin: str) -> dict[str, Any] | None:
    node: Any = document
    for key in TOOL_TABLE:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if not isinstance(node, dict):
        raise ConfigError("[tool.shockharness] must be a table", origin)
    return node


def load_bundled_defaults() -> dict[str, Any]:
    text = resources.files("shockharness").joinpath("defaults.toml").read_text(encoding="utf-8")
    document = tomllib.loads(text)
    table = _extract_tool_table(document, "bundled defaults.toml")
    if table is None:
        raise ConfigError("bundled defaults are missing [tool.shockharness]", "defaults.toml")
    return table


def profile_overlay_text(name: str) -> str:
    """The TOML text of built-in profile ``name`` (package data)."""
    if name not in PROFILES:
        raise ConfigError(f"unknown profile; known profiles: {', '.join(PROFILES)}", name)
    return resources.files(PROFILES_PACKAGE).joinpath(f"{name}.toml").read_text(encoding="utf-8")


def load_profile_overlay(name: str) -> dict[str, Any]:
    """The keys built-in profile ``name`` changes relative to the bundled defaults.

    An overlay is validated like user configuration and may not set ``profile`` itself.
    """
    origin = f"bundled profiles/{name}.toml"
    table = _extract_tool_table(tomllib.loads(profile_overlay_text(name)), origin)
    if table is None:
        raise ConfigError("bundled profile is missing [tool.shockharness]", origin)
    issues = validate_shape(table)
    if PROFILE_KEY in table:
        issues.append(ConfigIssue(PROFILE_KEY, "a profile overlay cannot select a profile"))
    if len(issues) > 0:
        raise ConfigError(
            "bundled profile is invalid:\n  " + "\n  ".join(issue.render() for issue in issues),
            origin,
        )
    return table


def _deep_merge(
    base: dict[str, Any],
    override: Mapping[str, Any],
    origins: dict[str, str],
    origin_label: str,
    prefix: str,
) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        dotted = key if prefix == "" else f"{prefix}.{key}"
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = _deep_merge(merged[key], value, origins, origin_label, dotted)
        else:
            merged[key] = copy.deepcopy(value)
            _set_origin_subtree(origins, dotted, value, origin_label)
    return merged


def _set_origin_subtree(origins: dict[str, str], dotted: str, value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _set_origin_subtree(origins, f"{dotted}.{key}", child, label)
        return
    origins[dotted] = label


def _record_origins(origins: dict[str, str], values: Mapping[str, Any], label: str) -> None:
    for key, value in values.items():
        _set_origin_subtree(origins, key, value, label)


def _discover_source(
    root: Path, explicit: Path | None
) -> tuple[ConfigSource, dict[str, Any], list[str]]:
    notes: list[str] = []
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError("explicit configuration file does not exist", str(explicit))
        document = _read_toml(explicit)
        table = _extract_tool_table(document, str(explicit))
        if table is None:
            raise ConfigError("configuration file has no [tool.shockharness] table", str(explicit))
        return ConfigSource(TIER_CLI, str(explicit)), table, notes

    present = [root / name for name in DEDICATED_FILENAMES if (root / name).is_file()]
    if len(present) > 1:
        listed = " and ".join(str(path) for path in present)
        raise ConfigError(
            "two dedicated configuration files exist; keep exactly one of "
            + ", ".join(DEDICATED_FILENAMES),
            listed,
        )
    pyproject = root / PYPROJECT_FILENAME
    pyproject_table: dict[str, Any] | None = None
    if pyproject.is_file():
        pyproject_table = _extract_tool_table(_read_toml(pyproject), str(pyproject))

    if len(present) == 1:
        dedicated = present[0]
        table = _extract_tool_table(_read_toml(dedicated), str(dedicated))
        if table is None:
            raise ConfigError("configuration file has no [tool.shockharness] table", str(dedicated))
        if pyproject_table is not None:
            notes.append(
                f"{pyproject} also has a [tool.shockharness] table; it is shadowed by "
                f"{dedicated} and ignored"
            )
        return ConfigSource(TIER_DEDICATED, str(dedicated)), table, notes

    if pyproject_table is not None:
        return ConfigSource(TIER_PYPROJECT, str(pyproject)), pyproject_table, notes

    notes.append("no project configuration found; bundled strict defaults apply")
    return ConfigSource(TIER_BUNDLED, "defaults.toml"), {}, notes


def _semantic_issues(values: Mapping[str, Any]) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    for list_key in ("include", "exclude"):
        for index, pattern in enumerate(values[list_key]):
            problem = validate_glob(pattern)
            if problem is not None:
                issues.append(ConfigIssue(f"{list_key}[{index}]", problem))
    for index, pattern in enumerate(values["include"]):
        suffix = _literal_extension(pattern)
        if suffix is not None and suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            issues.append(
                ConfigIssue(
                    f"include[{index}]",
                    f"extension {suffix!r} is not a supported language (supported: {supported})",
                )
            )
    for index, override in enumerate(values["overrides"]):
        key = f"overrides[{index}]"
        if len(override["paths"]) == 0:
            issues.append(ConfigIssue(f"{key}.paths", "must list at least one path"))
        if len(override["disable"]) == 0:
            issues.append(ConfigIssue(f"{key}.disable", "must list at least one rule ID"))
        for p_index, pattern in enumerate(override["paths"]):
            problem = validate_glob(pattern)
            if problem is not None:
                issues.append(ConfigIssue(f"{key}.paths[{p_index}]", problem))
        for r_index, rule_id in enumerate(override["disable"]):
            if not registry.is_known_rule(rule_id):
                known = ", ".join(registry.rule_ids())
                issues.append(
                    ConfigIssue(
                        f"{key}.disable[{r_index}]", f"unknown rule ID {rule_id!r} (known: {known})"
                    )
                )
    exceptions = values["rules"]["exceptions"]
    for index, boundary in enumerate(exceptions["boundaries"]):
        key = f"rules.exceptions.boundaries[{index}]"
        problem = validate_glob(boundary["path"])
        if problem is not None:
            issues.append(ConfigIssue(f"{key}.path", problem))
        issues.extend(_boundary_exception_issues(boundary, key))
    for index, guard in enumerate(exceptions["transparent_guards"]):
        if EXCEPTION_NAME.fullmatch(guard) is None:
            issues.append(
                ConfigIssue(
                    f"rules.exceptions.transparent_guards[{index}]",
                    "must be the guard's callee as written, a dotted name such as "
                    "'rethrowUnexpectedError' or 'errors.rethrow_unexpected'",
                )
            )
    for index, manager in enumerate(exceptions["capture_managers"]):
        if EXCEPTION_NAME.fullmatch(manager) is None:
            issues.append(
                ConfigIssue(
                    f"rules.exceptions.capture_managers[{index}]",
                    "must be the manager's qualified class name such as "
                    "'app.errors.CapturedExceptionContext'",
                )
            )
    magic = values["rules"]["magic_numbers"]
    for index, pattern in enumerate(magic["configuration_files"]):
        problem = validate_glob(pattern)
        if problem is not None:
            issues.append(ConfigIssue(f"rules.magic_numbers.configuration_files[{index}]", problem))
    return issues


def _boundary_exception_issues(boundary: Mapping[str, Any], key: str) -> list[ConfigIssue]:
    """Exactly one of ``exception`` / ``exceptions``, each a dotted class name."""
    has_single = "exception" in boundary
    has_list = "exceptions" in boundary
    if has_single == has_list:
        return [
            ConfigIssue(
                key,
                "needs exactly one of 'exception' (one class name) or 'exceptions' (a list of "
                "class names approved for the same path with one reason)",
            )
        ]
    if has_list and len(boundary["exceptions"]) == 0:
        return [ConfigIssue(f"{key}.exceptions", "must list at least one exception class name")]
    issues: list[ConfigIssue] = []
    if has_single:
        names = [(f"{key}.exception", str(boundary["exception"]))]
    else:
        names = [(f"{key}.exceptions[{i}]", str(n)) for i, n in enumerate(boundary["exceptions"])]
    for name_key, name in names:
        if EXCEPTION_NAME.fullmatch(name) is None:
            issues.append(
                ConfigIssue(
                    name_key,
                    "must be a dotted exception class name such as 'OSError' or "
                    "'requests.exceptions.Timeout'; wildcards and bare except cannot be approved",
                )
            )
    return issues


def _literal_extension(pattern: str) -> str | None:
    """Return ``.ext`` when the glob ends in a literal extension, else ``None``."""
    parts = pattern.rsplit("/", 1)
    basename = parts[len(parts) - 1]
    if "." not in basename:
        return None
    dot_parts = basename.rsplit(".", 1)
    extension = dot_parts[len(dot_parts) - 1]
    if extension == "" or any(ch in extension for ch in "*?[]"):
        return None
    return "." + extension


def _deviations(values: Mapping[str, Any]) -> tuple[str, ...]:
    """Explicit departures from the strict profile, always surfaced in reports."""
    found: list[str] = []
    profile = values[PROFILE_KEY]
    if profile != PROFILE_STRICT:
        found.append(
            f"profile is {profile!r}, below {PROFILE_STRICT!r}; the lines that follow are what "
            "it changes (see docs/configuration.md, Profiles)"
        )
    rules = values["rules"]
    for section_name in sorted(rules):
        if rules[section_name]["enabled"] is False:
            found.append(f"rules.{section_name} is disabled")
    for section_name in SEVERITY_SECTIONS:
        if rules[section_name]["severity"] != SECTION_SEVERITIES[0]:
            found.append(
                f"rules.{section_name}.severity is {rules[section_name]['severity']!r}; "
                f"{SEVERITY_SECTIONS[section_name]} findings are reported as review and never "
                "fail the gate"
            )
    if values["complexity"]["enabled"] is False:
        found.append("complexity is disabled")
    elif values["complexity"]["cyclomatic_counts_boolean_operators"] is False:
        found.append(
            "complexity.cyclomatic_counts_boolean_operators is false; cyclomatic/1 counts "
            "fewer decisions than its documented convention"
        )
    allowed = rules["magic_numbers"]["allowed_values"]
    extra = sorted({str(v) for v in allowed if v != 0 and v != 1})
    if len(extra) > 0:
        found.append("rules.magic_numbers.allowed_values permits " + ", ".join(extra))
    if rules["magic_numbers"]["allow_unary_negative_one"] is True:
        found.append("rules.magic_numbers.allow_unary_negative_one is enabled")
    if rules["magic_numbers"]["named_constant_definitions"] == NAMED_CONSTANT_ALLOW:
        found.append(
            f"rules.magic_numbers.named_constant_definitions is {NAMED_CONSTANT_ALLOW!r}; a "
            "numeric literal that is the whole value of a module-level named constant "
            "definition is not reported"
        )
    if values["parse_errors"] != "fail":
        found.append(
            f"parse_errors is {values['parse_errors']!r}; syntax failures do not fail the gate"
        )
    if values[UNSUPPORTED_SOURCES_KEY] == UNSUPPORTED_IGNORE:
        found.append(
            "unsupported_sources is 'ignore'; included files no adapter can parse are only "
            "counted, never listed or failed"
        )
    exceptions = rules["exceptions"]
    if exceptions["transparent_rethrow"] is True:
        found.append(
            "rules.exceptions.transparent_rethrow is enabled; handlers that only re-raise "
            "pass EXC001 outside any boundary"
        )
    for index, guard in enumerate(exceptions["transparent_guards"]):
        found.append(
            f"rules.exceptions.transparent_guards[{index}] treats a handler whose first "
            f"statement is {guard}(<caught exception>) as narrowed by that guard; EXC001 does "
            "not report the catch and EXC002 classifies the statements after the guard"
        )
    for index, manager in enumerate(exceptions["capture_managers"]):
        found.append(
            f"rules.exceptions.capture_managers[{index}] treats `with {manager}(T, ...):` as a "
            "catch of the exception types T passed to it; it is approved by boundaries like an "
            "except handler and reported by EXC001 otherwise"
        )
    for index, boundary in enumerate(exceptions["boundaries"]):
        approved = ", ".join(boundary_exceptions(boundary))
        found.append(
            f"rules.exceptions.boundaries[{index}] approves catching {approved} "
            f"in {boundary['path']} ({boundary['language']}): {boundary['reason']}"
        )
    found.extend(loosened_modes(rules["defaults"]))
    for index, override in enumerate(values["overrides"]):
        disabled = ", ".join(override["disable"])
        paths = ", ".join(override["paths"])
        found.append(f"overrides[{index}] disables {disabled} for {paths}: {override['reason']}")
    return tuple(found)


CACHE_KEY = "cache"


def config_digest(values: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of every key that can change a result: the
    ``cache`` table (where results are stored, and whether) is left out, so toggling
    the cache neither changes the digest a baseline records nor the cache key."""
    policy = {key: value for key, value in values.items() if key != CACHE_KEY}
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(root: Path, explicit: Path | None) -> EffectiveConfig:
    """Discover, validate, and merge configuration for ``root`` with no CLI overrides.

    Raises :class:`ConfigError` listing every shape and semantic problem found.
    """
    return load_config_with_overrides(root, explicit, NO_OVERRIDES)


def _validate_overrides(overrides: CliOverrides) -> None:
    if overrides.profile is not None and overrides.profile not in PROFILES:
        raise ConfigError(
            f"--profile must be one of {', '.join(PROFILES)}", repr(overrides.profile)
        )
    parse_choices = ("fail", "warn")
    if overrides.parse_errors is not None and overrides.parse_errors not in parse_choices:
        raise ConfigError(
            f"--parse-errors must be one of {', '.join(parse_choices)}",
            repr(overrides.parse_errors),
        )


def load_config_with_overrides(
    root: Path, explicit: Path | None, overrides: CliOverrides
) -> EffectiveConfig:
    """Discover, validate, and merge configuration for ``root``.

    Layers, lowest first: bundled defaults, the profile overlay (selected by
    ``--profile``, else the user source's ``profile`` key, else ``strict``), the user
    source, the CLI overrides. Raises :class:`ConfigError` listing every shape and
    semantic problem found.
    """
    _validate_overrides(overrides)
    defaults = load_bundled_defaults()
    source, user_table, notes = _discover_source(root, explicit)

    issues = validate_shape(user_table)
    if len(issues) > 0:
        raise ConfigError(
            "configuration is invalid:\n  " + "\n  ".join(issue.render() for issue in issues),
            source.path,
        )

    profile_name = str(defaults[PROFILE_KEY])
    if PROFILE_KEY in user_table:
        profile_name = str(user_table[PROFILE_KEY])
    if overrides.profile is not None:
        if overrides.profile != profile_name:
            notes.append(
                f"profile {overrides.profile!r} selected by --profile on the command line "
                f"replaces profile {profile_name!r}; the configuration file's other keys "
                "still apply on top of it"
            )
        profile_name = overrides.profile

    origins: dict[str, str] = {}
    _record_origins(origins, defaults, TIER_BUNDLED)
    overlay = load_profile_overlay(profile_name)
    merged = _deep_merge(defaults, overlay, origins, ORIGIN_PROFILE_PREFIX + profile_name, "")
    merged = _deep_merge(merged, user_table, origins, source.tier, "")

    cli_layer: dict[str, Any] = {}
    if overrides.profile is not None:
        cli_layer[PROFILE_KEY] = overrides.profile
    if overrides.parse_errors is not None:
        cli_layer[PARSE_ERRORS_KEY] = overrides.parse_errors
        notes.append(
            f"parse_errors = {overrides.parse_errors!r} set by --parse-errors on the command "
            f"line (configured value: {merged[PARSE_ERRORS_KEY]!r})"
        )
    if len(cli_layer) > 0:
        merged = _deep_merge(merged, cli_layer, origins, ORIGIN_CLI_OVERRIDE, "")

    semantic = _semantic_issues(merged)
    if len(semantic) > 0:
        raise ConfigError(
            "configuration is invalid:\n  " + "\n  ".join(issue.render() for issue in semantic),
            source.path,
        )

    return EffectiveConfig(
        values=merged,
        source=source,
        origins=origins,
        notes=tuple(notes),
        deviations=_deviations(merged),
        digest=config_digest(merged),
    )


def render_default_config_toml() -> str:
    """The text ``shockharness init --profile strict`` writes: the bundled defaults, verbatim."""
    return resources.files("shockharness").joinpath("defaults.toml").read_text(encoding="utf-8")


def render_profile_config_toml(name: str) -> str:
    """The text ``shockharness init --profile NAME`` writes.

    ``strict`` is the bundled defaults verbatim. Any other profile gets a short file
    that selects the profile and nothing else: spelling out the strict values would
    override the profile layer and silently undo it.
    """
    if name == PROFILE_STRICT:
        return render_default_config_toml()
    if name not in PROFILES:
        raise ConfigError(f"unknown profile; known profiles: {', '.join(PROFILES)}", name)
    return (
        f"# ShockHarness configuration selecting the built-in {name!r} profile.\n"
        "# Keys set here override the profile; keys left out keep the profile's values.\n"
        "# `shockharness config effective` prints the result with a per-key origin.\n"
        "\n"
        "[tool.shockharness]\n"
        f'profile = "{name}"\n'
    )
