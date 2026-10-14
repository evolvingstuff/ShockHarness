"""The rule registry: immutable metadata for every rule ID the project defines.

Every ID from the specification is registered here, including rules that are
not implemented yet. Unimplemented rules are reported as *not analyzed* so a
clean report never implies coverage the tool does not have.
"""

from dataclasses import dataclass

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_REVIEW = "review"
SEVERITY_NOTE = "note"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_REVIEW, SEVERITY_NOTE)

PYTHON = "python"
JAVASCRIPT = "javascript"
ALL_LANGUAGES = (PYTHON, JAVASCRIPT)


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    version: str
    name: str
    family: str
    config_section: str | None
    default_severity: str
    implemented: bool
    languages: tuple[str, ...]
    summary: str
    rationale: str
    guarantees: str
    limitations: str
    remediation: str
    noncompliant_example: str
    compliant_example: str


def _planned(
    rule_id: str,
    name: str,
    family: str,
    config_section: str,
    default_severity: str,
    summary: str,
) -> RuleSpec:
    return RuleSpec(
        rule_id=rule_id,
        version="0",
        name=name,
        family=family,
        config_section=config_section,
        default_severity=default_severity,
        implemented=False,
        languages=ALL_LANGUAGES,
        summary=summary,
        rationale="See the specification; this rule is registered but not yet implemented.",
        guarantees="None. The rule produces no findings in this version.",
        limitations="Not implemented. Files are reported as not analyzed for this rule.",
        remediation="Not applicable until the rule is implemented.",
        noncompliant_example="",
        compliant_example="",
    )


MAGIC001 = RuleSpec(
    rule_id="MAGIC001",
    version="1",
    name="numeric literal outside 0/1",
    family="magic_numbers",
    config_section="rules.magic_numbers",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="Every numeric literal in executable code must be exactly 0 or 1.",
    rationale=(
        "A bare number carries no contract: nobody can tell whether 30 is a timeout, a "
        "retry budget, or a protocol code, or why it is 30. Naming it is not enough on its "
        "own either; the value has to come from a validated configuration parameter or an "
        "authoritative specification constant. The analyzer does not invent exemptions for "
        "2, 10, 24, 60, or any other 'obvious' number."
    ),
    guarantees=(
        "Exact on numeric AST nodes: int, float, complex (Python) and number/bigint "
        "(JavaScript) literals in any encoding (decimal, hex, octal, binary, exponent, "
        "separators). Value-based: 0x1, 1.0, 1e0, 0b0 and 1n pass as 0 or 1. Unary minus "
        "over a literal is checked as one unit: -1 fails unless allow_unary_negative_one is "
        "set; -0 and -0.0 always fail. Python booleans are never flagged. Numeric literals in "
        "Python type annotations are flagged."
    ),
    limitations=(
        "Does not look inside strings or regular-expression literals; '30' and /\\d{3}/ are "
        "not numeric nodes. Does not detect numbers built at runtime (int('30')). NaN and "
        "Infinity are identifiers, not literals, and are not flagged. Files that fail to "
        "parse are reported as parse failures, not as clean."
    ),
    remediation=(
        "Identify the contract behind the value. Variable policy (timeouts, limits, sizes) "
        "becomes a required, validated configuration parameter. Invariant mathematics or a "
        "published specification value becomes a named constant that cites its source. "
        "Never move the number into an unexplained constant and never add a fallback. A "
        "0 or 1 that carries meaning (an exit code, a sentinel) deserves a name too, even "
        "though the rule permits it."
    ),
    noncompliant_example=(
        "timeout = 30\n"
        "for i in range(2): ...\n"
        "const page = items.slice(0, 10);\n"
        "if (retries > -1) {}"
    ),
    compliant_example=(
        "timeout = settings.request_timeout_seconds  # required, validated at load\n"
        "for i in range(settings.worker_count): ...\n"
        "const page = items.slice(0, config.pageSize);\n"
        "area = math.pi * r ** 2  # still fails on the 2: use a named SQUARE exponent or x*x"
    ),
)

SUPP001 = RuleSpec(
    rule_id="SUPP001",
    version="1",
    name="invalid suppression comment",
    family="suppressions",
    config_section=None,
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A shockharness suppression comment is malformed, names an unknown rule, or lacks a reason."
    ),
    rationale=(
        "A suppression is a policy decision. One that does not name an exact rule and give a "
        "reason is indistinguishable from hiding a violation."
    ),
    guarantees="Exact: every comment starting with the 'shockharness:' prefix is checked.",
    limitations="Only the single-line form on the same line as the construct is recognized.",
    remediation=(
        'Use the exact form: # shockharness: ignore[RULEID] reason="why this is justified" '
        "(JavaScript: // shockharness: ...). Keep the scope to one line."
    ),
    noncompliant_example="x = 30  # shockharness: ignore\ny = 30  # shockharness: ignore[MAGIC001]",
    compliant_example=(
        'x = 30  # shockharness: ignore[MAGIC001] reason="RFC 7231 section 6.5.1 status class"'
    ),
)

