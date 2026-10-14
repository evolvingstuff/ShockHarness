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

EXC001 = RuleSpec(
    rule_id="EXC001",
    version="1",
    name="forbidden catch",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "Every catch is forbidden unless the file is inside a configured boundary that names "
        "exactly the exception the handler catches."
    ),
    rationale=(
        "A catch is a decision that some failure is expected and handled. That decision is only "
        "defensible for failures of systems outside the program's control (network, disk, "
        "external input), and only when the exception identity is known. Catching Exception, "
        "a bare except, or an exception whose identity cannot be resolved hides internal "
        "defects as if they were expected events. There is no global whitelist of 'harmless' "
        "exceptions: ValueError around parsing external input may be a boundary; ValueError "
        "around your own arithmetic is a hidden bug."
    ),
    guarantees=(
        "Python: every except/except* handler of try is checked. Handler types are resolved "
        "through builtins, module-level absolute imports (exact), relative imports, classes "
        "defined in the module, and nested imports (approximate). Tuples are checked member by "
        "member; every member must be approved. Bare except, Exception, BaseException, and "
        "unresolved or dynamic type expressions fail closed with an explicit diagnostic. "
        "JavaScript: every catch clause, promise .catch(handler), and .then(onFulfilled, "
        "onRejected) is checked. A JavaScript catch has no type; it is approved only inside a "
        "boundary whose exception names the class that the handler's first statement checks "
        "with instanceof and otherwise re-throws (if (!(err instanceof C)) throw err; or "
        "if (err instanceof C) {...} else { throw err; }). That identity is approximate: nothing "
        "proves what C is bound to. With transparent_rethrow = true, a handler that only "
        "re-raises the caught exception passes this rule."
    ),
    limitations=(
        "Resolution is static and best effort: a name rebound at runtime, an import inside a "
        "function that shadows a module-level one, or star imports are not followed; such "
        "identities are reported as unresolved, never guessed. Approximate identities match a "
        "boundary by dotted suffix (.errors.X matches pkg.errors.X). Class hierarchies are not "
        "known, so a boundary for OSError does not approve FileNotFoundError and a catch of a "
        "broad library base class is only flagged when it is Exception or BaseException. "
        "JavaScript guards joined with || or expressed as err.name === '...' are not "
        "recognized. A rejection handler passed by reference is opaque and fails closed. "
        "Context managers, __exit__ methods, and signal handlers are not catches and are not "
        "inspected."
    ),
    remediation=(
        "Let the exception propagate. If the operation really is an external boundary, declare "
        "it in rules.exceptions.boundaries with the file, language, the qualified exception "
        "class, and the reason, then make the handler convert the failure into a typed error "
        "or re-raise with its cause. Never widen the caught type to make a boundary match."
    ),
    noncompliant_example=(
        "try:\n    data = json.loads(raw)\nexcept Exception:\n    data = {}\n"
        "try { await fetch(url); } catch (e) { return null; }"
    ),
    compliant_example=(
        "# .shockharness.toml: boundaries = [{path='src/net.py', language='python',\n"
        "#   exception='requests.exceptions.Timeout', reason='external HTTP call'}]\n"
        "try:\n    response = session.get(url, timeout=settings.timeout)\n"
        "except requests.exceptions.Timeout as exc:\n"
        "    raise UpstreamUnavailable(url) from exc\n"
        "try { await fetch(url); } catch (err) {\n"
        "  if (!(err instanceof TimeoutError)) throw err;\n"
        "  throw new UpstreamUnavailable(url, { cause: err });\n}"
    ),
)

