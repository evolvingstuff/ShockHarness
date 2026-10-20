"""Configuration schema: shape validation with exact key paths in every message.

The schema is data (a tree of field descriptors) rather than code so the loader
can reject unknown keys, wrong types, and bad enum values with one consistent
error format. Semantic checks that need other modules (rule IDs, glob validity,
supported languages) live in :mod:`shockharness.config`.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.ir.model import SHAPE_MIN_STATEMENTS
from shockharness.roles import CLASSIFIED_ROLES, ROLES

# A RESULT001 catalog entry: a qualified function or ".method", optionally with the number
# of positional arguments the pure callee takes (".replace/2-3", ".join/1"); a call with
# another count is some other method of that name (Thread.join(), location.replace(url)).
MUST_USE_ENTRY = re.compile(
    r"(?P<name>\.?[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)(?:/(?P<low>\d+)(?:-(?P<high>\d+))?)?"
)
MUST_USE = "a callee or .method, optionally /N or /N-M arguments (.replace/2-3)"
# A DOM002 skip list: the file that holds it and the function, "path:function".
PRESS_EXCLUSION = re.compile(r"[^:]+:[A-Za-z_$][\w$]*")
EXCLUSION = "path:function (app/events.js:isExcluded)"


@dataclass(frozen=True)
class ConfigIssue:
    key_path: str
    message: str

    def render(self) -> str:
        return f"{self.key_path}: {self.message}"


class Field(ABC):
    """Base descriptor. Subclasses append :class:`ConfigIssue` for every problem."""

    @abstractmethod
    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None: ...


class StrField(Field):
    def __init__(self, allow_empty: bool) -> None:
        self.allow_empty = allow_empty

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, str):
            issues.append(ConfigIssue(key_path, f"expected a string, got {type_name(value)}"))
            return
        if not self.allow_empty and value.strip() == "":
            issues.append(ConfigIssue(key_path, "must not be empty"))


class PatternField(Field):
    def __init__(self, pattern: re.Pattern[str], description: str) -> None:
        self.pattern = pattern
        self.description = description

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, str):
            issues.append(ConfigIssue(key_path, f"expected a string, got {type_name(value)}"))
            return
        if self.pattern.fullmatch(value) is None:
            issues.append(ConfigIssue(key_path, f"expected {self.description}, got {value!r}"))


class BoolField(Field):
    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, bool):
            issues.append(ConfigIssue(key_path, f"expected true or false, got {type_name(value)}"))


class IntField(Field):
    def __init__(self, minimum: int) -> None:
        self.minimum = minimum

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(ConfigIssue(key_path, f"expected an integer, got {type_name(value)}"))
            return
        if value < self.minimum:
            issues.append(ConfigIssue(key_path, f"must be at least {self.minimum}, got {value}"))


class NumberField(Field):
    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            issues.append(ConfigIssue(key_path, f"expected a number, got {type_name(value)}"))


class EnumField(Field):
    def __init__(self, choices: Sequence[str]) -> None:
        self.choices = tuple(choices)

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, str) or value not in self.choices:
            rendered = ", ".join(repr(c) for c in self.choices)
            issues.append(ConfigIssue(key_path, f"must be one of {rendered}, got {value!r}"))


class ListField(Field):
    def __init__(self, item: Field) -> None:
        self.item = item

    def check(self, value: Any, key_path: str, issues: list[ConfigIssue]) -> None:
        if not isinstance(value, list):
            issues.append(ConfigIssue(key_path, f"expected a list, got {type_name(value)}"))
            return
        for index, element in enumerate(value):
            self.item.check(element, f"{key_path}[{index}]", issues)


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
# The severity every VERIFY finding carries (H2). "warning" is the bundled default
# (spec 21.1 decision 9); "error" makes them gate; "review" lowers them further.
VERIFICATION_SEVERITIES = ("warning", "error", "review")
# A file matched by `include` whose extension no adapter parses (a .ts file in a JavaScript
# tree): "fail" is an analysis failure (exit 3), "warn" lists it under coverage, "ignore"
# says nothing. Strictest first.
UNSUPPORTED_SOURCE_POLICIES = ("fail", "warn", "ignore")
# MAGIC001 on the definition of a module-level named constant (MAX_PAGES = 8): "report"
# (strict: a named constant is not automatically justified) or "allow" (the name is the
# remedy the rule asks for; recommended and minimal).
NAMED_CONSTANT_MODES = ("report", "allow")
LANGUAGES = ("python", "javascript", "typescript")
# A catch boundary may name C# (G2, decision 41); contracts and catalogs do not cover it yet.
BOUNDARY_LANGUAGES = (*LANGUAGES, "csharp")
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
        "language": EnumField(BOUNDARY_LANGUAGES),
        "exception": StrField(allow_empty=False),
        "exceptions": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
    },
    required=("path", "language", "reason"),
)

# IMPORT002 (decision 44): files the importers globs match may not import a file the
# imported globs match, except the names allowed_names lists (required; [] allows none).
FORBIDDEN_IMPORT_SCHEMA = TableField(
    fields={
        "importers": ListField(StrField(allow_empty=False)),
        "imported": ListField(StrField(allow_empty=False)),
        "allowed_names": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
    },
    required=("importers", "imported", "allowed_names", "reason"),
)

# An override scopes its rule IDs either by path globs (`paths`) or by file role
# (`roles`, H1); exactly one of the two, checked in config.py.
OVERRIDE_SCHEMA = TableField(
    fields={
        "paths": ListField(StrField(allow_empty=False)),
        "roles": ListField(EnumField(ROLES)),
        "disable": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
    },
    required=("disable", "reason"),
)

# `[tool.shockharness.file_roles]` (H1): one glob list per classified role; a file whose
# path none of them matches is `production`.
FILE_ROLES_SCHEMA = TableField(
    fields={role: ListField(StrField(allow_empty=False)) for role in CLASSIFIED_ROLES},
    required=(),
)

# The H3 guardrail sections (rules.stubs, .assertions, .boolean_arguments, .module_state,
# .import_effects) share these keys; `severity` is the findings' severity, as in
# rules.verification.
GUARDRAIL_COMMON: dict[str, Field] = {
    "enabled": BoolField(),
    "severity": EnumField(VERIFICATION_SEVERITIES),
    "roles": ListField(EnumField(ROLES)),
}

# Property contracts (spec P1a): a catalog property and a callee sink.
CONTRACT_RUNTIME_LEVELS = ("static", "check", "verify")
CONTRACT_PROPERTY_SCHEMA = TableField(
    fields={
        "name": StrField(allow_empty=False),
        "description": StrField(allow_empty=False),
        "producers": ListField(StrField(allow_empty=False)),
        "runtime": EnumField(CONTRACT_RUNTIME_LEVELS),
        # A string literal with no interpolation carries the property (spec §5.2a).
        "literal_satisfies": BoolField(),
    },
    required=("name", "description", "producers", "runtime"),
)
# A sink is a callee ("callee:N") or an assignment target ("innerHTML", "headers[]");
# catalog_issues requires exactly one of the two.
CONTRACT_SINK_SCHEMA = TableField(
    fields={
        "language": EnumField(LANGUAGES),
        "callee": StrField(allow_empty=False),
        "target": StrField(allow_empty=False),
        "requires": ListField(StrField(allow_empty=False)),
        "reason": StrField(allow_empty=False),
        "producer": StrField(allow_empty=False),
    },
    required=("language", "requires", "reason"),
)
CONTRACT_OPERATIONS = ("template_literal", "concat", "fstring", "format", "join")
CONTRACT_COMPOSITION_SCHEMA = TableField(
    fields={
        "language": EnumField(LANGUAGES),
        "operation": EnumField(CONTRACT_OPERATIONS),
        "inputs_require": ListField(StrField(allow_empty=False)),
        "produces": StrField(allow_empty=False),
        "reason": StrField(allow_empty=False),
    },
    required=("language", "operation", "inputs_require", "produces", "reason"),
)

# `[[tool.shockharness.rules.module_state.allowed]]`: a deliberate process-wide binding.
ALLOWED_STATE_SCHEMA = TableField(
    fields={
        "path": StrField(allow_empty=False),
        "name": StrField(allow_empty=False),
        "reason": StrField(allow_empty=False),
    },
    required=("path", "name", "reason"),
)

CONFIG_SCHEMA = TableField(
    fields={
        "profile": EnumField(PROFILES),
        "include": ListField(StrField(allow_empty=False)),
        "exclude": ListField(StrField(allow_empty=False)),
        "parse_errors": EnumField(("fail", "warn")),
        "unsupported_sources": EnumField(UNSUPPORTED_SOURCE_POLICIES),
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
                        "magic004_severity": EnumField(VERIFICATION_SEVERITIES),
                        "magic005_severity": EnumField(VERIFICATION_SEVERITIES),
                        "exclude_configuration_files": BoolField(),
                        "configuration_files": ListField(StrField(allow_empty=False)),
                        "fail_on_unknown": BoolField(),
                    },
                    required=(),
                ),
                "magic_strings": TableField(
                    fields={
                        "enabled": BoolField(),
                        "mode": EnumField(("review", "fail")),
                        "roles": ListField(EnumField(ROLES)),
                        "min_length": IntField(minimum=1),
                        "min_occurrences": IntField(minimum=1),
                        "min_files": IntField(minimum=1),
                        "min_compared_files": IntField(minimum=0),
                        "kinds": ListField(
                            EnumField(("argument", "subscript", "compare", "value", "key", "jsx"))
                        ),
                        "message_callees": ListField(StrField(allow_empty=False)),
                        "allowed": ListField(StrField(allow_empty=True)),
                    },
                    required=(),
                ),
                "exceptions": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(SECTION_SEVERITIES),
                        "mode": EnumField(("boundary_whitelist",)),
                        "transparent_rethrow": BoolField(),
                        "transparent_guards": ListField(StrField(allow_empty=False)),
                        "capture_managers": ListField(StrField(allow_empty=False)),
                        "boundaries": ListField(BOUNDARY_SCHEMA),
                        "fail_on_unknown": BoolField(),
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
                        "fallback_helpers": EnumField(SEVERITY_MODES),
                        "fail_on_unknown": BoolField(),
                    },
                    required=(),
                ),
                "stubs": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "markers": ListField(StrField(allow_empty=False)),
                        "test_path_segments": ListField(StrField(allow_empty=False)),
                        "mock_modules": ListField(StrField(allow_empty=False)),
                        "stub003_severity": EnumField(VERIFICATION_SEVERITIES),
                    },
                    required=(),
                ),
                "assertions": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "assert002_severity": EnumField(VERIFICATION_SEVERITIES),
                        "allow_type_narrowing": BoolField(),
                        "external_reads": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "dom": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "classes": ListField(StrField(allow_empty=False)),
                        "dom002_severity": EnumField(VERIFICATION_SEVERITIES),
                        "press_exclusions": ListField(PatternField(PRESS_EXCLUSION, EXCLUSION)),
                    },
                    required=(),
                ),
                "boolean_arguments": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "allowed_callees": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "module_state": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "allowed": ListField(ALLOWED_STATE_SCHEMA),
                        "state002_severity": EnumField(VERIFICATION_SEVERITIES),
                    },
                    required=(),
                ),
                "import_effects": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "python_operations": ListField(StrField(allow_empty=False)),
                        "javascript_operations": ListField(StrField(allow_empty=False)),
                        "script_files": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "async_lifecycle": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "fail_on_unknown": BoolField(),
                        "python_coroutine_apis": ListField(StrField(allow_empty=False)),
                        "javascript_promise_apis": ListField(StrField(allow_empty=False)),
                        "supervisors": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "processes": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "python_process_apis": ListField(StrField(allow_empty=False)),
                        "javascript_process_apis": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "results": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "python_must_use": ListField(PatternField(MUST_USE_ENTRY, MUST_USE)),
                        "javascript_must_use": ListField(PatternField(MUST_USE_ENTRY, MUST_USE)),
                        "csharp_must_use": ListField(PatternField(MUST_USE_ENTRY, MUST_USE)),
                    },
                    required=(),
                ),
                "types": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "report_any": BoolField(),
                        "report_cast": BoolField(),
                        "report_non_null": BoolField(),
                        "report_type_ignore": BoolField(),
                        "annotated_share": NumberField(),
                        "min_annotated_functions": IntField(1),
                        "type002_severity": EnumField(VERIFICATION_SEVERITIES),
                    },
                    required=(),
                ),
                "sleep": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "python_sleep_apis": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "retry": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "retry_decorators": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "batches": TableField(fields=dict(GUARDRAIL_COMMON), required=()),
                "sentinels": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "values": ListField(NumberField()),
                        "python_index_callees": ListField(StrField(allow_empty=False)),
                        "javascript_index_callees": ListField(StrField(allow_empty=False)),
                        "standard_targets": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "consistency": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "python_fabricators": ListField(StrField(allow_empty=False)),
                        "javascript_fabricators": ListField(StrField(allow_empty=False)),
                        "issuer_prefixes": ListField(StrField(allow_empty=False)),
                        "guard_min_sites": IntField(minimum=1),
                        "guard_min_percent": IntField(minimum=1),
                    },
                    required=(),
                ),
                "input": TableField(
                    fields={
                        **GUARDRAIL_COMMON,
                        "input002_severity": EnumField(VERIFICATION_SEVERITIES),
                        "max_depth": IntField(minimum=1),
                        "python_sources": ListField(StrField(allow_empty=False)),
                        "javascript_sources": ListField(StrField(allow_empty=False)),
                        "python_sinks": ListField(StrField(allow_empty=False)),
                        "javascript_sinks": ListField(StrField(allow_empty=False)),
                        "python_validators": ListField(StrField(allow_empty=False)),
                        "javascript_validators": ListField(StrField(allow_empty=False)),
                        "python_config_reads": ListField(StrField(allow_empty=False)),
                        "javascript_config_reads": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "property_contracts": TableField(
                    fields={
                        "enabled": BoolField(),
                        "roles": ListField(EnumField(ROLES)),
                        "fail_on_unknown": BoolField(),
                        "runtime_module": ListField(StrField(allow_empty=False)),
                        "allow_undeclared": BoolField(),
                        "enforcement": EnumField(("declared", "complete")),
                        "complete_paths": ListField(StrField(allow_empty=False)),
                        "max_depth": IntField(minimum=1),
                        "runtime_mode_required": EnumField(("off", "check", "verify")),
                        "registration_module": StrField(allow_empty=True),
                        "properties": ListField(CONTRACT_PROPERTY_SCHEMA),
                        "sinks": ListField(CONTRACT_SINK_SCHEMA),
                        "compositions": ListField(CONTRACT_COMPOSITION_SCHEMA),
                        "severities": TableField(
                            fields={
                                rule: EnumField(VERIFICATION_SEVERITIES)
                                for rule in (
                                    "PROP001",
                                    "PROP002",
                                    "PROP003",
                                    "PROP004",
                                    "PROP005",
                                    "PROP006",
                                    "PROP007",
                                    "PROP008",
                                )
                            },
                            required=(),
                        ),
                    },
                    required=(),
                ),
                "import_boundaries": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(VERIFICATION_SEVERITIES),
                        "forbidden": ListField(FORBIDDEN_IMPORT_SCHEMA),
                    },
                    required=(),
                ),
                "duplicates": TableField(
                    fields={
                        "enabled": BoolField(),
                        "roles": ListField(EnumField(ROLES)),
                        "min_statements": IntField(minimum=SHAPE_MIN_STATEMENTS),
                        "min_tokens": IntField(minimum=1),
                        "similarity": NumberField(),
                        "severity": EnumField(VERIFICATION_SEVERITIES),
                        "dup002_severity": EnumField(VERIFICATION_SEVERITIES),
                    },
                    required=(),
                ),
                "dead_code": TableField(
                    fields={
                        "enabled": BoolField(),
                        "roles": ListField(EnumField(ROLES)),
                        "entry_points": ListField(StrField(allow_empty=False)),
                        "severity": EnumField(VERIFICATION_SEVERITIES),
                        "dead002_severity": EnumField(VERIFICATION_SEVERITIES),
                    },
                    required=(),
                ),
                "role_integrity": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(VERIFICATION_SEVERITIES),
                        "empty_test_severity": EnumField(VERIFICATION_SEVERITIES),
                        "support_files": ListField(StrField(allow_empty=False)),
                    },
                    required=(),
                ),
                "verification": TableField(
                    fields={
                        "enabled": BoolField(),
                        "severity": EnumField(VERIFICATION_SEVERITIES),
                        "fail_on_unknown": BoolField(),
                        "allowed_skip_reasons": ListField(StrField(allow_empty=False)),
                        "report_narrow_suppressions": BoolField(),
                        "rule_switching_severity": EnumField(VERIFICATION_SEVERITIES),
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
                "fail_on_unknown": BoolField(),
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
        "file_roles": FILE_ROLES_SCHEMA,
        "cache": TableField(
            fields={"enabled": BoolField(), "directory": StrField(allow_empty=False)},
            required=(),
        ),
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
