"""Configuration loading: discovery, precedence, validation, merge, digest.

Sources (highest first): explicit ``--config`` path, ``.shockharness.toml`` or
``shockharness.toml`` in the root (both present is an error), ``[tool.shockharness]``
in ``pyproject.toml``, bundled defaults. Exactly one user source applies. A
shadowed ``pyproject.toml`` table is reported in ``notes`` rather than silently
ignored.

Layers (lowest first): bundled defaults < the selected built-in profile
(``profile = "..."``; an overlay shipped as package data) < the policy file
(``--policy FILE``, H2 part 2) < the user source < the two command-line overrides
(``--profile``, ``--parse-errors``). Every key records the layer it came from in
``origins``.

The policy file is the organization's: it must live outside the analyzed root, and
the repository's configuration cannot loosen a key it sets (spec 21.1 decision 6).
A repository key that would loosen one is reverted to the policy's value and kept as
a :class:`PolicyAttempt`, which VERIFY003 reports. Tightening a policy key is allowed.
A list is one key: a policy that sets ``overrides = []`` locks the overrides.

Nothing here reads environment variables or executes configuration content.
"""

import copy
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from shockharness.contracts.catalog import catalog_issues
from shockharness.errors import ConfigError
from shockharness.globs import validate_glob
from shockharness.loosening import has_key, loosenings, value_at
from shockharness.roles import CLASSIFIED_ROLES, FILE_ROLES_KEY, ROLE_CONFIG
from shockharness.rules import registry
from shockharness.rules.defaults import loosened_modes
from shockharness.schema import (
    MUST_USE_ENTRY,
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
PARSE_ERRORS_KEY = "parse_errors"
PARSE_ERRORS_FAIL = "fail"
PARSE_ERROR_POLICIES = (PARSE_ERRORS_FAIL, "warn")
PROFILES_PACKAGE = "shockharness.profiles"
# Sections that carry a `severity` cap (see rules/severity.py), with the rules they cover.
SEVERITY_SECTIONS: Mapping[str, str] = {
    "magic_numbers": "MAGIC001",
    "exceptions": "EXC001-EXC003",
    "defaults": "DEF001-DEF006",
}
# The rule families with a `fail_on_unknown` switch (H1): the dotted section that holds
# it, and the rules it covers. A family is named after the last part of its section.
FAIL_ON_UNKNOWN_KEY = "fail_on_unknown"
# Rule sections a repository opts into; off is their default and not a deviation.
OPT_IN_SECTIONS = frozenset({"property_contracts", "dead_code", "duplicates"})


def is_opt_in(section: str) -> bool:
    """``rules.property_contracts`` and the like: off by default, and off is no deviation."""
    parts = section.split(".")
    return parts[len(parts) - 1] in OPT_IN_SECTIONS


def switched_off(values: Mapping[str, Any], section: str | None) -> bool:
    """A family turned off with ``enabled = false``. An opt-in family that is off is in
    its default state, not switched off: no deviation, no disabled rules."""
    if section is None or is_opt_in(section):
        return False
    node: Any = values
    for key in section.split("."):
        node = node[key]
    return node["enabled"] is False


FAIL_ON_UNKNOWN_SECTIONS: Mapping[str, str] = {
    "rules.magic_numbers": "MAGIC001",
    "rules.exceptions": "EXC001-EXC003",
    "rules.defaults": "DEF001-DEF006",
    "complexity": "CPLX001-CPLX006",
    "rules.verification": "VERIFY001, VERIFY002, VERIFY004",
    "rules.async_lifecycle": "ASYNC001-ASYNC003",
    "rules.property_contracts": "PROP001",
}
# The legacy spelling of the config role's globs (H1): merged into file_roles.config.
LEGACY_CONFIGURATION_FILES = "rules.magic_numbers.configuration_files"
FILE_ROLES_CONFIG = f"{FILE_ROLES_KEY}.{ROLE_CONFIG}"

# A boundary names one exception class: a dotted identifier path, never a wildcard.
EXCEPTION_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")

VERIFICATION_REVIEW = "review"
VERIFICATION_ERROR = "error"

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
    ".ts": registry.TYPESCRIPT,
    ".tsx": registry.TYPESCRIPT,
    ".mts": registry.TYPESCRIPT,
    ".cts": registry.TYPESCRIPT,
    ".cs": registry.CSHARP,
}


@dataclass(frozen=True)
class ConfigSource:
    tier: str
    path: str


@dataclass(frozen=True)
class CliOverrides:
    """What the command line contributes to the configuration.

    ``--profile`` replaces the profile layer (the repository's own keys still apply on
    top of it); ``--parse-errors`` decides whether syntax failures fail the run. Both
    are recorded in ``origins`` as ``cli_override`` and in ``notes``. ``--policy``
    names the organization's policy file (H2 part 2), a layer of its own.
    """

    profile: str | None
    parse_errors: str | None
    policy: Path | None


NO_OVERRIDES = CliOverrides(profile=None, parse_errors=None, policy=None)
ORIGIN_POLICY = "policy"