SUPP002 = RuleSpec(
    rule_id="SUPP002",
    version="1",
    name="unused suppression comment",
    family="suppressions",
    config_section=None,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="A suppression comment names a rule that produced no finding on that line.",
    rationale=(
        "Stale suppressions accumulate and later hide real violations. They also suggest the "
        "code changed without the policy decision being revisited."
    ),
    guarantees="Exact: computed after all enabled rules have run on the file.",
    limitations=(
        "A suppression for a rule that is disabled or not implemented is reported as unused, "
        "because it did nothing; re-check it when the rule is enabled."
    ),
    remediation="Delete the suppression, or move it to the line that still needs it.",
    noncompliant_example='x = 1  # shockharness: ignore[MAGIC001] reason="no longer needed"',
    compliant_example="x = 1",
)

RULES: tuple[RuleSpec, ...] = (
    MAGIC001,
    _planned(
        "MAGIC002",
        "suspicious string literal",
        "magic_strings",
        "rules.magic_strings",
        SEVERITY_REVIEW,
        "Decision strings, status codes, endpoints and repeated protocol strings should be named.",
    ),
    _planned(
        "EXC001",
        "forbidden catch",
        "exceptions",
        "rules.exceptions",
        SEVERITY_ERROR,
        "Every catch is forbidden unless it sits in an approved external boundary.",
    ),
    _planned(
        "EXC002",
        "suppressed or converted exception",
        "exceptions",
        "rules.exceptions",
        SEVERITY_ERROR,
        "A catch that passes, logs only, or returns a success-shaped value hides failure.",
    ),
    _planned(
        "EXC003",
        "broad try scope / unverified boundary",
        "exceptions",
        "rules.exceptions",
        SEVERITY_ERROR,
        "An approved catch must wrap only the sanctioned external operation.",
    ),
    _planned(
        "DEF001",
        "function parameter default",
        "defaults",
        "rules.defaults",
        SEVERITY_ERROR,
        "Parameter default values are forbidden in strict mode.",
    ),
    _planned(
        "DEF002",
        "missing mapping/object fallback",
        "defaults",
        "rules.defaults",
        SEVERITY_ERROR,
        "mapping.get(key, fallback), getattr(obj, name, fallback) and obj?.x ?? fallback "
        "mask missing data.",
    ),
    _planned(
        "DEF003",
        "truthiness fallback",
        "defaults",
        "rules.defaults",
        SEVERITY_REVIEW,
        "x or default / x || default also replace legitimate falsy values.",
    ),
    _planned(
        "DEF004",
        "nullish fallback",
        "defaults",
        "rules.defaults",
        SEVERITY_ERROR,
        "x ?? default and 'x if x is not None else default' substitute for missing data.",
    ),
    _planned(
        "DEF005",
        "exception-to-default",
        "defaults",
        "rules.defaults",
        SEVERITY_ERROR,
        "A catch that returns a literal converts failure into a default.",
    ),
    _planned(
        "DEF006",
        "implicit configuration fallback",
        "defaults",
        "rules.defaults",
        SEVERITY_ERROR,
        "os.getenv('X', value) / process.env.X || value bypass validated configuration.",
    ),
    _planned(
        "CPLX001",
        "cyclomatic complexity",
        "complexity",
        "complexity",
        SEVERITY_WARNING,
        "Function cyclomatic complexity above the configured threshold.",
    ),
    _planned(
        "CPLX002",
        "cognitive complexity",
        "complexity",
        "complexity",
        SEVERITY_WARNING,
        "Function cognitive complexity above the configured threshold.",
    ),
    _planned(
        "CPLX003",
        "nesting depth",
        "complexity",
        "complexity",
        SEVERITY_WARNING,
        "Decision nesting deeper than the configured threshold.",
    ),
    _planned(
        "CPLX004",
        "NPath estimate",
        "complexity",
        "complexity",
        SEVERITY_WARNING,
        "Bounded acyclic path estimate above threshold or saturated.",
    ),
    _planned(
        "CPLX005",
        "coupling / cycles",
        "complexity",
        "complexity",
        SEVERITY_WARNING,
        "Module cycles, fan-in/fan-out and shared mutable state heuristics.",
    ),
    SUPP001,
    SUPP002,
)

RULES_BY_ID: dict[str, RuleSpec] = {rule.rule_id: rule for rule in RULES}


def rule_ids() -> tuple[str, ...]:
    return tuple(rule.rule_id for rule in RULES)


def implemented_rules() -> tuple[RuleSpec, ...]:
    return tuple(rule for rule in RULES if rule.implemented)


def is_known_rule(rule_id: str) -> bool:
    return rule_id in RULES_BY_ID


def get_rule(rule_id: str) -> RuleSpec:
    """Look up a rule. Callers validate IDs first; an unknown ID here is a programming error."""
    if rule_id not in RULES_BY_ID:
        raise KeyError(f"unknown rule ID {rule_id!r}")
    return RULES_BY_ID[rule_id]
