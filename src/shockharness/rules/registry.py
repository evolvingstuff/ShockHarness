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

DEF001 = RuleSpec(
    rule_id="DEF001",
    version="1",
    name="function parameter default",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "Parameter default values (and dataclass field defaults) are forbidden in strict mode: "
        "every argument is passed explicitly."
    ),
    rationale=(
        "A default decides a value the caller did not decide. It hides whether the caller "
        "forgot the argument or meant the default, lets a wrong value travel silently through "
        "every call that omits it, and makes the signature lie about what the function needs. "
        "Dataclass field defaults are the same decision on the generated __init__. This is an "
        "opinionated project policy, not a claim about idiomatic Python or JavaScript."
    ),
    guarantees=(
        "Exact on the syntax. Python: positional and keyword-only defaults of def, async def "
        "and lambda; dataclass fields (a class decorated with dataclass or dataclasses.dataclass, "
        "with or without arguments) whose annotated field has a value, field(default=...) or "
        "field(default_factory=...), each reported with its own kind. JavaScript: assignment "
        "patterns in the parameters of function declarations and expressions, arrow functions, "
        "methods and constructors, including defaults inside destructured parameters. *args, "
        "**kwargs, rest parameters, ClassVar fields, field() without a default, and the ... "
        "defaults of typing.overload stubs are not defaults."
    ),
    limitations=(
        "Decorator detection is by name: a dataclass created through an alias or a wrapper is "
        "treated as a plain class. attrs, pydantic and NamedTuple field defaults are not "
        "recognized. Abstract method defaults are reported like any other. Class field "
        "initializers in JavaScript (class K { x = 1 }) are not parameters and are not reported."
    ),
    remediation=(
        "Make the parameter required and pass the value at every call site, or give the "
        "function fewer responsibilities. If the value is policy (a timeout, a size), it belongs "
        "in validated configuration that the caller reads; if it is an invariant, name it as a "
        "constant and still pass it. Do not move the default into the body as 'x = x or v'."
    ),
    noncompliant_example="def connect(host, port=5432, timeout=30):\n    ...",
    compliant_example=(
        "def connect(host, port, timeout):\n    ...\n\n"
        "connect(settings.host, settings.port, settings.timeout)"
    ),
)

DEF002 = RuleSpec(
    rule_id="DEF002",
    version="1",
    name="missing mapping/object fallback",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "mapping.get(key, fallback), getattr(obj, name, fallback), obj?.x ?? fallback and "
        "destructuring defaults substitute a value for data that is not there."
    ),
    rationale=(
        "A lookup with a fallback turns a missing key into a plausible value. If the key was "
        "required, the program continues with fabricated data and fails later, somewhere else, "
        "or never. If it was optional, the contract that says so should be explicit (a schema, a "
        "typed optional) rather than a literal at the point of use."
    ),
    guarantees=(
        "Python: m.get(k, v), m.setdefault(k, v), m.pop(k, v) on any receiver, getattr(o, a, v), "
        "and 'm[k] if k in m else v'. The receiver is proven a mapping (exact confidence) when it "
        "is a dict display, a name bound to a dict display or dict/defaultdict/OrderedDict/"
        "Counter/ChainMap call, or a name annotated as dict/Dict/Mapping/MutableMapping (and "
        "relatives) anywhere in the module; otherwise the finding is approximate. m.get(k) with "
        "no fallback is a separate review finding (the implicit None) unless the result is "
        "awaited, compared with None, or the left operand of a reported 'or'. JavaScript: "
        "destructuring defaults in declarations (const {x = v} = o, const [x = v] = a), "
        "obj?.x ?? v, obj.x ?? v, o[k] ?? v, m.get(k) ?? v, their ??= forms, ternaries guarded by "
        "a null/undefined check on a property, and 'k in o ? o[k] : v' / hasOwnProperty / "
        "Object.hasOwn ternaries. Exact when the fallback is a literal, a container of literals, "
        "an UPPER_CASE name, or an empty constructor call; approximate otherwise."
    ),
    limitations=(
        "Method names are matched, not types: session.get(url, params) on an HTTP client is "
        "reported with approximate confidence, and session.get(url) is an approximate review "
        "finding. A bare JavaScript property read (o.x, map.get(k)) is not a finding: every "
        "absent property yields undefined and nothing in the syntax singles it out. Object "
        "spread merging ({...defaults, ...options}) and Object.assign are not recognized. "
        "if-statement branches that assign a default are not inspected; only value-substituting "
        "expressions are."
    ),
    remediation=(
        "Index the mapping (m[k], o.x) so a missing key fails where it is missing, or validate "
        "the data once at its boundary and carry a typed, explicitly optional value from there. "
        "Never add a fallback to make a KeyError go away."
    ),
    noncompliant_example=(
        'timeout = config.get("timeout", 30)\nretries = getattr(opts, "retries", 3)'
    ),
    compliant_example='timeout = config["timeout"]  # validated when the config was loaded',
)