@dataclass(frozen=True)
class PolicyFile:
    """The ``--policy`` file in effect: its path, a digest of its table, and the dotted
    keys it sets (a list is one key)."""

    path: str
    digest: str
    keys: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {"path": self.path, "digest": self.digest, "keys": list(self.keys)}


@dataclass(frozen=True)
class PolicyAttempt:
    """A repository key that would have loosened a key the policy sets. The policy's
    value applies; ``reasons`` say what would have got looser."""

    key: str
    policy_value: Any
    attempted_value: Any
    reasons: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "policy_value": json.loads(json.dumps(self.policy_value)),
            "attempted_value": json.loads(json.dumps(self.attempted_value)),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EffectiveConfig:
    values: Mapping[str, Any]
    source: ConfigSource
    origins: Mapping[str, str]
    notes: tuple[str, ...]
    deviations: tuple[str, ...]
    digest: str
    policy: PolicyFile | None
    policy_attempts: tuple[PolicyAttempt, ...]
    # The project's console scripts, "module:function", from [project.scripts] of the
    # root pyproject.toml: entry points for DEF005 (spec 21.1 decision 37).
    entry_points: tuple[str, ...]
    # The analyzed root the configuration was loaded for: property contracts read a
    # resolved callee's declared contract from its project file when that file is not
    # among the analyzed ones (spec §5.3, one hop). Not part of the digest.
    root: Path

    def section(self, dotted: str) -> Mapping[str, Any]:
        node: Any = self.values
        for key in dotted.split("."):
            node = node[key]
        assert isinstance(node, Mapping), f"{dotted} is a validated table"
        return node

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": {"tier": self.source.tier, "path": self.source.path},
            "digest": self.digest,
            "notes": list(self.notes),
            "deviations": list(self.deviations),
            "origins": dict(sorted(self.origins.items())),
            "values": json.loads(json.dumps(self.values)),
            "policy": None if self.policy is None else self.policy.to_json_dict(),
            "policy_attempts": [attempt.to_json_dict() for attempt in self.policy_attempts],
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
    issues: list[ConfigIssue] = list(catalog_issues(values))
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
        issues.extend(_override_scope_issues(override, key))
        if len(override["disable"]) == 0:
            issues.append(ConfigIssue(f"{key}.disable", "must list at least one rule ID"))
        for r_index, rule_id in enumerate(override["disable"]):
            if not registry.is_known_rule(rule_id):
                known = ", ".join(registry.rule_ids())
                issues.append(
                    ConfigIssue(
                        f"{key}.disable[{r_index}]", f"unknown rule ID {rule_id!r} (known: {known})"
                    )
                )
    issues.extend(_guardrail_entry_issues(values["rules"]))
    for index, allowed in enumerate(values["rules"]["module_state"]["allowed"]):
        problem = validate_glob(allowed["path"])
        if problem is not None:
            issues.append(ConfigIssue(f"rules.module_state.allowed[{index}].path", problem))
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
    for role in CLASSIFIED_ROLES:
        for index, pattern in enumerate(values[FILE_ROLES_KEY][role]):
            problem = validate_glob(pattern)
            if problem is not None:
                issues.append(ConfigIssue(f"{FILE_ROLES_KEY}.{role}[{index}]", problem))
    return issues


def _override_scope_issues(override: Mapping[str, Any], key: str) -> list[ConfigIssue]:
    """Exactly one of ``paths`` (globs) / ``roles`` (file roles), non-empty, valid."""
    has_paths = "paths" in override
    has_roles = "roles" in override
    if has_paths == has_roles:
        return [
            ConfigIssue(
                key,
                "needs exactly one of 'paths' (glob patterns) or 'roles' (file roles such as "
                "'test'; see file_roles)",
            )
        ]
    if has_roles:
        if len(override["roles"]) == 0:
            return [ConfigIssue(f"{key}.roles", "must list at least one file role")]
        return []
    if len(override["paths"]) == 0:
        return [ConfigIssue(f"{key}.paths", "must list at least one path")]
    issues: list[ConfigIssue] = []
    for p_index, pattern in enumerate(override["paths"]):
        problem = validate_glob(pattern)
        if problem is not None:
            issues.append(ConfigIssue(f"{key}.paths[{p_index}]", problem))
    return issues


def override_scope(override: Mapping[str, Any]) -> str:
    """How a validated override names its files, for deviation lines and messages."""
    if "roles" in override:
        return "file role(s) " + ", ".join(override["roles"])
    return ", ".join(override["paths"])


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


def _section(values: Mapping[str, Any], dotted: str) -> Mapping[str, Any]:
    node: Any = values
    for key in dotted.split("."):
        node = node[key]
    assert isinstance(node, Mapping), f"{dotted} is a validated table"
    return node


