"""Configuration schema: shape validation with exact key paths in every message.

The schema is data (a tree of field descriptors) rather than code so the loader
can reject unknown keys, wrong types, and bad enum values with one consistent
error format. Semantic checks that need other modules (rule IDs, glob validity,
supported languages) live in :mod:`shockharness.config`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigIssue:
    key_path: str
    message: str

    def render(self) -> str:
        return f"{self.key_path}: {self.message}"


class Field:
    """Base descriptor. Subclasses append :class:`ConfigIssue` for every problem."""

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        raise NotImplementedError(type(self).__name__)

    def describe(self) -> str:
        raise NotImplementedError(type(self).__name__)


class StrField(Field):
    def __init__(self, allow_empty: bool) -> None:
        self.allow_empty = allow_empty

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, str):
            issues.append(ConfigIssue(key_path, f"expected a string, got {type_name(value)}"))
            return
        if not self.allow_empty and value.strip() == "":
            issues.append(ConfigIssue(key_path, "must not be empty"))

    def describe(self) -> str:
        return "string"


class BoolField(Field):
    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, bool):
            issues.append(ConfigIssue(key_path, f"expected true or false, got {type_name(value)}"))

    def describe(self) -> str:
        return "boolean"


class IntField(Field):
    def __init__(self, minimum: int) -> None:
        self.minimum = minimum

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(ConfigIssue(key_path, f"expected an integer, got {type_name(value)}"))
            return
        if value < self.minimum:
            issues.append(ConfigIssue(key_path, f"must be at least {self.minimum}, got {value}"))

    def describe(self) -> str:
        return f"integer >= {self.minimum}"


class NumberField(Field):
    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            issues.append(ConfigIssue(key_path, f"expected a number, got {type_name(value)}"))

    def describe(self) -> str:
        return "number"


class EnumField(Field):
    def __init__(self, choices: Sequence[str]) -> None:
        self.choices = tuple(choices)

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, str) or value not in self.choices:
            rendered = ", ".join(repr(c) for c in self.choices)
            issues.append(ConfigIssue(key_path, f"must be one of {rendered}, got {value!r}"))

    def describe(self) -> str:
        return "one of " + ", ".join(self.choices)


class ListField(Field):
    def __init__(self, item: Field) -> None:
        self.item = item

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, list):
            issues.append(ConfigIssue(key_path, f"expected a list, got {type_name(value)}"))
            return
        for index, element in enumerate(value):
            self.item.check(element, f"{key_path}[{index}]", issues)

    def describe(self) -> str:
        return f"list of {self.item.describe()}"


class TableField(Field):
    def __init__(self, fields: Mapping[str, Field], required: Sequence[str]) -> None:
        self.fields = dict(fields)
        self.required = tuple(required)

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, dict):
            issues.append(ConfigIssue(key_path, f"expected a table, got {type_name(value)}"))
            return
        for key in sorted(value):
            child_path = key if key_path == "" else f"{key_path}.{key}"
            if key not in self.fields:
                known = ", ".join(sorted(self.fields))
                issues.append(ConfigIssue(child_path, f"unknown key (known keys: {known})"))
                continue
            self.fields[key].check(value[key], child_path, issues)
        for key in self.required:
            if key not in value:
                child_path = key if key_path == "" else f"{key_path}.{key}"
                issues.append(ConfigIssue(child_path, "required key is missing"))

    def describe(self) -> str:
        return "table"


def type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


SEVERITY_MODES = ("forbid", "review", "allow")
# MAGIC001 on the definition of a module-level named constant (MAX_PAGES = 8): "report"
# (strict: a named constant is not automatically justified) or "allow" (the name is the
# remedy the rule asks for; recommended and minimal).
NAMED_CONSTANT_MODES = ("report", "allow")
LANGUAGES = ("python", "javascript")
# Built-in profiles, strictest first. "strict" is the bundled defaults; the others are
# overlays shipped as package data under shockharness/profiles/.
PROFILE_STRICT = "strict"
PROFILE_RECOMMENDED = "recommended"
PROFILE_MINIMAL = "minimal"
PROFILES = (PROFILE_STRICT, PROFILE_RECOMMENDED, PROFILE_MINIMAL)
# A rule section's `severity`: "error" keeps each rule's documented severity; "review" caps
# every error finding of the section at review (reported, never gating).
SECTION_SEVERITIES = ("error", "review")
# CPLX005 fan-out findings: a warning (strict) or a review finding (recommended); both are
# advisory and never fail the gate, so neither is a deviation.
FAN_OUT_SEVERITIES = ("warning", "review")

# A boundary names the exception(s) it approves either as `exception = "X"` or as
# `exceptions = ["X", "Y"]` (0.2.0); exactly one of the two, checked in config.py.
BOUNDARY_SCHEMA = TableField(
    fields={
        "path": StrField(allow_empty=False),
        "language": EnumField(LANGUAGES),
        "exception": StrField(allow_empty=False),
        "exceptions": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
    },
    required=("path", "language", "reason"),
)

OVERRIDE_SCHEMA = TableField(
    fields={
        "paths": ListField(StrField(allow_empty=False)),
        "disable": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
    },
    required=("paths", "disable", "reason"),
)

CONFIG_SCHEMA = TableField(
    fields={
        "profile": EnumField(PROFILES),
        "include": ListField(StrField(allow_empty=False)),
        "exclude": ListField(StrField(allow_empty=False)),
        "parse_errors": EnumField(("fail", "warn")),
        "follow_symlinks": BoolField(),
        "rules": TableField(
            fields={
                "magic_numbers": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(SECTION_SEVERITIES),
                        "allowed_values": ListField(NumberField()),
                        "allow_unary_negative_one": BoolField(),
                        "named_constant_definitions": EnumField(NAMED_CONSTANT_MODES),
                        "exclude_configuration_files": BoolField(),
                        "configuration_files": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "magic_strings": TableField(
                    fields={"enabled": BoolField(), "mode": EnumField(("review", "fail"))},
                    required=(),
                ),
                "exceptions": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(SECTION_SEVERITIES),
                        "mode": EnumField(("boundary_whitelist",)),
                        "transparent_rethrow": BoolField(),
                        "transparent_guards": ListField(StrField(allow_empty=False)),
                        "boundaries": ListField(BOUNDARY_SCHEMA),
                    },
                    required=(),
                ),
                "defaults": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(SECTION_SEVERITIES),
                        "function_parameters": EnumField(SEVERITY_MODES),
                        "dataclass_fields": EnumField(SEVERITY_MODES),
                        "missing_value_fallbacks": EnumField(SEVERITY_MODES),
                        "truthiness_fallbacks": EnumField(SEVERITY_MODES),
                        "nullish_fallbacks": EnumField(SEVERITY_MODES),
                        "configuration_fallbacks": EnumField(SEVERITY_MODES),
                    },
                    required=(),
                ),
            },
            required=(),
        ),
        "complexity": TableField(
            fields={
                "enabled": BoolField(),
                "cognitive_warn": IntField(minimum=1),
                "cyclomatic_warn": IntField(minimum=1),
                "max_nesting_warn": IntField(minimum=1),
                "cyclomatic_counts_boolean_operators": BoolField(),
                "npath_cap": IntField(minimum=1),
                "npath_warn": IntField(minimum=1),
                "fan_out_warn": IntField(minimum=1),
                "fan_out_severity": EnumField(FAN_OUT_SEVERITIES),
                "max_lines_warn": IntField(minimum=1),
                "npath_only_without_cognitive": BoolField(),
                "abstraction_displacement": BoolField(),
            },
            required=(),
        ),
        "history": TableField(
            fields={
                "enabled": BoolField(),
                "horizon_days": IntField(minimum=1),
                "min_support": IntField(minimum=1),
            },
            required=(),
        ),
        "gates": TableField(
            fields={
                "new_hard_violations": EnumField(("fail", "warn")),
                "legacy": EnumField(("baseline", "fail", "ignore")),
                "complexity_regressions": EnumField(("warn", "fail", "ignore")),
            },
            required=(),
        ),
        "overrides": ListField(OVERRIDE_SCHEMA),
    },
    required=(),
)


def validate_shape(raw: Any) -> list[ConfigIssue]:
    """Validate the ``[tool.shockharness]`` table shape. Returns all issues found."""
    issues: list[ConfigIssue] = []
    CONFIG_SCHEMA.check(raw, "", issues)
    return issues


def boundary_exceptions(boundary: Mapping[str, Any]) -> tuple[str, ...]:
    """The exception names a validated boundary approves, whichever key spelled them."""
    if "exceptions" in boundary:
        return tuple(str(name) for name in boundary["exceptions"])
    return (str(boundary["exception"]),)