DEF003 = RuleSpec(
    rule_id="DEF003",
    version="1",
    name="truthiness fallback",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "'x or default' / 'x || default' substitute for every falsy value, so 0, '', [], false "
        "and None/null are all replaced alike."
    ),
    rationale=(
        "Truthiness fallbacks conflate 'missing' with 'empty' and 'zero'. A legitimate 0 or '' "
        "is silently replaced by the default, and a missing required value is silently supplied. "
        "Because 'or' is also ordinary Boolean logic, the rule reports only shapes that read as "
        "a value substitution and says how sure it is; by default the finding is review, not "
        "a gate failure."
    ),
    guarantees=(
        "Reported: 'x or v' and 'x || v' outside a Boolean test (not the condition of if/while/"
        "assert/ternary, nor an operand of not/!/and/&&/comparison) when v is a literal, a "
        "container of literals, an UPPER_CASE name or an empty constructor call (exact), or "
        "when the expression is the value of an assignment, declaration, object property or "
        "return and v is any other expression (approximate: it may be a legitimate "
        "alternative). Also 'x ||= v', 'x if x else v' and 'x ? x : v'. Chains report once, on "
        "the whole chain, with the last operand as the fallback. Environment reads on the left "
        "are DEF006 instead."
    ),
    limitations=(
        "'x or v' as a call argument or inside a larger expression is reported only when v is "
        "constant-shaped. Intent is not inferred: 'name or anonymous_label' in an assignment is "
        "approximate even when both are legitimate. Boolean-typed variables are not "
        "distinguished from values."
    ),
    remediation=(
        "Decide what 'missing' means and test for exactly that: 'if x is None' (Python) or "
        "'x === undefined' (JavaScript) at the boundary, then raise or reject. If a falsy value "
        "is legitimate input, the fallback was a bug."
    ),
    noncompliant_example='items = payload.get("items") or []\nconst port = options.port || 8080;',
    compliant_example=(
        'items = payload["items"]\n'
        'if (options.port === undefined) throw new Error("port is required");'
    ),
)

DEF004 = RuleSpec(
    rule_id="DEF004",
    version="1",
    name="nullish fallback",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "'x ?? default' and 'x if x is not None else default' substitute a value for a missing "
        "one; strict mode fails clear substitutions."
    ),
    rationale=(
        "A nullish fallback is the honest form of a default: it replaces exactly 'missing'. It "
        "still decides, at the point of use, that the value was optional and what it should be. "
        "If the value was required, the failure is hidden; if it was optional, that belongs in "
        "the contract, not in an expression."
    ),
    guarantees=(
        "Python: 'x if x is not None else v', 'v if x is None else x' (also == / != None), "
        "where the non-missing branch mentions x. JavaScript: 'x ?? v' and 'x ??= v' with a "
        "plain identifier on the left (a property on the left is DEF002), and ternaries guarded "
        "by x === undefined, x === null, x == null, typeof x === 'undefined' and their "
        "negations. Exact when v is constant-shaped, approximate otherwise. 'None if x is None "
        "else f(x)' and 'x == null ? null : x.y' propagate absence and are not reported; neither "
        "is a ternary whose branches do not mention x (a choice, not a fallback)."
    ),
    limitations=(
        "Fallbacks spelled as if-statements ('if x is None: x = v') are not inspected. Optional "
        "chaining alone (o?.x) is propagation, not a fallback. '?? null' is reported like any "
        "other constant: normalizing undefined to null is still a substitution."
    ),
    remediation=(
        "Treat None/null/undefined as an error at the boundary where the value enters, or make "
        "the optionality explicit in the type and let callers decide. Do not replace the check "
        "with 'or'; that only widens what is swallowed."
    ),
    noncompliant_example=(
        "limit = requested if requested is not None else 100\nconst n = count ?? 0;"
    ),
    compliant_example=(
        'if requested is None:\n    raise ValueError("limit is required")\nlimit = requested'
    ),
)