def _unknown_deviations(values: Mapping[str, Any], strict_values: Mapping[str, Any]) -> list[str]:
    """A family whose ``fail_on_unknown`` is below the strict profile's value (true -> false),
    whether a profile or the repository set it (``recommended`` does for ``rules.defaults``)."""
    found: list[str] = []
    for section, rules in FAIL_ON_UNKNOWN_SECTIONS.items():
        configured = _section(values, section)[FAIL_ON_UNKNOWN_KEY]
        expected = _section(strict_values, section)[FAIL_ON_UNKNOWN_KEY]
        if expected is True and configured is False:
            found.append(
                f"{section}.{FAIL_ON_UNKNOWN_KEY} is false (profile {PROFILE_STRICT!r}: true); "
                f"{rules} findings whose status is unknown are reported and never fail the gate"
            )
    return found


# H3 guardrail sections: which rules each one carries, which of its lists are catalogs
# (removing an entry loosens) and which are permissions (adding one loosens).
# RESULT001's section: its catalog entries may carry an argument count.
RESULTS_SECTION = "results"
GUARDRAIL_RULES = {
    "stubs": "STUB001, STUB002",
    "assertions": "ASSERT001",
    "boolean_arguments": "BOOL001",
    "module_state": "STATE001",
    "import_effects": "IMPORT001",
    "async_lifecycle": "ASYNC001-ASYNC003",
    "processes": "PROCESS001",
    "results": "RESULT001",
    "types": "TYPE001",
    "sleep": "SLEEP001",
    "retry": "RETRY001",
    "batches": "BATCH001",
    "role_integrity": "ROLE001",
    "input": "INPUT001",
    "consistency": "PROV001, GUARD001",
    "sentinels": "MAGIC003",
    "dom": "DOM001",
    "magic_strings": "MAGIC002",
}
GUARDRAIL_CATALOGS = (
    ("stubs", "roles"),
    ("stubs", "test_path_segments"),
    ("stubs", "mock_modules"),
    ("assertions", "roles"),
    ("assertions", "external_reads"),
    ("boolean_arguments", "roles"),
    ("module_state", "roles"),
    ("import_effects", "roles"),
    ("import_effects", "python_operations"),
    ("import_effects", "javascript_operations"),
    ("import_effects", "csharp_operations"),
    ("async_lifecycle", "roles"),
    ("async_lifecycle", "python_coroutine_apis"),
    ("async_lifecycle", "javascript_promise_apis"),
    ("async_lifecycle", "csharp_task_apis"),
    ("processes", "roles"),
    ("processes", "python_process_apis"),
    ("processes", "javascript_process_apis"),
    ("processes", "csharp_process_apis"),
    ("results", "roles"),
    ("results", "python_must_use"),
    ("results", "javascript_must_use"),
    ("results", "csharp_must_use"),
    ("types", "roles"),
    ("sleep", "roles"),
    ("sleep", "python_sleep_apis"),
    ("retry", "roles"),
    ("retry", "retry_decorators"),
    ("batches", "roles"),
    ("input", "roles"),
    ("input", "python_sources"),
    ("input", "javascript_sources"),
    ("input", "python_sinks"),
    ("input", "javascript_sinks"),
    ("input", "python_config_reads"),
    ("input", "javascript_config_reads"),
    ("consistency", "roles"),
    ("consistency", "python_fabricators"),
    ("consistency", "javascript_fabricators"),
    ("consistency", "issuer_prefixes"),
    ("sentinels", "roles"),
    ("sentinels", "values"),
    ("dom", "roles"),
    ("dom", "classes"),
    ("magic_strings", "roles"),
    ("magic_strings", "kinds"),
)
TYPE_SWITCHES = ("report_any", "report_cast", "report_non_null", "report_type_ignore")
GUARDRAIL_PERMISSIONS = (
    ("boolean_arguments", "allowed_callees"),
    ("async_lifecycle", "supervisors"),
    ("role_integrity", "support_files"),
    ("import_effects", "script_files"),
    ("input", "python_validators"),
    ("input", "javascript_validators"),
    ("sentinels", "python_index_callees"),
    ("sentinels", "javascript_index_callees"),
    ("sentinels", "csharp_index_callees"),
    ("sentinels", "standard_targets"),
    ("magic_strings", "message_callees"),
    ("magic_strings", "allowed"),
)
REVIEW = "review"


def _guardrail_deviations(rules: Mapping[str, Any], strict: Mapping[str, Any]) -> list[str]:
    """H3: a severity lowered to review, a catalog entry removed, a permission added, and
    every declared module-state binding."""
    found: list[str] = []
    for section, rule_ids in GUARDRAIL_RULES.items():
        if "severity" not in rules[section]:
            continue  # rules.magic_strings sets its severity with `mode` (since 0.1.0)
        if rules[section]["severity"] == REVIEW and strict[section]["severity"] != REVIEW:
            found.append(
                f"rules.{section}.severity is 'review'; {rule_ids} findings are reported as review"
            )
    found.extend(_guardrail_list_deviations(rules, strict))
    found.extend(
        _input_deviations(
            rules["input"],
            strict["input"],
            rules["consistency"],
            strict["consistency"],
            rules["magic_strings"],
            strict["magic_strings"],
        )
    )
    for key in TYPE_SWITCHES:
        if rules["types"][key] is False and strict["types"][key] is True:
            found.append(f"rules.types.{key} is false; TYPE001 does not report that escape hatch")
    for index, allowed in enumerate(rules["module_state"]["allowed"]):
        found.append(
            f"rules.module_state.allowed[{index}] permits module state {allowed['name']!r} in "
            f"{allowed['path']}: {allowed['reason']}"
        )
    return found


