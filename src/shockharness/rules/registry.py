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
        "re-raises the caught exception passes this rule. Python context managers: with "
        "contextlib.suppress(T, ...) is a catch of T (exact through either import spelling), "
        "and with M(T, ...) is a catch of T for every M listed in capture_managers (exact "
        "when the import resolves, approximate by bare name when it does not); a manager "
        "with no positional argument that names an exception type is an untyped catch. "
        "Promise handlers given as a reference to a function defined at the top level of the "
        "same module are classified by that function's body; other references are "
        "unresolved. .finally(fn) is never a catch."
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
        "are not flagged. Applies to approved and unapproved catches alike, except that an "
        "approved with contextlib.suppress(T) is not reported: the construct names its discard "
        "and has no handler, so the boundary approved the discard itself; a configured "
        "capture manager keeps the exception for inspection and is 'other'."
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
        "defaults of typing.overload stubs are not defaults. Pydantic models (a class whose "
        "base resolves to pydantic.BaseModel through the imports) are checked like "
        "dataclasses: x: int = v, Field(default=v), Field(v) and Field(default_factory=f) are "
        "reported under dataclass_fields; Field(...), Field() and x: int = ... are required "
        "fields, not defaults."
    ),
    limitations=(
        "Decorator detection is by name: a dataclass created through an alias or a wrapper is "
        "treated as a plain class. attrs and NamedTuple field defaults are not recognized; a "
        "pydantic model whose BaseModel import cannot be resolved is a plain class. "
        "Abstract method defaults are reported like any other. Class field "
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
        "'m[k] if k in m else v', next(iterator, v), and collections.defaultdict(factory) "
        "through any import spelling (import collections as c; c.defaultdict(list)); "
        "d.pop(k), next(it) and defaultdict() with no default are not findings. The receiver "
        "is proven a mapping (exact confidence) when it "
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

COMPLEXITY_REMEDIATION = (
    "Reduce repeated cognitive work rather than the number: hoist validation to one load "
    "step, name a repeated condition as a predicate, separate effects from computation, and "
    "pin behavior with tests before and after. Do not split a function into helpers that "
    "share mutable state or hide a branch behind an early return, a catch or a default; the "
    "graph records the delegation and the metrics stay advisory either way."
)
COMPLEXITY_LIMITATIONS_COMMON = (
    "Advisory: never fails a plain check; in diff/gate a per-unit regression against the base "
    "revision follows gates.complexity_regressions. A unit is a module body, class body, "
    "function, method, lambda or arrow; nested units are measured separately and excluded "
    "from their parent, which lowers the parent's number when code is extracted. Files that "
    "fail to parse have no metrics."
)

CPLX001 = RuleSpec(
    rule_id="CPLX001",
    version="1",
    name="cyclomatic complexity",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="A unit's cyclomatic complexity (convention cyclomatic/1) is above cyclomatic_warn.",
    rationale=(
        "Each decision point is a path a test has to cover and a reader has to follow. The "
        "number is a size of the decision space, not a judgement of correctness, which is why "
        "it is reported as a warning and kept out of the hard gate."
    ),
    guarantees=(
        "Exact on the control tree: 1 + each if/elif/else-if, each loop (comprehension for "
        "clauses included) and comprehension if clause, each except/catch handler, each "
        "non-default match/switch arm, each conditional expression, and, with "
        "cyclomatic_counts_boolean_operators = true, each and/or, &&/||/??, and logical "
        "assignment operator. Optional chaining, finally, try/else and else add nothing. "
        "The message names the value, the threshold and the convention version."
    ),
    limitations=COMPLEXITY_LIMITATIONS_COMMON,
    remediation=COMPLEXITY_REMEDIATION,
    noncompliant_example=(
        "def route(req):            # cyclomatic 17 with cyclomatic_warn = 15\n"
        "    if req.a and req.b: ...\n    elif req.c: ...\n    # ... twelve more branches"
    ),
    compliant_example=(
        "HANDLERS = {'a': handle_a, 'b': handle_b}\n"
        "def route(req):\n    return HANDLERS[req.kind](req)   # each handler measured on its own"
    ),
)

CPLX002 = RuleSpec(
    rule_id="CPLX002",
    version="1",
    name="cognitive complexity",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="A unit's cognitive complexity (convention cognitive/1) is above cognitive_warn.",
    rationale=(
        "Nesting and interrupted flow cost a reader more than a flat sequence of the same "
        "decisions. The convention follows the published description of cognitive complexity "
        "(structural increments, nesting increments, flow interruptions) and is explicitly not "
        "a SonarSource score: nested functions are measured separately here."
    ),
    guarantees=(
        "Exact on the control tree: +1 plus the nesting level for each if, loop, match/switch, "
        "except/catch handler and conditional expression (each raises the nesting level for its "
        "contents); +1 without nesting increment for elif/else-if, else, loop else and try/else; "
        "+1 per maximal run of one short-circuit operator, per logical assignment, per direct "
        "recursive call and per labeled break/continue. try, finally, with and plain blocks add "
        "nothing. Python and JavaScript produce the same number for equivalent constructs."
    ),
    limitations=(
        COMPLEXITY_LIMITATIONS_COMMON
        + " The score is not comparable with tools that include nested functions in their "
        "parent or count operator runs differently."
    ),
    remediation=COMPLEXITY_REMEDIATION,
    noncompliant_example=(
        "for item in items:\n    if item.ok:\n        if item.value:\n"
        "            if valid(item):   # each level costs more than the last\n                ..."
    ),
    compliant_example=(
        "for item in items:\n    if not is_candidate(item):\n        continue\n    process(item)"
    ),
)

CPLX003 = RuleSpec(
    rule_id="CPLX003",
    version="1",
    name="nesting depth",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="A unit's decision nesting depth (convention nesting/1) is above max_nesting_warn.",
    rationale=(
        "Deep nesting means a reader must hold every enclosing condition in mind to understand "
        "one line. It usually marks validation that belongs at a boundary or a loop body that "
        "wants a name."
    ),
    guarantees=(
        "Exact on the control tree: the deepest chain of if (elif/else branches at the depth of "
        "the then branch), loops and comprehension for clauses, match/switch arms, except/catch "
        "handlers and conditional expressions. Parentheses, with blocks, plain blocks, labels, "
        "try bodies, try/else and finally add no depth. A unit without decisions has depth 0."
    ),
    limitations=COMPLEXITY_LIMITATIONS_COMMON,
    remediation=COMPLEXITY_REMEDIATION,
    noncompliant_example=(
        "if a:\n    for x in xs:\n        if b:\n            while c:\n"
        "                if d:   # depth 5 with max_nesting_warn = 4\n                    ..."
    ),
    compliant_example=(
        "if not a:\n    return\nfor x in xs:\n    handle(x, b, c, d)   # handle measured on its own"
    ),
)

CPLX004 = RuleSpec(
    rule_id="CPLX004",
    version="1",
    name="NPath estimate",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A unit's NPath estimate (convention npath/1) is at or above npath_warn, or saturated "
        "at npath_cap."
    ),
    rationale=(
        "Sequential decisions multiply: three independent if statements have eight paths, ten "
        "have a thousand. The estimate counts acyclic paths including infeasible ones, so it "
        "overstates; it is bounded by npath_cap so it can never be mistaken for a measurement "
        "of something the tool did not compute."
    ),
    guarantees=(
        "Computed bottom-up with every intermediate clamped to npath_cap: blocks multiply, an "
        "expression is 1 + its short-circuit operators, if/loop/conditional are (condition - 1) "
        "+ then + else, try is body * try_else + handlers, times finally, match/switch sums its "
        "arms (+1 without a default). A value at or above the cap is reported as >= cap with "
        "saturated = true. No path is ever enumerated."
    ),
    limitations=(
        COMPLEXITY_LIMITATIONS_COMMON
        + " The number is an estimate: infeasible paths are counted, loops count as one branch, "
        "early returns do not prune later paths."
    ),
    remediation=COMPLEXITY_REMEDIATION,
    noncompliant_example=(
        "if a: ...\nif b: ...\nif c: ...\nif d: ...\nif e: ...\nif f: ...\nif g: ...\n"
        "if h: ...   # 256 paths with npath_warn = 200"
    ),
    compliant_example=(
        "settings = load_settings(raw)   # a, b, c validated once\n"
        "render(settings)                # each branch lives where its data is known"
    ),
)