DEF005 = RuleSpec(
    rule_id="DEF005",
    version="1",
    name="exception-to-default",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A handler that returns a literal, a module-level constant, an empty constructor, or a "
        "helper's literal converts a failure into a value."
    ),
    rationale=(
        "Returning a default from a catch is the purest form of a silent failure: the caller "
        "receives a plausible value and cannot tell that nothing was read, parsed, or fetched. "
        "EXC002 classifies the handler shape; DEF005 names the default and follows the value one "
        "step: a constant bound at module level, or a helper whose body is a single literal "
        "return. The two rules describe one handler, so while DEF005 is active EXC002 does not "
        "also report return_fallback; the handler counts once."
    ),
    guarantees=(
        "Exact: every catch whose body EXC002 classifies as return_fallback (returns nothing, "
        "None/null/undefined, a constant, or a container of constants, possibly after logging), "
        "and a handler returning an empty constructor call (dict(), new Map()). Approximate "
        "(static trace): the one non-logging statement returns a name bound at module level to "
        "a constant-shaped value, an UPPER_CASE name or property not bound in the module, or "
        "calls a module-level function whose body is a single 'return <constant>' (JavaScript: "
        "function declaration, const arrow or function expression, including an expression "
        "body). Promise rejection handlers are covered through their literal body only."
    ),
    limitations=(
        "The trace is one step and module-local: rebinding, imports, methods and nested helpers "
        "are not followed, so 'return self.default()' or 'return imported_constant' is EXC001 "
        "territory only. A handler that computes a value from the exception is not a default to "
        "this rule."
    ),
    remediation=(
        "Let the exception propagate, or convert it into a typed error that carries the cause "
        "(raise X from exc; new Error(msg, { cause: err })). If a missing resource is genuinely "
        "optional, make the absence a first-class value the caller must handle, not a default "
        "shaped like success."
    ),
    noncompliant_example=(
        "try:\n    return json.loads(raw)\nexcept ValueError:\n    return DEFAULT_SETTINGS"
    ),
    compliant_example=(
        "try:\n    return json.loads(raw)\nexcept ValueError as exc:\n"
        "    raise ConfigError(path) from exc"
    ),
)

DEF006 = RuleSpec(
    rule_id="DEF006",
    version="1",
    name="implicit configuration fallback",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "os.getenv('X', value), process.env.X || value and friends decide configuration at the "
        "point of use instead of at a validated configuration boundary."
    ),
    rationale=(
        "An environment fallback in application code means the program runs with a value nobody "
        "configured, and the same variable can carry different defaults in different files. "
        "Configuration is external input: read it once, validate it, fail loudly when it is "
        "missing or malformed, and pass typed values inward."
    ),
    guarantees=(
        "Python (through import os / from os import environ, getenv, with aliases): "
        "os.getenv(k, v), os.getenv(k, default=v), os.environ.get(k, v), os.environ.setdefault(k, "
        "v), os.environ.pop(k, v), 'os.environ[k] if k in os.environ else v', and 'or' / 'is None' "
        "fallbacks whose left operand reads the variable. os.getenv(k) and os.environ.get(k) "
        "with no fallback are review findings (the implicit None) unless compared with None. "
        "JavaScript: process.env.X || v, process.env.X ?? v, process.env['X'] forms, ||= and ??=, "
        "ternaries on a null/undefined check of the read, and const { X = v } = process.env. "
        "Exact when the fallback is constant-shaped, approximate otherwise."
    ),
    limitations=(
        "A bare process.env.X read is not reported (see DEF002). Variables read through a "
        "wrapper (settings.env('X', 3)), dotenv helpers, or a configuration library are not "
        "recognized. The rule does not know where the configuration boundary is: a fallback in "
        "the one module that validates configuration is still reported and must be removed or "
        "suppressed there with a reason."
    ),
    remediation=(
        "Read the variable once at the configuration boundary, require it (os.environ['X'], "
        "or an explicit check that raises), parse and validate it, and pass the typed value to "
        "the code that needs it. Defaults, if any, live in documented configuration files, not "
        "in the code that consumes the value."
    ),
    noncompliant_example=(
        'PORT = int(os.getenv("PORT", "8080"))\nconst host = process.env.HOST || "localhost";'
    ),
    compliant_example=(
        'PORT = parse_port(os.environ["PORT"])  # raises KeyError / ValueError at startup'
    ),
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
    DEF001,
    DEF002,
    DEF003,
    DEF004,
    DEF005,
    DEF006,
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