SINK_ENTRY = re.compile(r"[^:\s]+:[0-9]+")


IMPORT_BOUNDARY_GLOBS = ("importers", "imported")


def _import_boundary_issues(section: Mapping[str, Any]) -> list[ConfigIssue]:
    """IMPORT002: each entry names at least one importer and one imported glob, all valid."""
    issues: list[ConfigIssue] = []
    for index, entry in enumerate(section["forbidden"]):
        for field in IMPORT_BOUNDARY_GLOBS:
            key = f"rules.import_boundaries.forbidden[{index}].{field}"
            if len(entry[field]) == 0:
                issues.append(ConfigIssue(key, "must list at least one path glob"))
            for g_index, pattern in enumerate(entry[field]):
                problem = validate_glob(pattern)
                if problem is not None:
                    issues.append(ConfigIssue(f"{key}[{g_index}]", problem))
    return issues


def _guardrail_entry_issues(rules: Mapping[str, Any]) -> list[ConfigIssue]:
    """ROLE001's support globs, IMPORT001's script globs, H6's sink entries and IMPORT002's
    boundaries."""
    issues: list[ConfigIssue] = []
    for section, key in (("role_integrity", "support_files"), ("import_effects", "script_files")):
        for index, pattern in enumerate(rules[section][key]):
            problem = validate_glob(pattern)
            if problem is not None:
                issues.append(ConfigIssue(f"rules.{section}.{key}[{index}]", problem))
    issues.extend(_sink_issues(rules["input"]))
    issues.extend(_import_boundary_issues(rules["import_boundaries"]))
    return issues


def _sink_issues(section: Mapping[str, Any]) -> list[ConfigIssue]:
    """H6: every sink entry is "callee:N" (an argument position counted from 0)."""
    issues: list[ConfigIssue] = []
    for key in ("python_sinks", "javascript_sinks"):
        for index, entry in enumerate(section[key]):
            if SINK_ENTRY.fullmatch(str(entry)) is None:
                issues.append(
                    ConfigIssue(
                        f"rules.input.{key}[{index}]",
                        f"must be 'callee:N' (an argument position, from 0), got {entry!r}",
                    )
                )
    return issues


def _threshold_deviations(rules: Mapping[str, Any], strict: Mapping[str, Any]) -> list[str]:
    """MAGIC002: a higher bar (length, occurrences, files) reports fewer repeated strings."""
    return [
        f"rules.magic_strings.{key} is {rules[key]} (strict: {strict[key]}); MAGIC002 "
        "reports fewer repeated strings"
        for key in ("min_length", "min_occurrences", "min_files", "min_compared_files")
        if rules[key] > strict[key]
    ]


def _input_deviations(
    rules: Mapping[str, Any],
    strict: Mapping[str, Any],
    consistency: Mapping[str, Any],
    strict_consistency: Mapping[str, Any],
    magic_strings: Mapping[str, Any],
    strict_magic_strings: Mapping[str, Any],
) -> list[str]:
    """H6: INPUT002's own severity lowered to review, a shallower INPUT001 search, and
    GUARD001 thresholds raised."""
    found: list[str] = []
    if rules["input002_severity"] == REVIEW and strict["input002_severity"] != REVIEW:
        found.append("rules.input.input002_severity is 'review'; INPUT002 findings are review")
    found.extend(_threshold_deviations(magic_strings, strict_magic_strings))
    for key in ("guard_min_sites", "guard_min_percent"):
        if consistency[key] > strict_consistency[key]:
            found.append(
                f"rules.consistency.{key} is {consistency[key]} (strict: "
                f"{strict_consistency[key]}); GUARD001 asks for more agreement before it reports"
            )
    if rules["max_depth"] < strict["max_depth"]:
        found.append(
            f"rules.input.max_depth is {rules['max_depth']} (strict: {strict['max_depth']}); "
            "INPUT001 follows values across fewer function boundaries"
        )
    return found


def _listed(section: str, value: Any, entries: Sequence[Any]) -> bool:
    """``value`` is in ``entries``; a RESULT001 entry with an argument count
    (``.join/1``) is also covered by the same callee without one (``.join``)."""
    if value in entries:
        return True
    if section != RESULTS_SECTION:
        return False
    match = MUST_USE_ENTRY.fullmatch(str(value))
    return match is not None and match.group("name") in entries


