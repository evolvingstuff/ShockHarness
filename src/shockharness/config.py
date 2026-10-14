"""Configuration loading: discovery, precedence, validation, merge, digest.

Precedence (highest first): explicit ``--config`` path, ``.shockharness.toml`` in
the root, ``[tool.shockharness]`` in ``pyproject.toml``, bundled defaults. Exactly
one user source applies; it is merged over the bundled defaults. A shadowed
``pyproject.toml`` table is reported in ``notes`` rather than silently ignored.

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
from shockharness.schema import ConfigIssue, validate_shape

TOOL_TABLE = ("tool", "shockharness")
DEDICATED_FILENAME = ".shockharness.toml"
PYPROJECT_FILENAME = "pyproject.toml"

# A boundary names one exception class: a dotted identifier path, never a wildcard.
EXCEPTION_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*")

TIER_CLI = "cli"
TIER_DEDICATED = "dedicated"
TIER_PYPROJECT = "pyproject"
TIER_BUNDLED = "bundled"

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

    dedicated = root / DEDICATED_FILENAME
    pyproject = root / PYPROJECT_FILENAME
    pyproject_table: dict[str, Any] | None = None
    if pyproject.is_file():
        pyproject_table = _extract_tool_table(_read_toml(pyproject), str(pyproject))

    if dedicated.is_file():
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
    for index, boundary in enumerate(values["rules"]["exceptions"]["boundaries"]):
        problem = validate_glob(boundary["path"])
        if problem is not None:
            issues.append(ConfigIssue(f"rules.exceptions.boundaries[{index}].path", problem))
        if EXCEPTION_NAME.fullmatch(boundary["exception"]) is None:
            issues.append(
                ConfigIssue(
                    f"rules.exceptions.boundaries[{index}].exception",
                    "must be a dotted exception class name such as 'OSError' or "
                    "'requests.exceptions.Timeout'; wildcards and bare except cannot be approved",
                )
            )
    magic = values["rules"]["magic_numbers"]
    for index, pattern in enumerate(magic["configuration_files"]):
        problem = validate_glob(pattern)
        if problem is not None:
            issues.append(ConfigIssue(f"rules.magic_numbers.configuration_files[{index}]", problem))
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
    rules = values["rules"]
    for section_name in sorted(rules):
        if rules[section_name]["enabled"] is False:
            found.append(f"rules.{section_name} is disabled")
    allowed = rules["magic_numbers"]["allowed_values"]
    extra = sorted({str(v) for v in allowed if v != 0 and v != 1})
    if len(extra) > 0:
        found.append("rules.magic_numbers.allowed_values permits " + ", ".join(extra))
    if rules["magic_numbers"]["allow_unary_negative_one"] is True:
        found.append("rules.magic_numbers.allow_unary_negative_one is enabled")
    if values["parse_errors"] != "fail":
        found.append(
            f"parse_errors is {values['parse_errors']!r}; syntax failures do not fail the gate"
        )
    exceptions = rules["exceptions"]
    if exceptions["transparent_rethrow"] is True:
        found.append(
            "rules.exceptions.transparent_rethrow is enabled; handlers that only re-raise "
            "pass EXC001 outside any boundary"
        )
    for index, boundary in enumerate(exceptions["boundaries"]):
        found.append(
            f"rules.exceptions.boundaries[{index}] approves catching {boundary['exception']} "
            f"in {boundary['path']} ({boundary['language']}): {boundary['reason']}"
        )
    for index, override in enumerate(values["overrides"]):
        disabled = ", ".join(override["disable"])
        paths = ", ".join(override["paths"])
        found.append(f"overrides[{index}] disables {disabled} for {paths}: {override['reason']}")
    return tuple(found)


def config_digest(values: Mapping[str, Any]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(root: Path, explicit: Path | None) -> EffectiveConfig:
    """Discover, validate, and merge configuration for ``root``.

    Raises :class:`ConfigError` listing every shape and semantic problem found.
    """
    defaults = load_bundled_defaults()
    source, user_table, notes = _discover_source(root, explicit)

    issues = validate_shape(user_table)
    if len(issues) > 0:
        raise ConfigError(
            "configuration is invalid:\n  " + "\n  ".join(issue.render() for issue in issues),
            source.path,
        )

    origins: dict[str, str] = {}
    _record_origins(origins, defaults, TIER_BUNDLED)
    merged = _deep_merge(defaults, user_table, origins, source.tier, "")

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
    """The text ``shockharness init`` writes: the bundled defaults, verbatim."""
    return resources.files("shockharness").joinpath("defaults.toml").read_text(encoding="utf-8")