CPLX005 = RuleSpec(
    rule_id="CPLX005",
    version="1",
    name="coupling / cycles",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "Modules import each other in a cycle, or a unit calls more than fan_out_warn distinct "
        "targets."
    ),
    rationale=(
        "An import cycle means neither module can be understood, tested or loaded without the "
        "other. A unit with many distinct call targets changes whenever any of them does. Both "
        "are coupling facts, not correctness verdicts, and both are reported with the "
        "confidence of the edges behind them."
    ),
    guarantees=(
        "Module cycles: strongly connected components of two or more modules over resolved "
        "import edges only (Python absolute and relative imports, JavaScript import/export/"
        "re-export and require with a literal specifier, each resolved to an analyzed file); "
        "one finding per cycle, anchored on the lexically first member at its import into the "
        "cycle (so the fingerprint is stable when unrelated modules are added), naming the "
        "language, the size and up to eight members; the full membership is in "
        "metrics.graph.cycles. In text output Python cycles are listed before JavaScript "
        "cycles: a Python cycle fails at import time, an ES-module cycle is usually resolved "
        "at call time. Fan-out: distinct "
        "targets of resolved and probable call edges (analyzed units plus external symbols; "
        "builtins excluded) above fan_out_warn; unresolved calls are reported in the message "
        "and in metrics.graph but never counted as targets. Shared mutable state (a "
        "module-level mutable binding written from more than one unit) is a note under "
        "metrics.graph.shared_mutable_state, not a finding."
    ),
    limitations=(
        "The call graph is static and best effort: dynamic property calls, getattr/reflection, "
        "callbacks of unknown origin, method calls on values of unknown type and self/this "
        "attributes the class body does not define are unresolved and never guessed as "
        "resolved. Imports of modules outside the analyzed files are external and cannot "
        "close a cycle. Inheritance, decorators that rebind, star imports and runtime "
        "rebinding are not followed. Never fails the gate on its own."
    ),
    remediation=(
        "Break a cycle by moving the shared type or constant into a module both sides import, "
        "not by importing inside a function. Reduce fan-out by giving the unit one job and "
        "passing it data instead of collaborators. Record the before and after graph "
        "(metrics.graph) with the behavior tests."
    ),
    noncompliant_example=(
        "# a.py\nfrom b import helper\n# b.py\nfrom a import shared   # a -> b -> a"
    ),
    compliant_example=(
        "# shared.py\nSHARED = ...\n# a.py\nfrom shared import SHARED\n"
        "# b.py\nfrom shared import SHARED"
    ),
)