def _guardrail_list_deviations(rules: Mapping[str, Any], strict: Mapping[str, Any]) -> list[str]:
    """A catalog entry removed, a permission added."""
    found: list[str] = []
    for section, key in GUARDRAIL_CATALOGS:
        removed = [v for v in strict[section][key] if not _listed(section, v, rules[section][key])]
        if len(removed) > 0:
            found.append(
                f"rules.{section}.{key} no longer lists "
                + ", ".join(repr(v) for v in removed)
                + f"; {GUARDRAIL_RULES[section]} no longer cover them"
            )
    for section, key in GUARDRAIL_PERMISSIONS:
        added = [v for v in rules[section][key] if v not in strict[section][key]]
        if len(added) > 0:
            found.append(
                f"rules.{section}.{key} also permits "
                + ", ".join(repr(v) for v in added)
                + f"; {GUARDRAIL_RULES[section]} no longer report what they cover"
            )
    return found


def _verification_deviations(verification: Mapping[str, Any]) -> list[str]:
    """VERIFY findings lowered to review, and every allowed skip reason (H2). Raising the
    severity to error tightens the policy and is not a deviation."""
    found: list[str] = []
    if verification["severity"] == VERIFICATION_REVIEW:
        found.append(
            "rules.verification.severity is 'review'; VERIFY001, VERIFY002 and VERIFY004 "
            "findings are reported as review and never fail the gate"
        )
    if verification["rule_switching_severity"] != VERIFICATION_ERROR:
        found.append(
            f"rules.verification.rule_switching_severity is "
            f"{verification['rule_switching_severity']!r}; a configuration change that "
            "switches a rule off does not fail the gate"
        )
    for index, reason in enumerate(verification["allowed_skip_reasons"]):
        found.append(
            f"rules.verification.allowed_skip_reasons[{index}] accepts an added skip marker "
            f"whose reason is {reason!r} (VERIFY001 does not report it)"
        )
    return found


def _deviations(values: Mapping[str, Any], strict_values: Mapping[str, Any]) -> tuple[str, ...]:
    """Explicit departures from the strict profile, always surfaced in reports.

    ``strict_values`` are the bundled defaults (the strict profile): the reference for
    keys whose deviation is a value below strict's (``fail_on_unknown``).
    """
    found: list[str] = []
    profile = values[PROFILE_KEY]
    if profile != PROFILE_STRICT:
        found.append(
            f"profile is {profile!r}, below {PROFILE_STRICT!r}; the lines that follow are what "
            "it changes (see docs/configuration.md, Profiles)"
        )
    rules = values["rules"]
    for section_name in sorted(rules):
        if switched_off(values, f"rules.{section_name}"):
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
    if values[PARSE_ERRORS_KEY] != PARSE_ERRORS_FAIL:
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
    found.extend(_verification_deviations(rules["verification"]))
    found.extend(_guardrail_deviations(rules, strict_values["rules"]))
    found.extend(_unknown_deviations(values, strict_values))
    for index, override in enumerate(values["overrides"]):
        disabled = ", ".join(override["disable"])
        scope = override_scope(override)
        found.append(f"overrides[{index}] disables {disabled} for {scope}: {override['reason']}")
    return tuple(found)


USER_TIERS = frozenset({TIER_CLI, TIER_DEDICATED, TIER_PYPROJECT})


def _merge_legacy_configuration_files(
    values: dict[str, Any], origins: dict[str, str], notes: list[str]
) -> None:
    """Fold ``rules.magic_numbers.configuration_files`` into ``file_roles.config`` (H1).

    Only a configuration that sets the legacy key changes anything (its bundled default
    equals the default config role). Set alone, it replaces the config role's globs, as
    it replaced the exempt list in 0.3.0; set together with ``file_roles.config``, the
    two lists are merged (``file_roles.config`` first, duplicates dropped).
    """
    legacy_origin = origins[LEGACY_CONFIGURATION_FILES]
    if legacy_origin not in USER_TIERS:
        return
    legacy = list(values["rules"]["magic_numbers"]["configuration_files"])
    roles = values[FILE_ROLES_KEY]
    if origins[FILE_ROLES_CONFIG] in USER_TIERS:
        merged = list(roles[ROLE_CONFIG])
        merged.extend(pattern for pattern in legacy if pattern not in merged)
        notes.append(
            f"{LEGACY_CONFIGURATION_FILES} (legacy spelling) is merged into "
            f"{FILE_ROLES_CONFIG}; the config role has {len(merged)} glob(s)"
        )
    else:
        merged = legacy
        notes.append(
            f"{LEGACY_CONFIGURATION_FILES} (legacy spelling) sets the config role's globs "
            f"({FILE_ROLES_CONFIG}); prefer {FILE_ROLES_CONFIG}"
        )
    roles[ROLE_CONFIG] = merged
    origins[FILE_ROLES_CONFIG] = legacy_origin


CACHE_KEY = "cache"