EXC002 = RuleSpec(
    rule_id="EXC002",
    version="1",
    name="suppressed or converted exception",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A handler that passes, only logs, returns a fabricated value, or replaces the exception "
        "without its cause hides the failure, even inside an approved boundary."
    ),
    rationale=(
        "Catching is only acceptable when the failure stays visible: it is re-raised, converted "
        "into a typed error that carries the original as its cause, or handled by code that "
        "demonstrably does something else. pass, ..., an empty block, a log line, return None, "
        "return [] and friends all turn a failure into an apparently successful result. Logging "
        "is a record, not a remedy."
    ),
    guarantees=(
        "Exact on handler shape. Flags: a body that is only pass/.../empty; a body made only of "
        "logging or printing statements (logging.*, logger.*, log.*, print, warnings.warn, "
        "traceback.print_exc, sys.stderr.write, console.*, process.stderr.write); a body whose "
        "only non-logging statement returns nothing, None/null/undefined, a constant, or a "
        "container built only of constants (optionally after logging); a body whose only "
        "non-logging statement raises or throws something other than the caught exception "
        "without preserving it as the cause (raise X, raise X from None, throw new X()). "
        "Bare raise, raise err, raise X from err, throw err and throw new X(..., {cause: err}) "
        "are not flagged. Applies to approved and unapproved catches alike."
    ),
    limitations=(
        "A handler with several non-logging statements, or one that returns a variable or a "
        "call result, is 'other' and not flagged by this rule (EXC001 still applies). Whether "
        "a returned variable is a fabricated default is not decided here; DEF005 will cross-"
        "reference catches with defaults. A guarded JavaScript handler is classified by the "
        "statements after the instanceof guard."
    ),
    remediation=(
        "Re-raise, or raise a typed error with 'from exc' (JavaScript: new Error(msg, "
        "{ cause: err })). Remove the logging-only handler and let the caller decide. If the "
        "operation is optional, make that explicit in the contract and return a typed outcome, "
        "never a bare None/null/false/0."
    ),
    noncompliant_example=(
        "except OSError:\n    pass\n"
        "except OSError as exc:\n    logger.warning('failed: %s', exc)\n"
        "except OSError:\n    return None\n"
        "except OSError:\n    raise ConfigError('unreadable')\n"
        "catch (err) { console.error(err); }\n"
        "catch (err) { return []; }"
    ),
    compliant_example=(
        "except OSError as exc:\n    raise ConfigError(f'cannot read {path}') from exc\n"
        "except OSError:\n    raise\n"
        "catch (err) { throw new ConfigError(path, { cause: err }); }"
    ),
)

EXC003 = RuleSpec(
    rule_id="EXC003",
    version="1",
    name="broad try scope / unverified boundary",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "An approved catch may protect only the one sanctioned external operation; a try body "
        "with more statements, or a statement that cannot be attributed to a single call, is "
        "an unverified boundary."
    ),
    rationale=(
        "A boundary approves catching one failure from one external operation. When the try "
        "body also parses, validates, or computes, the same handler catches internal defects "
        "in that code too, and the approval no longer means what it says. Static analysis "
        "cannot infer which line raises, so the only verifiable shape is a try body that is "
        "exactly the sanctioned call."
    ),
    guarantees=(
        "Runs only on catches that EXC001 approved through a boundary. Flags a try body with "
        "zero or more than one statement, and a single statement that is not a plain call "
        "(or import): compound statements, assignments of non-call values, subscripts, and "
        "statements that perform more than one operation (nested calls, comprehensions, "
        "lambdas, extra awaits). The attributable forms are expression, assignment, "
        "augmented assignment, annotated assignment, or return of a single call, optionally "
        "awaited, and import statements. JavaScript: an expression statement, single-variable "
        "declaration, or return of one call or new expression, optionally awaited. For promise "
        "handlers the receiver of .catch/.then must itself be one call: x.catch(h) where x is a "
        "variable, and fetch(u).then(f).catch(h), are flagged."
    ),
    limitations=(
        "Arguments of the one call may be arbitrary names, attributes, and constants; argument "
        "evaluation that raises is attributed to the call. Finally and else clauses are not "
        "inspected. The rule reports what the try body contains, not which statement raises: "
        "a finding with approximate confidence says the boundary is unverified, not that it "
        "is wrong."
    ),
    remediation=(
        "Move everything except the external call out of the try body: prepare inputs before "
        "it, bind the result, and parse or validate the result after it. One try per "
        "sanctioned operation."
    ),
    noncompliant_example=(
        "try:\n    raw = fetch(url)\n    data = json.loads(raw)\n    validate(data)\n"
        "except Timeout as exc:\n    raise Upstream(url) from exc"
    ),
    compliant_example=(
        "try:\n    raw = fetch(url)\nexcept Timeout as exc:\n    raise Upstream(url) from exc\n"
        "data = json.loads(raw)\nvalidate(data)"
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
    EXC001,
    EXC002,
    EXC003,
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