CPLX006 = RuleSpec(
    rule_id="CPLX006",
    version="1",
    name="unit size",
    family="complexity",
    config_section="complexity",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A unit's logical line count (convention size/1) is above max_lines_warn; module "
        "bodies are exempt."
    ),
    rationale=(
        "Length is the coarsest complexity signal and the one every code-review standard "
        "checks. The longest units are usually also the ones with the highest cognitive "
        "scores, but a long linear unit with one job is not wrong, which is why this is a "
        "warning that names the count and never fails a plain check."
    ),
    guarantees=(
        "Exact on size/1: the lines of the unit's own span that carry code once comments are "
        "blanked out, minus the lines of units nested inside it (a nested def/class/function "
        "declaration gives up its whole span, a nested lambda or arrow only its interior "
        "lines). Reported when the count is above max_lines_warn. Module bodies are never "
        "reported: a module is a container, and its length is the sum of what it holds. The "
        "count is also in metrics.complexity.functions[].size.logical_lines for every unit."
    ),
    limitations=(
        COMPLEXITY_LIMITATIONS_COMMON
        + " Docstrings and multi-line string literals count as code lines; a table of "
        "constants inside a function counts like any other code."
    ),
    remediation=COMPLEXITY_REMEDIATION,
    noncompliant_example=(
        "def handle(request):        # 80 logical lines with max_lines_warn = 50\n"
        "    # parse, validate, dispatch, format and log, all in one body"
    ),
    compliant_example=(
        "def handle(request):\n    command = parse(request)\n    validate(command)\n"
        "    return render(dispatch(command))   # each step measured on its own"
    ),
)

# --- Verification integrity (H2) ----------------------------------------------------------
# These rules compare two revisions, so they run only under `diff`/`gate --base --head`.
# They ship at `warning` by default (spec 21.1 decision 9: no new rule gates by default
# before its precision is measured); `rules.verification.severity` raises them to
# `error`. Their findings are not suppressible inline (spec 21.1 decision 5).

VERIFICATION_FAMILY = "verification"
VERIFICATION_SECTION = "rules.verification"
VERIFICATION_REMEDIATION_COMMON = (
    "If the change is intended, say why in the review and record it centrally: "
    "rules.verification settings or an [[overrides]] entry for the path or role, which "
    "are visible policy changes. An inline shockharness suppression cannot excuse a "
    "verification finding."
)