def config_digest(values: Mapping[str, Any], entry_points: Sequence[str]) -> str:
    """SHA-256 of the canonical JSON of every key that can change a result: the
    ``cache`` table (where results are stored, and whether) is left out, so toggling
    the cache neither changes the digest a baseline records nor the cache key. The
    project's entry points change DEF005 findings, so they are part of it."""
    policy: dict[str, Any] = {key: value for key, value in values.items() if key != CACHE_KEY}
    policy[ENTRY_POINTS_DIGEST_KEY] = list(entry_points)
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _leaves(table: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """Dotted leaf keys of a configuration table; a list is a leaf."""
    found: dict[str, Any] = {}
    for key, value in table.items():
        dotted = key if prefix == "" else f"{prefix}.{key}"
        if isinstance(value, Mapping):
            found.update(_leaves(value, dotted))
        else:
            found[dotted] = value
    return found


def _nested(dotted: str, value: Any) -> dict[str, Any]:
    """``{"a": {"b": value}}`` for ``"a.b"``."""
    parts = dotted.split(".")
    node: dict[str, Any] = {parts[len(parts) - 1]: copy.deepcopy(value)}
    for part in reversed(parts[: len(parts) - 1]):
        node = {part: node}
    return node


def _without(table: Mapping[str, Any], dotted: str) -> dict[str, Any]:
    """A deep copy of ``table`` without the leaf ``dotted`` (empty tables pruned)."""
    copied = copy.deepcopy(dict(table))
    parts = dotted.split(".")
    trail: list[dict[str, Any]] = [copied]
    for part in parts[: len(parts) - 1]:
        trail.append(trail[len(trail) - 1][part])
    del trail[len(trail) - 1][parts[len(parts) - 1]]
    for index in reversed(range(1, len(trail))):
        if len(trail[index]) == 0:
            del trail[index - 1][parts[index - 1]]
    return copied


def _load_policy(root: Path, path: Path) -> tuple[PolicyFile, dict[str, Any]]:
    """Read and validate the ``--policy`` file. It must live outside the analyzed root:
    a policy that the change under review can edit protects nothing."""
    if not path.is_file():
        raise ConfigError("policy file does not exist", str(path))
    if path.resolve().is_relative_to(root.resolve()):
        raise ConfigError(
            "the policy file must live outside the analyzed root, where the change under "
            "review cannot edit it (check it out from a separate, protected repository)",
            str(path),
        )
    table = _extract_tool_table(_read_toml(path), str(path))
    if table is None:
        raise ConfigError("policy file has no [tool.shockharness] table", str(path))
    issues = validate_shape(table)
    if len(issues) > 0:
        raise ConfigError(
            "policy file is invalid:\n  " + "\n  ".join(issue.render() for issue in issues),
            str(path),
        )
    canonical = json.dumps(table, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    keys = tuple(sorted(_leaves(table, "")))
    return PolicyFile(path=str(path), digest=digest, keys=keys), table


def _protect(
    policy_values: dict[str, Any],
    strict_values: Mapping[str, Any],
    policy_keys: frozenset[str],
    user_table: Mapping[str, Any],
) -> tuple[dict[str, Any], list[PolicyAttempt]]:
    """The user table minus every key that would loosen a key the policy sets."""
    kept = copy.deepcopy(dict(user_table))
    attempts: list[PolicyAttempt] = []
    reference = _deviations(policy_values, strict_values)
    for dotted, value in sorted(_leaves(user_table, "").items()):
        if dotted not in policy_keys:
            continue
        if not has_key(policy_values, dotted):
            raise ConfigError(
                f"the policy sets {dotted}, but its merged values lack it", ORIGIN_POLICY
            )
        policy_value = value_at(policy_values, dotted)
        if value == policy_value:
            continue
        trial = _deep_merge(policy_values, _nested(dotted, value), {}, ORIGIN_POLICY, "")
        found = loosenings(policy_values, reference, trial, _deviations(trial, strict_values))
        if len(found) == 0:
            continue  # a tightening (or a neutral change) of a policy key is allowed
        attempts.append(
            PolicyAttempt(
                key=dotted,
                policy_value=policy_value,
                attempted_value=value,
                reasons=tuple(item.message for item in found),
            )
        )
        kept = _without(kept, dotted)
    return kept, attempts


def _profile_looser(candidate: str, reference: str) -> bool:
    """``PROFILES`` is ordered strictest first."""
    return PROFILES.index(candidate) > PROFILES.index(reference)


def _select_profile(
    bundled: str,
    policy_table: Mapping[str, Any],
    user_table: dict[str, Any],
    attempts: list[PolicyAttempt],
) -> tuple[str, dict[str, Any]]:
    """The profile before command-line overrides: the user source's, else the policy's,
    else the bundled one. A user profile looser than the policy's is an attempt and is
    dropped from the user table."""
    profile_name = bundled
    if PROFILE_KEY in policy_table:
        profile_name = str(policy_table[PROFILE_KEY])
    if PROFILE_KEY not in user_table:
        return profile_name, user_table
    wanted = str(user_table[PROFILE_KEY])
    if PROFILE_KEY in policy_table and _profile_looser(wanted, profile_name):
        attempts.append(
            PolicyAttempt(
                key=PROFILE_KEY,
                policy_value=profile_name,
                attempted_value=wanted,
                reasons=(f"profile {wanted!r} is looser than the policy's {profile_name!r}",),
            )
        )
        return profile_name, _without(user_table, PROFILE_KEY)
    return wanted, user_table


def _note_cli_profile(
    selected: str, profile_name: str, policy_table: Mapping[str, Any], notes: list[str]
) -> None:
    if PROFILE_KEY in policy_table and _profile_looser(selected, profile_name):
        notes.append(
            f"--profile {selected!r} on the command line is looser than the policy "
            f"file's profile {profile_name!r}; command-line overrides are the operator's and "
            "are not bound by the policy (VERIFY003 reports a workflow that adds the flag)"
        )
    if selected != profile_name:
        notes.append(
            f"profile {selected!r} selected by --profile on the command line "
            f"replaces profile {profile_name!r}; the configuration file's other keys "
            "still apply on top of it"
        )


def _apply_policy(
    merged: dict[str, Any],
    strict_values: Mapping[str, Any],
    policy: PolicyFile,
    policy_table: Mapping[str, Any],
    user_table: dict[str, Any],
    origins: dict[str, str],
    attempts: list[PolicyAttempt],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge the policy layer; return it and the user table minus every key that would
    loosen a policy key (each recorded in ``attempts``)."""
    policy_layer = {k: v for k, v in policy_table.items() if k != PROFILE_KEY}
    merged = _deep_merge(merged, policy_layer, origins, ORIGIN_POLICY, "")
    if PROFILE_KEY in policy_table:
        origins[PROFILE_KEY] = ORIGIN_POLICY
    user_table, protected = _protect(merged, strict_values, frozenset(policy.keys), user_table)
    attempts.extend(protected)
    return merged, user_table


def _apply_cli_overrides(
    merged: dict[str, Any], overrides: CliOverrides, origins: dict[str, str], notes: list[str]
) -> dict[str, Any]:
    cli_layer: dict[str, Any] = {}
    if overrides.profile is not None:
        cli_layer[PROFILE_KEY] = overrides.profile
    if overrides.parse_errors is not None:
        cli_layer[PARSE_ERRORS_KEY] = overrides.parse_errors
        notes.append(
            f"parse_errors = {overrides.parse_errors!r} set by --parse-errors on the command "
            f"line (configured value: {merged[PARSE_ERRORS_KEY]!r})"
        )
    if len(cli_layer) == 0:
        return merged
    return _deep_merge(merged, cli_layer, origins, ORIGIN_CLI_OVERRIDE, "")


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
    if overrides.parse_errors is not None and overrides.parse_errors not in PARSE_ERROR_POLICIES:
        raise ConfigError(
            f"--parse-errors must be one of {', '.join(PARSE_ERROR_POLICIES)}",
            repr(overrides.parse_errors),
        )


def load_config_with_overrides(
    root: Path, explicit: Path | None, overrides: CliOverrides
) -> EffectiveConfig:
    """Discover, validate, and merge configuration for ``root``.

    Layers, lowest first: bundled defaults, the profile overlay (selected by
    ``--profile``, else the user source's ``profile`` key, else the policy file's, else
    ``strict``), the ``--policy`` file, the user source minus every key that would
    loosen a policy key, the CLI overrides. Raises :class:`ConfigError` listing every
    shape and semantic problem found.
    """
    _validate_overrides(overrides)
    defaults = load_bundled_defaults()
    source, user_table, notes = _discover_source(root, explicit)
    policy: PolicyFile | None = None
    policy_table: dict[str, Any] = {}
    attempts: list[PolicyAttempt] = []
    if overrides.policy is not None:
        policy, policy_table = _load_policy(root, overrides.policy)
        notes.append(
            f"policy file {policy.path} sets {len(policy.keys)} key(s); the repository's "
            "configuration cannot loosen them"
        )

    issues = validate_shape(user_table)
    if len(issues) > 0:
        raise ConfigError(
            "configuration is invalid:\n  " + "\n  ".join(issue.render() for issue in issues),
            source.path,
        )

    profile_name, user_table = _select_profile(
        str(defaults[PROFILE_KEY]), policy_table, user_table, attempts
    )
    if overrides.profile is not None:
        _note_cli_profile(overrides.profile, profile_name, policy_table, notes)
        profile_name = overrides.profile

    origins: dict[str, str] = {}
    _record_origins(origins, defaults, TIER_BUNDLED)
    strict_values = copy.deepcopy(defaults)
    overlay = load_profile_overlay(profile_name)
    merged = _deep_merge(defaults, overlay, origins, ORIGIN_PROFILE_PREFIX + profile_name, "")
    if policy is not None:
        merged, user_table = _apply_policy(
            merged, strict_values, policy, policy_table, user_table, origins, attempts
        )
        for attempt in attempts:
            notes.append(
                f"{attempt.key} = {attempt.attempted_value!r} in {source.path} would loosen the "
                f"policy file's {attempt.policy_value!r}; the policy's value applies"
            )
    merged = _deep_merge(merged, user_table, origins, source.tier, "")

    merged = _apply_cli_overrides(merged, overrides, origins, notes)

    semantic = _semantic_issues(merged)
    if len(semantic) > 0:
        raise ConfigError(
            "configuration is invalid:\n  " + "\n  ".join(issue.render() for issue in semantic),
            source.path,
        )
    _merge_legacy_configuration_files(merged, origins, notes)

    return _effective(merged, source, origins, notes, strict_values, policy, attempts, root)


def _effective(
    merged: dict[str, Any],
    source: ConfigSource,
    origins: dict[str, str],
    notes: list[str],
    strict_values: Mapping[str, Any],
    policy: PolicyFile | None,
    attempts: list[PolicyAttempt],
    root: Path,
) -> EffectiveConfig:
    """The loaded configuration, with the project's entry points (decision 37)."""
    entry_points = project_entry_points(root)
    return EffectiveConfig(
        values=merged,
        source=source,
        origins=origins,
        notes=tuple(notes),
        deviations=_deviations(merged, strict_values),
        digest=config_digest(merged, entry_points),
        policy=policy,
        policy_attempts=tuple(attempts),
        entry_points=entry_points,
        root=root,
    )


PROJECT_TABLE = "project"
SCRIPTS_TABLE = "scripts"
ENTRY_POINTS_DIGEST_KEY = "<entry_points>"


def project_entry_points(root: Path) -> tuple[str, ...]:
    """``[project.scripts]`` of the root pyproject.toml as sorted "module:function"
    values (an extra after the function, "pkg.cli:main [extra]", is dropped); empty
    when there is no pyproject.toml or no such table."""
    pyproject = root / PYPROJECT_FILENAME
    if not pyproject.is_file():
        return ()
    document = _read_toml(pyproject)
    if PROJECT_TABLE not in document or not isinstance(document[PROJECT_TABLE], dict):
        return ()
    project = document[PROJECT_TABLE]
    if SCRIPTS_TABLE not in project or not isinstance(project[SCRIPTS_TABLE], dict):
        return ()
    scripts = project[SCRIPTS_TABLE]
    return tuple(
        sorted(str(target).split()[0] for target in scripts.values() if str(target).strip())
    )


def render_default_config_toml() -> str:
    """The bundled defaults, verbatim (``init --profile strict`` adds the test exemption)."""
    return resources.files("shockharness").joinpath("defaults.toml").read_text(encoding="utf-8")


# The override `init` and `skills install` write (spec 21.1 decision 35): the exemption
# ShockHarness's own configuration has and the skills recommend.
TEST_EXEMPTION_RULES = ("MAGIC001", "DEF001")
TEST_EXEMPTION_REASON = (
    "Test code states literal expected values, and test helpers and fixtures take keyword "
    "defaults (written by shockharness init; remove it to hold tests to every rule)"
)
DEFAULTS_OVERRIDES_LINE = "overrides = []\n"


def _test_exemption_rules() -> str:
    return ", ".join(f'"{rule}"' for rule in TEST_EXEMPTION_RULES)


def _test_exemption_inline() -> str:
    """The test exemption as an inline table, for the ``overrides`` array."""
    return (
        f'{{ roles = ["test"], disable = [{_test_exemption_rules()}], '
        f'reason = "{TEST_EXEMPTION_REASON}" }}'
    )


def test_exemption_table() -> str:
    """The test exemption as an ``[[tool.shockharness.overrides]]`` table."""
    return (
        "[[tool.shockharness.overrides]]\n"
        'roles = ["test"]\n'
        f"disable = [{_test_exemption_rules()}]\n"
        f'reason = "{TEST_EXEMPTION_REASON}"\n'
    )


def render_profile_config_toml(name: str) -> str:
    """The text ``shockharness init --profile NAME`` writes.

    ``strict`` is the bundled defaults verbatim, except that ``overrides`` holds the test
    exemption (decision 35). Any other profile gets a short file that selects the
    profile and holds the test exemption, nothing else: spelling out the strict values
    would override the profile layer and silently undo it.
    """
    if name == PROFILE_STRICT:
        defaults = render_default_config_toml()
        if DEFAULTS_OVERRIDES_LINE not in defaults:
            raise ConfigError("the bundled defaults no longer set overrides = []", name)
        return defaults.replace(
            DEFAULTS_OVERRIDES_LINE, f"overrides = [\n  {_test_exemption_inline()},\n]\n", 1
        )
    if name not in PROFILES:
        raise ConfigError(f"unknown profile; known profiles: {', '.join(PROFILES)}", name)
    return (
        f"# ShockHarness configuration selecting the built-in {name!r} profile.\n"
        "# Keys set here override the profile; keys left out keep the profile's values.\n"
        "# `shockharness config effective` prints the result with a per-key origin.\n"
        "\n"
        "[tool.shockharness]\n"
        f'profile = "{name}"\n'
        "\n" + test_exemption_table()
    )