VERIFY001 = RuleSpec(
    rule_id="VERIFY001",
    version="1",
    name="added test skip or focus marker",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A change adds a skip, expected-failure or focus marker to a test, taking tests "
        "out of the run while the suite still passes."
    ),
    rationale=(
        "The cheapest way to make a failing suite green is to stop running the failing "
        "test. A skip, an xfail, or an it.only that silently drops every other test all "
        "look like a passing build. Markers that already existed at the base revision are "
        "debt, not findings; a marker this change adds is a decision someone should see."
    ),
    guarantees=(
        "Exact on syntax, in files whose role is test. Python: pytest.mark.skip / skipif / "
        "xfail (also through `from pytest import mark`), unittest.skip / skipIf / "
        "skipUnless / expectedFailure (also imported by name) on a test or test class, a "
        "pytestmark assignment at module or class level, and pytest.skip / pytest.xfail / "
        "self.skipTest called directly in a test body. JavaScript: describe / it / test "
        "with .skip or .only, xdescribe / xit / xtest, fdescribe / fit. A marker counts as "
        "added when its test, kind and text do not occur at the base revision (renames "
        "detected by git are followed)."
    ),
    limitations=(
        "Needs a base revision: under a plain `check` the rule is reported as not "
        "applicable. A skip inside a conditional branch of a test body, a skip applied "
        "through a fixture or a conftest hook, and test-runner configuration that "
        "deselects tests are not seen (VERIFY003, planned, covers configuration). Renaming "
        "a test that already had a marker makes the marker look added. When the base "
        "version of a file could not be analyzed, or rename detection failed, the finding "
        "is unknown."
    ),
    remediation=(
        "Fix or delete the test instead of hiding it. A focus marker (.only, fit) is "
        "almost always a debugging leftover: remove it. For a legitimate platform skip, "
        "give it a reason and list that reason in rules.verification.allowed_skip_reasons. "
        + VERIFICATION_REMEDIATION_COMMON
    ),
    noncompliant_example=(
        '@pytest.mark.skip(reason="flaky")\n'
        "def test_parse(): ...\n"
        'it.only("adds", () => { expect(add(1, 1)).toBe(2); });'
    ),
    compliant_example=(
        '@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals only")\n'
        "def test_sigterm(): ...  # with the reason listed in allowed_skip_reasons"
    ),
)

VERIFY002 = RuleSpec(
    rule_id="VERIFY002",
    version="1",
    name="added blanket suppression",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A change adds a suppression comment that names no rule codes or covers a whole "
        "file, silencing every check of a linter, type checker or coverage tool there."
    ),
    rationale=(
        "A bare # noqa, # type: ignore, // eslint-disable or // @ts-ignore turns off every "
        "present and future check on that line or file, not just the one that fired. It "
        "is how a check is made to pass without anyone deciding that its finding is wrong."
    ),
    guarantees=(
        "Exact on comment syntax, in files of every role except generated and vendor. "
        "Python: # noqa, # ruff: noqa, # flake8: noqa, # type: ignore, # pylint: "
        "disable / disable-next / skip-file, # pragma: no cover / no branch, # mypy: "
        "ignore-errors. JavaScript: eslint-disable, eslint-disable-line, "
        "eslint-disable-next-line, @ts-ignore, @ts-expect-error, @ts-nocheck, istanbul "
        "ignore, c8 / v8 ignore. Both: shockharness: ignore[...]. A directive that names at "
        "least one code (and, for ShockHarness, has a reason) is narrow and is reported "
        "only when rules.verification.report_narrow_suppressions is true; one that names "
        "no codes, names `all`, or covers a file is blanket and always reported. A "
        "directive counts as added when its tool and text do not occur at the base "
        "revision of the file."
    ),
    limitations=(
        "Needs a base revision. Ignore lists in tool configuration files (ruff, eslint, "
        "coverage, pytest) are VERIFY003's, planned for part 2. @ts-expect-error is "
        "classified blanket because it names no code, although TypeScript fails when it "
        "suppresses nothing. A suppression moved to another file looks added."
    ),
    remediation=(
        "Fix what the tool reports, or name the exact codes being silenced "
        "(# noqa: E501, // eslint-disable-next-line no-console) so future problems on "
        "the line still surface. " + VERIFICATION_REMEDIATION_COMMON
    ),
    noncompliant_example="result = compute()  # noqa\n// eslint-disable-next-line",
    compliant_example=(
        "result = compute()  # noqa: E501\n// eslint-disable-next-line no-console -- debug"
    ),
)

VERIFY004 = RuleSpec(
    rule_id="VERIFY004",
    version="1",
    name="neutralized assertions",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A change makes a test unable to fail: it adds an assertion that is always true, "
        "removes every assertion from a test, or replaces a test's body with nothing."
    ),
    rationale=(
        "A test that cannot fail reports success whatever the code does. Replacing "
        "assertions with assert True, deleting them, or emptying the test keeps the test "
        "count and the green build while removing the check."
    ),
    guarantees=(
        "Exact on known patterns, in files whose role is test. Tautologies added: assert "
        "<truthy constant>, assert c == c / c is c on equal constants, self.assertTrue / "
        "assertEqual / assertIs on constants, expect(L).toBe(L) / toEqual / toStrictEqual, "
        "expect(L).toBeTruthy() / toBeFalsy() on a literal of that truthiness, assert(L) / "
        "assert.ok(L), assert.equal / strictEqual / deepEqual / deepStrictEqual(L, L). A "
        "test (matched by qualified name, renames followed) whose assertion count was "
        "above zero at the base revision and is zero at head; a test whose body is only "
        "pass / ... / a docstring / an empty block at head and was not at base."
    ),
    limitations=(
        "Needs a base revision. Known patterns only: an assertion weakened to something "
        "that is merely unlikely to fail (assert len(x) >= 0, a loosened tolerance) is not "
        "judged. Assertions are counted syntactically: assert statements, calls whose name "
        "starts with assert or expect, assert.* methods and pytest.raises / warns blocks; "
        "a test that moved its checks into a helper with another name looks as if it lost "
        "them. A renamed test is not matched to its old name."
    ),
    remediation=(
        "Restore the assertion that was removed or weakened, or delete the test if what it "
        "checked is gone. " + VERIFICATION_REMEDIATION_COMMON
    ),
    noncompliant_example="def test_total():\n    assert True\nexpect(1).toBe(1);",
    compliant_example="def test_total():\n    assert total([1, 2]) == expected_total",
)

VERIFY003 = _planned(
    "VERIFY003",
    "weakened policy, workflow or baseline",
    VERIFICATION_FAMILY,
    VERIFICATION_SECTION,
    SEVERITY_WARNING,
    "Semantic diff of protected paths: lowered thresholds, disabled rules, widened "
    "allowlists, edited baselines, workflow pins and removed jobs (H2 part 2).",
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
    CPLX001,
    CPLX002,
    CPLX003,
    CPLX004,
    CPLX005,
    CPLX006,
    SUPP001,
    SUPP002,
    VERIFY001,
    VERIFY002,
    VERIFY003,
    VERIFY004,
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


# --- Categories (H2, spec 21.1 decision 2) -------------------------------------------------
# Every finding carries the category of its rule's family. Policy-integrity findings are
# hard violations like any other when they gate; the category lets CI and readers tell
# "the code is wrong" from "the checks were weakened" without a separate exit code.
CATEGORY_CONTRACT = "contract_integrity"
CATEGORY_POLICY = "policy_integrity"
CATEGORY_STRUCTURAL = "structural"
CATEGORIES = (CATEGORY_POLICY, CATEGORY_CONTRACT, CATEGORY_STRUCTURAL)
FAMILY_CATEGORIES: dict[str, str] = {
    "magic_numbers": CATEGORY_CONTRACT,
    "magic_strings": CATEGORY_CONTRACT,
    "exceptions": CATEGORY_CONTRACT,
    "defaults": CATEGORY_CONTRACT,
    "suppressions": CATEGORY_CONTRACT,
    "complexity": CATEGORY_STRUCTURAL,
    VERIFICATION_FAMILY: CATEGORY_POLICY,
}


def category_of(rule_id: str) -> str:
    return FAMILY_CATEGORIES[get_rule(rule_id).family]


def needs_base_revision(rule: RuleSpec) -> bool:
    """Rules that compare a head revision with a base revision (diff / gate --base)."""
    return rule.family == VERIFICATION_FAMILY


def base_revision_rules() -> tuple[RuleSpec, ...]:
    """Implemented rules that only run in a revision comparison."""
    return tuple(rule for rule in implemented_rules() if needs_base_revision(rule))
