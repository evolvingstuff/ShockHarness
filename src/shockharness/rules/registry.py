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
TYPESCRIPT = "typescript"  # H-TS: parsed with tree-sitter-typescript, judged by the JS rules
ALL_LANGUAGES = (PYTHON, JAVASCRIPT, TYPESCRIPT)
JAVASCRIPT_FAMILY = frozenset({JAVASCRIPT, TYPESCRIPT})
# G1 (spec 21.1 decision 40): C# for Godot .NET, parsed with tree-sitter-c-sharp. It is
# not in ALL_LANGUAGES: a rule runs on C# only once its family has C# facts and lists it.
CSHARP = "csharp"
SUPPORTED_LANGUAGES = (*ALL_LANGUAGES, CSHARP)
# The rules that run on C#: numbers, unit complexity and suppression comments (G1);
# exceptions, defaults, RESULT001, BOOL001 and STUB001 (G2); dead code, CPLX005 and the
# per-file families of G3 part two.
WITH_CSHARP = SUPPORTED_LANGUAGES
# Languages whose rule coverage is partial: the text report names the rules that do not
# run on them (coverage.rules_not_applicable lists them for every language).
PARTIAL_LANGUAGES = frozenset({CSHARP})


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


MAGIC001 = RuleSpec(
    rule_id="MAGIC001",
    version="1",
    name="numeric literal outside 0/1",
    family="magic_numbers",
    config_section="rules.magic_numbers",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=WITH_CSHARP,
    summary="Every numeric literal in executable code must be exactly 0, 1 or -1.",
    rationale=(
        "A bare number carries no contract: nobody can tell whether 30 is a timeout, a "
        "retry budget, or a protocol code, or why it is 30. A module-level named constant "
        "(REQUEST_TIMEOUT_SECONDS = 30) is the remedy and is not reported (spec 21.1 "
        "decision 36); variable policy still belongs in validated configuration. The "
        "analyzer does not invent exemptions for 2, 10, 24, 60, or any other 'obvious' "
        "number written where it is used."
    ),
    guarantees=(
        "Exact on numeric AST nodes: int, float, complex (Python) and number/bigint "
        "(JavaScript) literals in any encoding (decimal, hex, octal, binary, exponent, "
        "separators). Value-based: 0x1, 1.0, 1e0, 0b0 and 1n pass as 0 or 1. Unary minus "
        "over a literal is checked as one unit: -1 passes while allow_unary_negative_one is "
        "true (the default: items[-1], indexOf(...) === -1); -0 and -0.0 always fail. Python "
        "booleans are never flagged. Numeric literals in Python type annotations are flagged. "
        "A literal that is the whole value of a module-level named constant definition "
        "(MAX_PAGES = 8, const SETTLE_MS = 400, CHUNK_BYTES = 64 * 1024) is not reported "
        "while rules.magic_numbers.named_constant_definitions is 'allow', the default of "
        "every profile since 0.9.0; 'report' is a tightening."
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
        "0, 1 or -1 that carries meaning (an exit code, a sentinel such as 'nothing "
        "selected') deserves a name too, even though the rule permits it."
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
    summary=(
        "A shockharness suppression comment is malformed, names an unknown rule, or lacks a reason."
    ),
    rationale=(
        "A suppression is a policy decision. One that does not name an exact rule and give a "
        "reason is indistinguishable from hiding a violation."
    ),
    guarantees=(
        "Exact: every comment starting with the 'shockharness:' prefix is checked. Under "
        "--no-inline-suppressions, and in a file a suppressions.forbidden entry's paths "
        "match, every suppression comment is reported and suppresses nothing."
    ),
    limitations="Only the single-line form on the same line as the construct is recognized.",
    remediation=(
        'Use the exact form: # shockharness: ignore[RULEID] reason="why this is justified" '
        "(JavaScript: // shockharness: ...). Keep the scope to one line. Where suppressions "
        "are refused, fix the finding instead."
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    version="2",
    name="missing mapping/object fallback",
    family="defaults",
    config_section="rules.defaults",
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=WITH_CSHARP,
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
        "'m[k] if k in m else v' and its statement form ('if k in m: return m[k]' followed by "
        "'return v', or 'if k not in m: return v' followed by 'return m[k]'), next(iterator, v), "
        "and collections.defaultdict(factory) "
        "through any import spelling (import collections as c; c.defaultdict(list)); "
        "d.pop(k), next(it) and defaultdict() with no default are not findings. Not fallbacks "
        "either: a .get(...) call that is itself a decorator (@router.get('/x')); a lookup "
        "with a None fallback (m.get(k), m.get(k, None), m.pop(k, None), getattr(o, a, None)) "
        "assigned to a name whose very next statement is an if without else that only raises "
        "when the name is None, falsy, not callable or not an instance; and "
        "m.setdefault(k, <empty container>) whose result is immediately mutated (.append, "
        ".add, .extend, .update, .insert, .setdefault, or a subscript assignment). "
        "m.pop(k, None) as a statement (its result discarded) is a review finding of kind "
        "discarded_removal: use del if the key is always present. The receiver "
        "is proven a mapping (exact confidence) when it "
        "is a dict display, a name bound to a dict display or dict/defaultdict/OrderedDict/"
        "Counter/ChainMap call, or a name annotated as dict/Dict/Mapping/MutableMapping (and "
        "relatives) anywhere in the module; otherwise the finding is approximate. A call of a "
        "module-level fallback helper of the same file (its body, after a docstring and "
        "checks that only raise, is a lookup whose default is one of its parameters) is "
        "reported at the call, with the argument as the fallback, under the "
        "fallback_helpers mode (review in strict). m.get(k) with "
        "no fallback is a separate review finding (the implicit None) unless the result is "
        "awaited, compared with None, or the left operand of a reported 'or'. JavaScript: "
        "destructuring defaults in declarations (const {x = v} = o, const [x = v] = a), "
        "obj?.x ?? v, obj.x ?? v, o[k] ?? v, m.get(k) ?? v, their ??= forms (except lazy "
        "initialization of an own field, this.x ??= new X() / this.#x ??= new Map(), "
        "see DEF004), ternaries guarded by "
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
        "expressions and the return statement forms are. Fallback helpers are followed within "
        "their own file and by name only (not methods, not imports), and the statement form "
        "is Python only."
    ),
    remediation=(
        "Decide which case this is. (1) The key must exist: index the mapping (m[k], o.x) so a "
        "missing key fails where it is missing, or validate the data once at its boundary. "
        "(2) Absence is a normal state (an empty view has no root entry, an unused tag has no "
        "posting): branch where it matters and do the absent case's own work there ('if tag "
        "not in index: continue'). A helper returning a stand-in is the fallback again, and "
        "one taking the default as a parameter is .get under another name; a stand-in that "
        "really is the meaning gets an inline suppression with the reason. Do not force an "
        "index here; that turns a normal state into a crash. (3) The value comes from outside "
        "(configuration, a request): validate it where it enters and carry a typed, explicitly "
        "optional value from there. Never add a fallback to make a KeyError go away."
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
        "is a ternary whose branches do not mention x (a choice, not a fallback). "
        "Lazy initialization is not a fallback: a field or module variable filled on first "
        "use with a value built for it (new X(...), a call, an empty [] or {}) is left alone: "
        "JavaScript this.x / this.#x ??= v and a module-level let/var not shadowed in an "
        "enclosing function (DEF002 for the field forms); C# _x / this._x ??= v on a "
        "field of the enclosing type that no parameter or local shadows; Python "
        "self.x = self.x if self.x is not None else v (either spelling, self or cls). "
        "A constant (this.timeout ??= 30), a parameter, a local or a parameter's property "
        "is still reported."
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
    languages=WITH_CSHARP,
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
        "shaped like success. Never re-implement a library's validation to avoid "
        "catching its exception (a hand-written date check returning None): raise your own "
        "typed error from the handler (raise InvalidDate(...) from exc). At the entry point, "
        "a named non-zero exit status returned inside a declared boundary is not reported "
        "(decision 37)."
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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
    languages=WITH_CSHARP,
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

VERIFY005 = RuleSpec(
    rule_id="VERIFY005",
    version="1",
    name="stub the code under test no longer reaches",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "A test patches a project function (monkeypatch.setattr, mock.patch, patch.object) "
        "that nothing the test calls reaches any more: the test runs the real code it meant "
        "to stub out, or stubs nothing."
    ),
    rationale=(
        "A refactor moves the work to another function and the old stub keeps the test "
        "green while it runs the real thing: in one project, three tests went on launching "
        "real processes after the code stopped calling the function they stubbed."
    ),
    guarantees=(
        "Python test and config files. A patch is resolved to the project functions it "
        "replaces through the file's imports (monkeypatch.setattr(module, 'name'), "
        "patch.object(Class, 'name')) or the project's module names (patch('pkg.mod.name')). "
        "The tests that run it are the test it is in, the tests that reach the helper it "
        "is in, and the tests that take the fixture it is in as a parameter. Reported when "
        "none of them reaches a replaced function by the dead-code rules' edges (calls, "
        "same-name fallbacks, value references, nesting). Not reported: tripwires, stubs "
        "there to be not called (they raise, call pytest.fail, have an exception as "
        "side_effect, or append to a list the test asserts empty); patches of code outside "
        "the project; patches no test is seen to run. Judged only when the run analyzed "
        "every included file."
    ),
    limitations=(
        "Reachability leans toward reached (a call through any object of the same name "
        "counts), so a stale stub whose name another reached function shares is missed. "
        "Fixtures that other fixtures request are not followed, and code reached only "
        "dynamically (getattr with a computed name, an entry the analysis cannot see) makes "
        "a live stub look stale: suppress it with that reason. A patch of module.name that "
        "the code under test bypasses by importing the name directly is not detected yet."
    ),
    remediation=(
        "Find what the code under test calls now and stub that, or delete the stub if the "
        "test means to run the real code. A stub meant to fail the test if the code ever "
        "calls it should raise or assert, which marks it as a tripwire."
    ),
    noncompliant_example=(
        "monkeypatch.setattr(switcher, 'open_or_launch_namespace', fake)  # no longer called\n"
        "open_all_namespaces()  # now calls _launch_namespace_process"
    ),
    compliant_example="monkeypatch.setattr(switcher, '_launch_namespace_process', fake)",
)


VERIFY006 = RuleSpec(
    rule_id="VERIFY006",
    version="1",
    name="a test file deleted while its code remains",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A change deletes a test file while every project module it imported is still "
        "there: the code keeps running, and the checks on it are gone."
    ),
    rationale=(
        "VERIFY004 sees a test emptied of its assertions, but deleting the whole file leaves "
        "nothing to compare, so the build stays green with less verification. In one "
        "project's history, 26 of the 49 deleted test files that imported project code "
        "left all of it behind; a reviewer should see that the checks went."
    ),
    guarantees=(
        "Needs a base revision. A file whose role at the base was test, analyzed there, that "
        "the head neither has nor renamed (git's rename detection), whose imports resolve, by "
        "the module graph's rules, to at least one analyzed file of the base, all of which "
        "the head still has (or renamed). Reported at the deleted path, line 1. When rename "
        "detection failed the finding is unknown."
    ),
    limitations=(
        "Whether the deletion is deliberate is not known: tests deleted with a redesign, or "
        "by a decision to test another way, are reported too, which is the point of a "
        "review. A test that imported no project module (a helper, a conftest, a test that "
        "loads code by path) is not judged, and a test whose code went in the same change is "
        "not reported. Tests moved into another file look deleted unless git sees a rename."
    ),
    remediation=(
        "Keep the tests, or move them where they now belong, or say in the change why the "
        "code no longer needs them. " + VERIFICATION_REMEDIATION_COMMON
    ),
    noncompliant_example="git rm tests/test_tokens.py  # app/tokens.py stays",
    compliant_example="git mv tests/test_tokens.py tests/auth/test_tokens.py",
)

VERIFY003 = RuleSpec(
    rule_id="VERIFY003",
    version="1",
    name="weakened policy, workflow or baseline",
    family=VERIFICATION_FAMILY,
    config_section=VERIFICATION_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A change loosens the policy that judges it: the ShockHarness configuration, a "
        "baseline, the CI workflow that runs the gate, or another tool's configuration; or "
        "the repository tries to loosen a key the organization's --policy file sets."
    ),
    rationale=(
        "The cheapest way to pass a gate is to move it: disable a rule, raise a threshold, "
        "exclude a directory, add fingerprints to the baseline, mark the CI step "
        "continue-on-error, or ignore a code in ruff. Each of these is a policy decision "
        "that deserves review, and none of them shows up as a code finding."
    ),
    guarantees=(
        "Revision comparison (diff, gate --base --head), with each revision's committed "
        "configuration loaded from its own tree: every policy deviation present at head and "
        "absent at base (list order ignored), looser gate modes, unsupported_sources, "
        "parse_errors, VERIFY or fan-out severity, raised complexity thresholds, patterns "
        "removed from include or added to exclude, and the files the base configuration "
        "analyzes in the head tree that the head configuration does not; baselines "
        "(*baseline*.json) that gained fingerprints; workflow jobs (.github/workflows, "
        "when the analysis root is the repository top level) that ran ShockHarness and were "
        "removed or stopped, or gained continue-on-error: true, if: false, --exit-zero, "
        "--profile minimal|recommended or --parse-errors warn, or an older analyzer pin; "
        "ruff, flake8, pytest, coverage and JSON ESLint settings at the analysis root that "
        "added ignores, deselections or omissions, removed selections or test paths, "
        "lowered fail_under, or turned an ESLint rule down. With --policy, in any run: every "
        "repository key that would loosen a key the policy file sets (the policy's value "
        "applies). In check and the edit hook (spec 21.1 decision 35): every configuration "
        "loosening that switches a rule off (all but a catch boundary naming one file) since "
        "the accepted configuration, which is the merge base with origin/HEAD, else HEAD, else "
        "what init writes. Rule-switching findings take rules.verification.rule_switching_severity "
        "(error by default) in every mode."
    ),
    limitations=(
        "Workflows are read as text, not YAML: flow style, anchors and matrix-generated "
        "jobs are not interpreted, and a renamed job looks removed. Tool configuration is "
        "read only at the analysis root and only from the files listed in docs/rules.md; "
        "flat-config eslint.config.js and YAML .eslintrc are not compared. A change that "
        "makes a configuration invalid at one revision yields an unknown finding. Per-path "
        "[[overrides]] do not apply to VERIFY003; only rules.verification.enabled turns it "
        "off, and the strictest of the run's and the base revision's rules.verification "
        "applies, so a change cannot switch off the rule reporting it. The accepted-configuration "
        "comparison of check and the hook needs git: outside a repository nothing is "
        "compared (coverage.accepted_configuration says so), and any commit accepts a "
        "change, one an agent makes included; a pull request's gate --base is the check "
        "the agent cannot make pass by committing."
    ),
    remediation=(
        "Revert the loosening, or make the policy change deliberately in its own reviewed "
        "change with the reason in the commit message. An agent never switches a rule off "
        "to get past a finding: it undoes the change or asks the user, who accepts it by "
        "committing it. An organization that wants a key "
        "fixed sets it in the --policy file kept outside the repository. "
        + VERIFICATION_REMEDIATION_COMMON
    ),
    noncompliant_example=(
        "[tool.shockharness.rules.magic_numbers]\nenabled = false\n"
        "# .github/workflows/ci.yml\n- run: shockharness gate --base origin/main --head HEAD\n"
        "  continue-on-error: true"
    ),
    compliant_example=(
        "A separate pull request titled 'Policy: allow X in Y because Z' that changes only "
        "the configuration, reviewed by the owners of .shockharness.toml (CODEOWNERS)."
    ),
)


# --- H3: syntax-level guardrails (spec 21.2) -----------------------------------------------
# Each ships at warning (BOOL001 at review) until its precision is measured on a reviewed
# corpus (spec 21.1 decision 9). STUB*, ASSERT001, BOOL001, STATE001 and IMPORT001 apply to
# the file roles listed in their section's `roles` (default: production only).

STUBS_SECTION = "rules.stubs"
ASSERTIONS_SECTION = "rules.assertions"
BOOLEAN_ARGUMENTS_SECTION = "rules.boolean_arguments"
MODULE_STATE_SECTION = "rules.module_state"
IMPORT_EFFECTS_SECTION = "rules.import_effects"
DOM_SECTION = "rules.dom"
GUARDRAIL_SECTIONS = (
    STUBS_SECTION,
    ASSERTIONS_SECTION,
    BOOLEAN_ARGUMENTS_SECTION,
    MODULE_STATE_SECTION,
    IMPORT_EFFECTS_SECTION,
    DOM_SECTION,
)

EXC004 = RuleSpec(
    rule_id="EXC004",
    version="1",
    name="control flow leaves a finally block",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "return, break or continue that leaves a finally block discards the exception in "
        "flight, and the return value or loop step silently replaces it."
    ),
    rationale=(
        "A finally block runs while an exception may be propagating. Leaving it with return, "
        "break or continue cancels that exception: the caller sees an ordinary result. This is "
        "the most silent catch there is, and it needs no except clause at all. CPython 3.14 "
        "warns about it (PEP 765)."
    ),
    guarantees=(
        "Python: return anywhere in a finally block; break/continue not inside a loop of their "
        "own within the block (the else of such a loop counts as outside). JavaScript: return "
        "in a finally clause; unlabeled break not inside a loop or switch of its own, "
        "unlabeled continue not inside a loop of its own, and a labeled break/continue whose "
        "label is not declared inside the clause. Nested functions, lambdas, arrows, methods "
        "and classes are separate scopes. Exact."
    ),
    limitations=(
        "Syntax only: a finally block that calls a function which itself exits the process "
        "or re-raises a different exception is not judged. Exception boundaries do not apply: "
        "there is no exception type to approve."
    ),
    remediation=(
        "Move the return after the try statement, or compute the value in the try and return "
        "it there; keep the finally block to cleanup that cannot fail. If the exception really "
        "must be discarded, catch the specific type in an except clause at a declared boundary "
        "so the decision is visible."
    ),
    noncompliant_example="try:\n    return compute()\nfinally:\n    return DEFAULT",
    compliant_example="try:\n    value = compute()\nfinally:\n    release()\nreturn value",
)

STUB001 = RuleSpec(
    rule_id="STUB001",
    version="1",
    name="placeholder in place of an implementation",
    family="stubs",
    config_section=STUBS_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "Production code that raises NotImplementedError, raises NotImplemented, throws "
        "'not implemented', or is an empty function body ships a stub instead of behavior."
    ),
    rationale=(
        "An agent under pressure to make the code compile or the tests pass writes the "
        "signature and leaves the body for later. The program then fails at run time, in "
        "production, on the first real call, or (for an empty body) silently does nothing."
    ),
    guarantees=(
        "Python: raise NotImplementedError (bare or called), raise NotImplemented (itself a "
        "bug: NotImplemented is not an exception), and a function whose body is only pass, "
        "... and a docstring. Not reported: functions decorated @abstractmethod or @overload, "
        "and every method of a class deriving from ABC or Protocol or using ABCMeta. "
        "JavaScript: throw new XError('...') where the constructor name ends in Error and the "
        "message says not implemented, not yet implemented, unimplemented, or starts with a "
        "TODO marker (TODO in capitals, or todo followed by : or (; not 'Todo toggle "
        "missing', a name). Both: a comment line that opens with one of rules.stubs.markers "
        "(none by default). Only "
        "in files whose role is in rules.stubs.roles (production by default). Exact."
    ),
    limitations=(
        "An abstract API written without ABC, Protocol or @abstractmethod looks like a stub; "
        "declare it abstract. Empty JavaScript functions are not reported (no-op callbacks are "
        "idiomatic). A plausible but fake implementation (return True) is STUB003's, which is "
        "not built yet."
    ),
    remediation=(
        "Implement the behavior, delete the unused entry point, or, if the behavior is "
        "genuinely underspecified, stop and say so. Never replace the stub with a plausible "
        "fake to silence the finding. Make an intentionally abstract method abstract "
        "(@abstractmethod on an ABC, or a Protocol)."
    ),
    noncompliant_example="def refund(order):\n    raise NotImplementedError",
    compliant_example=(
        "class Gateway(ABC):\n    @abstractmethod\n    def refund(self, order): ..."
    ),
)

STUB002 = RuleSpec(
    rule_id="STUB002",
    version="1",
    name="test double imported by production code",
    family="stubs",
    config_section=STUBS_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "Production code imports a mocking or fake-data library, or a module under tests/, "
        "fixtures/ or mocks/: test behavior wired into the shipped program."
    ),
    rationale=(
        "A mock that leaks into production makes the program report success for work it never "
        "did. The import direction is the cheapest place to stop it: production code has no "
        "reason to depend on test code."
    ),
    guarantees=(
        "Every import in a file whose role is in rules.stubs.roles (production by default) "
        "whose module is one of rules.stubs.mock_modules or below it (unittest.mock, "
        "from unittest import mock, @faker-js/faker/locale/en), or whose path has a segment "
        "in rules.stubs.test_path_segments: Python dotted modules (absolute or relative, and "
        "the names of a 'from . import x'), JavaScript relative and absolute specifiers "
        "('./__mocks__/api.js'). Exact."
    ),
    limitations=(
        "Imports are matched by name, not resolved to files: a production package that is "
        "itself named fixtures is reported. A library that deliberately exports test "
        "utilities should mark those files with a test role (file_roles.test) or an override."
    ),
    remediation=(
        "Move the dependency the other way: production code defines an interface, tests "
        "provide the double. If the module is really production code, rename or move it out "
        "of the test directory, or classify the file's role explicitly."
    ),
    noncompliant_example="from tests.fakes import FakePaymentClient\nfrom unittest import mock",
    compliant_example="from payments.client import PaymentClient  # tests inject a fake",
)

ASSERT001 = RuleSpec(
    rule_id="ASSERT001",
    version="2",
    name="assert used to check external input",
    family="assertions",
    config_section=ASSERTIONS_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "An assert whose test depends on external input (a request field, an environment "
        "variable, a command-line argument, a file's or a response's contents): an expected "
        "failure is an error to raise, and python -O removes the assert."
    ),
    rationale=(
        "An assert states an internal invariant: if it fails, the program has a bug, and "
        "stopping loudly at that point is right; asserts are encouraged for that. Input from "
        "outside fails for reasons that are not bugs and deserves a typed error that "
        "survives every build. Version 1 reported every production assert, which pushed "
        "agents to delete invariants; version 2 (decision 28) reports only the misuse."
    ),
    guarantees=(
        "A Python assert in a file whose role is in rules.assertions.roles (production by "
        "default) whose test depends, as INPUT001 follows values (assignments, string "
        "building, calls, and project functions through the call graph up to "
        "rules.input.max_depth crossings), on a rules.input source, a configuration read "
        "(rules.input.python_config_reads, os.environ) or one of "
        "rules.assertions.external_reads (sys.argv, input, open, json.load, requests ...). "
        "No validator cleans a value: assert int(x) > 0 still checks input. With "
        "allow_type_narrowing (the default) an assert that only narrows types is never "
        "reported. An assert on anything else is an internal invariant and is not reported."
    ),
    limitations=(
        "The limitations of INPUT001's value following apply (no attributes, closures or "
        "callbacks). Data from the project's own storage is not external unless a read of it "
        "is listed. JavaScript has no removable assert statement."
    ),
    remediation=(
        "Check the input explicitly where it enters and raise a typed error that names the "
        "problem (if amount <= 0: raise ValueError(...)). Keep asserts for internal "
        "invariants; never delete an assert to satisfy a finding."
    ),
    noncompliant_example='amount = int(request.form["amount"])\nassert amount > 0, "positive"',
    compliant_example=(
        'amount = int(request.form["amount"])\n'
        'if amount <= 0:\n    raise ValueError(f"amount must be positive, got {amount}")'
    ),
)

ASSERT002 = RuleSpec(
    rule_id="ASSERT002",
    version="1",
    name="asserts relied on, optimized runs not refused",
    family="assertions",
    config_section=ASSERTIONS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "Production code checks invariants with assert, and no analyzed code reads "
        "sys.flags.optimize: under python -O or PYTHONOPTIMIZE every one of those checks "
        "disappears."
    ),
    rationale=(
        "Whether asserts run is a property of how the program is started, so it is checked "
        "once, at startup, not at every assert. A project that refuses to run optimized can "
        "rely on its asserts everywhere."
    ),
    guarantees=(
        "One finding per run, at the first assert (by path and line) that is not pure type "
        "narrowing in a file whose role is in rules.assertions.roles, when no analyzed Python "
        "file reads sys.flags.optimize (through import sys or from sys import flags). "
        "Severity rules.assertions.assert002_severity (review by default)."
    ),
    limitations=(
        "Any read of sys.flags.optimize counts as the guard; what the code does with it is "
        "not checked. A run that analyzes only part of the project may not see the guard."
    ),
    remediation=(
        "At the program's entry point, refuse to run optimized: if sys.flags.optimize: "
        "raise SystemExit('this program checks its invariants with assert; do not run it "
        "with python -O'). Do not replace the asserts."
    ),
    noncompliant_example="def head(items):\n    assert items, 'the ordering has a head here'",
    compliant_example=(
        "def main():\n    if sys.flags.optimize:\n"
        "        raise SystemExit('do not run with python -O')"
    ),
)

BOOL001 = RuleSpec(
    rule_id="BOOL001",
    version="1",
    name="positional Boolean argument",
    family="boolean_arguments",
    config_section=BOOLEAN_ARGUMENTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A True/False literal passed positionally to a call with several arguments does not "
        "say what it switches: analyze(path, cfg, None, False)."
    ),
    rationale=(
        "A bare Boolean at a call site is a flag whose meaning lives in another file. It is "
        "easy to pass in the wrong position and impossible to review without opening the "
        "callee."
    ),
    guarantees=(
        "Python: a True/False literal among the positional arguments of a call that has more "
        "than one positional argument and no *args. JavaScript: a true/false literal among "
        "the arguments of a call with more than one argument and no spread. Calls whose last "
        "callee segment is in rules.boolean_arguments.allowed_callees are not reported "
        "(defaults: the lookup functions DEF002 already covers). Only in files whose role is "
        "in rules.boolean_arguments.roles (production by default). Exact."
    ),
    limitations=(
        "The callee is not resolved, so a parameter whose Boolean meaning is obvious from the "
        "function name is reported too; that is why the rule ships at review."
    ),
    remediation=(
        "Pass the flag by keyword (Python) or in a named options object (JavaScript), or "
        "replace the flag with two functions or an enum when it selects behavior."
    ),
    noncompliant_example="render(page, True, False)\nconnect(host, true);",
    compliant_example="render(page, escape=True, cache=False)\nconnect(host, { secure: true });",
)

STATE001 = RuleSpec(
    rule_id="STATE001",
    version="1",
    name="module state written from functions",
    family="module_state",
    config_section=MODULE_STATE_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A module-level mutable binding (a container, a let/var, a name named by global) that "
        "functions assign or mutate is shared state with no owner."
    ),
    rationale=(
        "Module state outlives every call, is shared by every caller and every thread, and "
        "makes the order of calls part of every function's contract. Tests pass one at a "
        "time and fail together."
    ),
    guarantees=(
        "Every module-level binding the analyzer marks mutable (bound to a list, dict, set or "
        "mutable constructor; a JavaScript let/var; a Python name named by a global "
        "statement) that at least one function, method or arrow assigns or mutates, one "
        "finding per binding at its definition, naming the writers. Entries in "
        "[[rules.module_state.allowed]] (path glob, name, reason) are not reported; each is a "
        "policy deviation. Only in files whose role is in rules.module_state.roles. Approximate."
    ),
    limitations=(
        "Per file: writes through another module (other.CACHE.append) and through aliases are "
        "not seen. Module-level code that mutates its own containers while building them is "
        "not a finding."
    ),
    remediation=(
        "Prefer immutable values (the write-compliant-code skill, principle 8): if the "
        "binding is a fixed table, make it a tuple, frozenset or frozen object that nothing "
        "writes. Otherwise give the state an owner: an object created by the caller and "
        "passed in, or a new value returned and threaded through. A deliberate process-wide "
        "cache is declared in [[rules.module_state.allowed]] with its reason (thread safety, "
        "invalidation)."
    ),
    noncompliant_example="_SEEN = set()\n\ndef mark(key):\n    _SEEN.add(key)",
    compliant_example="class Tracker:\n    def __init__(self):\n        self.seen = set()",
)

IMPORT001 = RuleSpec(
    rule_id="IMPORT001",
    version="1",
    name="side effect at import time",
    family="import_effects",
    config_section=IMPORT_EFFECTS_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A process, network request, socket, thread or destructive file operation started "
        "when the module is imported, before any caller asked for it."
    ),
    rationale=(
        "Importing a module should not do anything. An import-time effect runs in every test, "
        "every tool that inspects the package, and every process that merely needs a "
        "constant; it fails or hangs where no one called it."
    ),
    guarantees=(
        "Calls executed at import time (module body, class bodies, decorators and default "
        "values; JavaScript top level, class static blocks and static fields) whose callee, "
        "resolved through the file's own imports, is in rules.import_effects.python_operations "
        "or javascript_operations (subprocess, os.system, socket, threading.Thread, "
        "urllib/requests/httpx requests, asyncio.run, shutil.rmtree, os.remove; "
        "child_process, fetch, fs deletion and writes, net connections, setInterval). Not under "
        "if __name__ == '__main__' or if TYPE_CHECKING. Not in a script run directly: a file "
        "whose first line is a shebang, or one rules.import_effects.script_files matches "
        "(scripts/**, bin/**) that no analyzed file imports; the exemption is listed in "
        "files[].rules_disabled. Only in files whose role is in "
        "rules.import_effects.roles. Exact for the listed operations."
    ),
    limitations=(
        "Only the configured operations are recognized; framework calls with effects "
        "(app.run(), server.listen()) are not, because the receiver's type is not known. "
        "Calls reached through a function called at import time are not followed."
    ),
    remediation=(
        "Move the effect into a function the entry point calls (main(), a factory, an "
        "explicit start()). Keep module bodies to definitions."
    ),
    noncompliant_example="CONFIG = requests.get(CONFIG_URL).json()",
    compliant_example="def load_config(url: str) -> dict:\n    return requests.get(url).json()",
)


# --- H4: async lifecycle (spec 21.2) --------------------------------------------------------

ASYNC_SECTION = "rules.async_lifecycle"

ASYNC001 = RuleSpec(
    rule_id="ASYNC001",
    version="1",
    name="discarded coroutine or Promise",
    family="async_lifecycle",
    config_section=ASYNC_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A coroutine or Promise is created and thrown away: the work may never run (Python) "
        "or finish after the caller has reported success, and its failure is never observed."
    ),
    rationale=(
        "save(record) without await returns before anything is saved, and a rejection "
        "becomes an unhandled-rejection warning in a log, if anything. The caller reports "
        "success for work that did not happen. This is a swallowed exception with no catch."
    ),
    guarantees=(
        "A call that is a whole expression statement (and a JavaScript void call) whose "
        "callee is (a) in rules.async_lifecycle.python_coroutine_apis or "
        "javascript_promise_apis, resolved through the file's own imports (asyncio.sleep, "
        "asyncio.wait_for, fetch, fs/promises functions), or (b) a function or method of the "
        "analyzed project that the call graph resolves to an async def / async function, "
        "across files. A resolved edge is a violation; a probable edge (matched by name "
        "only) is unknown. void is not treated as handling the Promise."
    ),
    limitations=(
        "Without type information an arbitrary call is not assumed to return a Promise: a "
        "library call not in the catalog, a callback, or a method on an object of unknown "
        "type is not reported. A Promise stored in a variable and never awaited is not "
        "tracked."
    ),
    remediation=(
        "await it, return it, or hand it to an owner that observes its failure (a TaskGroup, "
        "Promise.all whose result is awaited). A JavaScript entry point that must not "
        "await (main() at the top level) handles the rejection explicitly: "
        "main().catch((error) => { console.error(error); process.exitCode = 1; })."
    ),
    noncompliant_example=(
        "async def handler(record):\n    save(record)  # save is async\n    return OK"
    ),
    compliant_example="async def handler(record):\n    await save(record)\n    return OK",
)

ASYNC002 = RuleSpec(
    rule_id="ASYNC002",
    version="1",
    name="task started without an owner",
    family="async_lifecycle",
    config_section=ASYNC_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "asyncio.create_task(...) or ensure_future(...) as a statement drops the task's "
        "handle: nothing awaits it, keeps it alive or retrieves its exception."
    ),
    rationale=(
        "The event loop keeps only a weak reference to a task: a dropped task can be "
        "garbage-collected mid-flight, and an exception in it surfaces, if ever, as 'Task "
        "exception was never retrieved' long after the request that started it returned."
    ),
    guarantees=(
        "A call statement whose last callee segment is create_task or ensure_future "
        "(asyncio.create_task, loop.create_task, ...), unless its receiver was bound in the "
        "same function by a with/async with whose manager is in "
        "rules.async_lifecycle.supervisors (asyncio.TaskGroup, anyio.create_task_group, "
        "trio.open_nursery). Exact for asyncio.*, approximate for other receivers."
    ),
    limitations=(
        "A task kept elsewhere (added to a set, given a done-callback) is not reported, "
        "because its handle is not dropped; whether that owner observes failures is not "
        "checked. Framework background-job queues are not modeled."
    ),
    remediation=(
        "Start the task inside a TaskGroup (async with asyncio.TaskGroup() as group: "
        "group.create_task(...)), or keep the handle and await it, or keep it in an owner "
        "that awaits or cancels it and logs its exception."
    ),
    noncompliant_example="asyncio.create_task(notify(user))\nreturn OK",
    compliant_example=(
        "async with asyncio.TaskGroup() as group:\n    group.create_task(notify(user))"
    ),
)

ASYNC004 = RuleSpec(
    rule_id="ASYNC004",
    version="1",
    name="command waits on the page being drawn",
    family="async_lifecycle",
    config_section=ASYNC_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(JAVASCRIPT, TYPESCRIPT),
    summary=(
        "Code a gated command runs awaits an animation's .finished: a page that is not "
        "drawn may never settle it, and every later command waits behind the gate."
    ),
    rationale=(
        "A browser does not run animations for a page it does not draw (a background tab, a "
        "minimized window), so their .finished promises stay pending until the page is "
        "shown. A command that awaits one holds its gate (a command queue, a lock) the whole "
        "time, and nothing after it runs: the page looks frozen. From an app where every "
        "navigation awaited its slide animation inside the command queue."
    ),
    guarantees=(
        "JavaScript and TypeScript. A drawn wait is an await or return (or an arrow's "
        "expression body) of .finished, of a const the function bound to it, of .then / "
        ".catch / .finally on it, or of Promise.all / race / allSettled / any over an array "
        "holding one or a .map whose callback returns one. A function waits on the page when "
        "it has a drawn wait, or awaits or returns a call (resolved through the call graph) "
        "of a function that does. Gates: rules.async_lifecycle.gates, 'callee:index' with "
        "the callback's argument index or 'last' (navigator.locks.request:last by default; "
        "a project adds its own, CommandQueue.run:1). One finding at each drawn wait that a "
        "gate's callback reaches, naming every command that reaches it (the gate call's "
        "first argument) and where; approximate when a step was a probable call-graph edge."
    ),
    limitations=(
        "The callback must be written at the gate call (an arrow or a function); a named "
        "function passed as the callback is not followed. Calls are followed through await "
        "and return only: a promise kept in a variable and awaited later, or passed to "
        "another function, is not. A gate is matched by its callee as written. "
        "requestAnimationFrame and transitionend wrapped in a promise are not recognized."
    ),
    remediation=(
        "Do not hold the gate while the page draws: let the command return and let the "
        "animation finish on its own (handle its rejection with .catch: .finished rejects "
        "when the animation is cancelled), or skip the animation when document.hidden. "
        "Await only work that does not depend on the page being drawn."
    ),
    noncompliant_example=(
        "CommandQueue.run('nav', async () => {\n"
        "  await Promise.all(el.getAnimations().map((a) => a.finished));\n"
        "});"
    ),
    compliant_example=(
        "CommandQueue.run('nav', async () => {\n"
        "  Promise.all(el.getAnimations().map((a) => a.finished))\n"
        "    .then(cleanUp)\n"
        "    .catch(reportError);\n"
        "});"
    ),
)

ASYNC003 = RuleSpec(
    rule_id="ASYNC003",
    version="1",
    name="settled batch whose failures are not inspected",
    family="async_lifecycle",
    config_section=ASYNC_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "asyncio.gather(..., return_exceptions=True) and Promise.allSettled turn failures "
        "into values; thrown away or never checked, every failure in the batch disappears."
    ),
    rationale=(
        "These APIs exist so that one failure does not hide the others. Used without looking "
        "at the results, they hide all of them, and the batch reports success."
    ),
    guarantees=(
        "Python: a call whose last callee segment is gather with return_exceptions=True; "
        "JavaScript: Promise.allSettled(...). Reported when the result is thrown away (an "
        "expression statement, awaited or not; exact), or when the enclosing function "
        "neither returns the batch nor inspects a result for failure (Python: an isinstance "
        "check against a type whose name contains Exception or Error; JavaScript: .status, "
        ".reason or a 'rejected' string; approximate). Not reported: a Python gather in a "
        "finally / except block of a function that called .cancel() before it (the wait for "
        "cancellation to finish)."
    ),
    limitations=(
        "Inspection is recognized anywhere in the enclosing function, not traced to the "
        "batch's own results; a helper that inspects the results in another function is not "
        "followed."
    ),
    remediation=(
        "Check every result: raise or report the failures (isinstance(result, Exception); "
        "result.status === 'rejected'), or use gather / Promise.all without the setting if "
        "the first failure should fail the batch."
    ),
    noncompliant_example="await asyncio.gather(*jobs, return_exceptions=True)",
    compliant_example=(
        "results = await asyncio.gather(*jobs, return_exceptions=True)\n"
        "failures = [r for r in results if isinstance(r, Exception)]\n"
        "if failures:\n    raise ExceptionGroup('jobs failed', failures)"
    ),
)


# --- H5: API-catalog rules (spec 21.2) ------------------------------------------------------
# Advisory until measured (decision 9): warning, or review where the pattern is often
# deliberate (TYPE001, SLEEP001, STUB003). Each section's `roles` scopes its rules.

PROCESSES_SECTION = "rules.processes"
RESULTS_SECTION = "rules.results"
TYPES_SECTION = "rules.types"
SLEEP_SECTION = "rules.sleep"
RETRY_SECTION = "rules.retry"
BATCHES_SECTION = "rules.batches"
CATALOG_SECTIONS = (
    PROCESSES_SECTION,
    RESULTS_SECTION,
    TYPES_SECTION,
    SLEEP_SECTION,
    RETRY_SECTION,
    BATCHES_SECTION,
)

PROCESS001 = RuleSpec(
    rule_id="PROCESS001",
    version="1",
    name="shell command from data, or exit status ignored",
    family="processes",
    config_section=PROCESSES_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A shell command built from data (an injection waiting for the right value), or a "
        "process API that returns its exit status with nothing checking it (a failed "
        "command reads as success)."
    ),
    rationale=(
        "subprocess.run(cmd) without check=True and os.system(...) return a status code; "
        "dropped, the program continues after the command failed. A command string built "
        "from a variable and run through a shell executes whatever shell syntax the value "
        "contains."
    ),
    guarantees=(
        "Calls whose callee, resolved through the file's imports, is in "
        "rules.processes.python_process_apis / javascript_process_apis. Reported: a command "
        "built from non-literal parts (an f-string or template with substitutions, + or % "
        "with a non-literal, .format) run through a shell (shell=True, {shell: true}, "
        "os.system, os.popen, subprocess.getoutput, child_process.exec / execSync); and "
        "subprocess.run without check=True, subprocess.call or child_process.spawnSync whose "
        "result is thrown away or whose function never reads .returncode / .status, and "
        "os.system whose result is thrown away; a result returned to the caller (directly or "
        "through a returned name) is the caller's to check. Exact."
    ),
    limitations=(
        "Whether a non-literal value can contain shell syntax is not traced (that is H6's "
        "taint analysis); a status read anywhere in the function counts as checking it. "
        "Popen and child_process.spawn (event-based) are not judged for their exit status."
    ),
    remediation=(
        "Pass an argument list without a shell (subprocess.run([...], check=True); "
        "execFile / spawnSync with an array). Use check=True, or read the status and raise "
        "a typed error on failure."
    ),
    noncompliant_example='subprocess.run(f"rm -rf {path}", shell=True)',
    compliant_example='subprocess.run(["rm", "-rf", "--", path], check=True)',
)

RESULT001 = RuleSpec(
    rule_id="RESULT001",
    version="1",
    name="must-use result thrown away",
    family="results",
    config_section=RESULTS_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A call that returns a new value and changes nothing is used as a statement: "
        "name.strip(), sorted(items), items.map(f). The line has no effect."
    ),
    rationale=(
        "The author meant to change the value and the code does not. Tests that check the "
        "unchanged value pass by accident or never notice."
    ),
    guarantees=(
        "A call that is a whole statement whose callee is listed in "
        "rules.results.python_must_use / javascript_must_use / csharp_must_use: a "
        "qualified function "
        "(sorted, copy.deepcopy, dataclasses.replace; structuredClone) is exact; an entry "
        "starting with '.' names a method on any receiver (.strip, .replace, .lower; .map, "
        ".filter, .concat, .slice, .trim, .toSorted) and is approximate, because the "
        "receiver's type is not known."
    ),
    limitations=(
        "A method matched by name on a receiver of another type (a custom .replace that "
        "mutates) is reported. Values stored and never read are not tracked."
    ),
    remediation=(
        "Use the result (name = name.strip()), call the mutating form (items.sort(), "
        "forEach), or delete the line if the call was not needed."
    ),
    noncompliant_example="name.strip()\nitems.map((item) => item.id);",
    compliant_example="name = name.strip()\nconst ids = items.map((item) => item.id);",
)

TYPE001 = RuleSpec(
    rule_id="TYPE001",
    version="1",
    name="type escape hatch",
    family="types",
    config_section=TYPES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(PYTHON, TYPESCRIPT, CSHARP),
    summary=(
        "Any, typing.cast and # type: ignore (Python); any, as/<T> assertions, non-null ! and "
        "@ts-ignore (TypeScript); dynamic, the null-forgiving x!, #nullable disable and "
        "#pragma warning disable of a nullable warning (C#) switch the type checker off for a "
        "value, a line or a region; each is a claim nobody checks."
    ),
    rationale=(
        "An agent that cannot satisfy the type checker can make it stop looking. Each escape "
        "hatch is sometimes right (a boundary with runtime validation), and always worth a "
        "reviewer's glance."
    ),
    guarantees=(
        "Python: Any (bare or typing.Any) in a parameter, return or annotated-assignment "
        "annotation; cast(...) and typing.cast(...); every # type: ignore comment. Each "
        "kind can be switched off (report_any, report_cast, report_type_ignore). TypeScript: "
        "the any type anywhere; x as T and <T>x (not as const; x as unknown as T is reported "
        "once); the non-null assertion x! (report_non_null); @ts-ignore, @ts-expect-error and "
        "@ts-nocheck (report_type_ignore). C# (G4): dynamic where a type is written "
        "(report_any); the null-forgiving operator x! (report_non_null); #nullable disable, "
        "and #pragma warning disable naming a nullable warning (CS86xx, CS87xx) or no code "
        "at all (report_type_ignore). Exact on the syntax."
    ),
    limitations=(
        "Type checking itself stays with mypy, pyright or tsc; ShockHarness only lists the "
        "escapes. Plain JavaScript has no types, so TYPE001 does not apply to it. A C# cast "
        "is checked at run time and is not an escape; a pragma's code range is approximate. A "
        "deliberate boundary is excluded with an [[overrides]] entry."
    ),
    remediation=(
        "Name the real type, validate at the boundary and return a typed value, or narrow "
        "with isinstance; keep the escape only where a runtime check backs it, and say so."
    ),
    noncompliant_example="def load(raw: Any) -> Any:\n    return cast(Config, raw)",
    compliant_example="def load(raw: object) -> Config:\n    return Config.parse(raw)",
)


TYPE002 = RuleSpec(
    rule_id="TYPE002",
    version="1",
    name="type annotations nothing checks",
    family="types",
    config_section=TYPES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(PYTHON, CSHARP),
    summary=(
        "Most production functions carry type annotations and no Python type checker is "
        "configured: one finding per run (spec 21.1 decision 33). C#: a project whose "
        "nullable reference types are off, so the compiler checks no null (decision 52)."
    ),
    rationale=(
        "An annotation is a claim. Without a checker nothing verifies it, so a wrong one "
        "reads as true to the next reader and to an agent; one project was 96% annotated "
        "with no checker configured."
    ),
    guarantees=(
        "Reported when at least rules.types.annotated_share (0.5) of the functions and "
        "methods where the rule applies, and at least rules.types.min_annotated_functions "
        "(20) of them, carry an annotation (a parameter other than "
        "self/cls, or the return) and the analysis root configures no checker: mypy.ini, "
        ".mypy.ini, pyrightconfig.json, .pyre_configuration, ty.toml, a [tool.mypy], "
        "[tool.pyright], [tool.basedpyright], [tool.pyre] or [tool.ty] table in "
        "pyproject.toml, or [mypy] in setup.cfg or tox.ini. Severity "
        "rules.types.type002_severity (review by default). C#: each *.csproj under the "
        "analysis root that has C# files where the rule applies, when neither it nor the "
        "Directory.Build.props above it sets <Nullable> to enable or warnings; one finding "
        "per project, at line 1 of its first C# file, naming the project file."
    ),
    limitations=(
        "Configuration only: a configured checker that CI never runs is not seen, and a "
        "checker configured outside the analysis root (a parent directory, a command line) "
        "is not either. TypeScript is not covered: a TypeScript project that builds has a "
        "tsconfig.json. C#: MSBuild is not evaluated (conditions, imports and $(...) are "
        "not followed), and files that turn null checking on themselves (#nullable enable) "
        "are not counted; C# files with no project file above them are not judged."
    ),
    remediation=(
        "Configure the checker and run it in CI (mypy or pyright with the project's own "
        "settings). Annotations a project does not mean to "
        "check are better left out than left unverified."
    ),
    noncompliant_example="def total(items: list[Item]) -> int:  # no [tool.mypy], no mypy.ini",
    compliant_example="[tool.mypy]\nstrict = true  # pyproject.toml, and mypy runs in CI",
)

SLEEP001 = RuleSpec(
    rule_id="SLEEP001",
    version="2",
    name="fixed sleep instead of a condition",
    family="sleep",
    config_section=SLEEP_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "time.sleep / asyncio.sleep / an awaited setTimeout waits a fixed time where the "
        "code needs a condition: too short and it races, too long and it is slow."
    ),
    rationale=(
        "Sleeping is how flaky synchronization gets fixed until it breaks again. A sleep in a "
        "loop is polling; a single sleep is usually waiting for something that has a signal."
    ),
    guarantees=(
        "Python: calls resolved to rules.sleep.python_sleep_apis (time.sleep, asyncio.sleep, "
        "trio.sleep, anyio.sleep); JavaScript: new Promise((r) => setTimeout(r, ...)) and an "
        "awaited timers/promises setTimeout. The message says whether it is in a loop. A delay "
        "that is a literal 0 or left out (await asyncio.sleep(0), setTimeout(resolve)) is a "
        "yield to the event loop, not a wait, and is not reported (version 2). Approximate: a "
        "sleep may be legitimate pacing or rate limiting, hence review."
    ),
    limitations=(
        "Intent is not inferred. Rate limiting and backoff written as a sleep are reported "
        "like synchronization."
    ),
    remediation=(
        "Wait on the condition (an event, a future, a readiness probe with a deadline), or "
        "name the pacing policy and take its interval from configuration."
    ),
    noncompliant_example="start_server()\ntime.sleep(PAUSE)  # hope it is up",
    compliant_example=(
        "start_server()\nwait_until_ready(server, deadline=settings.startup_deadline)"
    ),
)

RETRY001 = RuleSpec(
    rule_id="RETRY001",
    version="1",
    name="retry without a limit",
    family="retry",
    config_section=RETRY_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A retry with no stop condition: a permanent failure retries forever and the "
        "caller never hears about it."
    ),
    rationale=(
        "Retrying is how transient failures are hidden; without a limit it hides permanent "
        "ones too, and the process spins instead of failing."
    ),
    guarantees=(
        "while True / while (true) / for (;;) whose body catches an exception in a handler "
        "that never raises, returns or breaks; decorators resolved to "
        "rules.retry.retry_decorators (tenacity.retry, retrying.retry, backoff.on_exception, "
        "backoff.on_predicate) used without stop / stop_max_attempt_number / tries / "
        "attempts / max_attempts (tenacity, retrying) or max_tries / max_time (backoff). "
        "Exact."
    ),
    limitations=(
        "A limit enforced elsewhere (a timeout around the loop, a counter checked outside the "
        "handler) is not seen; a handler that raises on any path counts as bounded."
    ),
    remediation=(
        "Bound the retries (stop_after_attempt, max_tries, a counter that raises), retry only "
        "the failures that can be transient, and re-raise the last error when giving up."
    ),
    noncompliant_example="@tenacity.retry\ndef fetch(url): ...",
    compliant_example=(
        "@tenacity.retry(stop=tenacity.stop_after_attempt(settings.attempts))\ndef fetch(url): ..."
    ),
)

BATCH001 = RuleSpec(
    rule_id="BATCH001",
    version="1",
    name="batch drops per-item failures",
    family="batches",
    config_section=BATCHES_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A loop catches each item's failure and only passes, continues or logs: the batch "
        "finishes 'successfully' with items silently missing."
    ),
    rationale=(
        "Per-item error handling is how one bad record stops failing a whole import. Done "
        "without recording the failures, it is how a whole import fails without anyone "
        "knowing."
    ),
    guarantees=(
        "A for / for...of / for...in loop whose body (outside nested functions and loops) "
        "has a try whose handler contains only pass, continue, logging calls "
        "(logger.*, logging.*, print; console.*), or nothing. Approximate: whether the "
        "caller learns of the failures elsewhere is not traced."
    ),
    limitations=(
        "A handler that records the failure in a list, or re-raises after the loop, is not "
        "reported; whether that record is ever reported is not checked. The catch itself is "
        "also judged by EXC001/EXC002."
    ),
    remediation=(
        "Collect the failures and return them with the results (a partial-success result), "
        "or raise after the loop when any item failed."
    ),
    noncompliant_example=(
        "for row in rows:\n    try:\n        save(row)\n    except ValueError:\n"
        "        log.warning('skip')"
    ),
    compliant_example=(
        "failures = []\nfor row in rows:\n    try:\n        save(row)\n"
        "    except ValueError as error:\n        failures.append((row, error))\n"
        "return ImportResult(saved, failures)"
    ),
)

STUB003 = RuleSpec(
    rule_id="STUB003",
    version="1",
    name="check that always answers yes",
    family="stubs",
    config_section="rules.stubs",
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A function named as a check (is_admin, can_edit, validate_token) whose whole body "
        "returns True: a success-shaped placeholder."
    ),
    rationale=(
        "The most dangerous stub compiles, passes every test that expects access, and grants "
        "everything. A real check rarely has no inputs that matter."
    ),
    guarantees=(
        "Python and JavaScript functions, methods and arrows named is_/has_/can_/should_ "
        "(isX/hasX/... in JavaScript) or starting with check, validate, verify, authorize, "
        "authenticate or allow, whose body (docstring aside) is only return True / return "
        "true / => true. Severity rules.stubs.stub003_severity (review by default). "
        "Approximate: a feature flag that is deliberately always on looks the same."
    ),
    limitations="Other success-shaped constants (return {} from a fetch) are not judged.",
    remediation=(
        "Implement the check, or delete it and make callers decide; a deliberate constant "
        "(a flag that is always on) becomes a named setting."
    ),
    noncompliant_example="def can_refund(user, order):\n    return True",
    compliant_example=(
        "def can_refund(user, order):\n    return user.id == order.owner_id and order.refundable"
    ),
)


# --- ROLE001: is shielded code really a test? (spec 21.1 decision 24) ----------------------

ROLE_INTEGRITY_SECTION = "rules.role_integrity"
ROLE_INTEGRITY_FAMILY = "role_integrity"

ROLE001 = RuleSpec(
    rule_id="ROLE001",
    version="1",
    name="test role that does not hold",
    family=ROLE_INTEGRITY_FAMILY,
    config_section=ROLE_INTEGRITY_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A file classified as a test is imported by production code (so it ships, yet the "
        "production rules do not apply to it), or contains no test cases at all."
    ),
    rationale=(
        "The test role switches rules off: STUB, ASSERT, BOOL, STATE and IMPORT apply to "
        "production files only. Classifying a file as a test is therefore an exemption, and "
        "the cheapest way to shield code is to move it under tests/ or widen the test globs. "
        "Test code is a dead end: test runners import it, production code never does."
    ),
    guarantees=(
        "An import, resolved through the cross-file module graph, from a production-role file "
        "to a test-role file: exact, at the import. A test-role file whose verification facts "
        "hold no test case (test_* functions and methods; describe/it/test calls) and that "
        "matches none of rules.role_integrity.support_files (conftest, fixtures, helpers, "
        "mocks, __init__.py, ...): reported at rules.role_integrity.empty_test_severity "
        "(review by default). In a revision diff, a file the base revision classified as "
        "production that the head classifies as test (re-globbed or renamed under tests/) is "
        "a VERIFY003 finding."
    ),
    limitations=(
        "Only resolved module edges count; an import the graph cannot resolve (dynamic, "
        "through a package re-export it does not follow) is not seen. A helper that only "
        "tests import but that holds real logic is not judged."
    ),
    remediation=(
        "Move the shared code out of the test tree into production (where the rules apply), "
        "or stop importing it from production. A test file without tests is either support "
        "code (add it to support_files, a reviewed deviation) or should not be classified as "
        "a test."
    ),
    noncompliant_example=(
        "# src/app/payments.py\nfrom tests.helpers import charge  # shipped code under tests/"
    ),
    compliant_example="# src/app/payments.py\nfrom app.billing import charge",
)


# --- H6: external input (spec 21.2, decision 26) ------------------------------------------
# Advisory until measured (decision 9). The facts are each unit's value dependencies
# (ir/*_dataflow.py); the catalogs of rules.input decide what is a source, a sink, a
# validator or an optional configuration read.

INPUT_SECTION = "rules.input"
INPUT_FAMILY = "input"

INPUT001 = RuleSpec(
    rule_id="INPUT001",
    version="1",
    name="external input reaches a sink unvalidated",
    family=INPUT_FAMILY,
    config_section=INPUT_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A value from outside the program (request parameters, bodies, headers and cookies "
        "by default) reaches a shell, eval, deserialization, a file path, a query, a "
        "redirect or an outbound URL without passing a validator."
    ),
    rationale=(
        "An agent wiring a request field straight into a privileged operation produces code "
        "that works on every test input and fails on the first hostile one. Validation is "
        "context-specific; this rule only asks that some recognized validator stands between "
        "the source and the sink."
    ),
    guarantees=(
        "Sources, sinks (callee and argument position) and validators come from "
        "rules.input's catalogs, resolved through the file's imports; a dotted entry "
        "(request.GET, req.body) also matches a read rooted at a parameter of that name "
        "(approximate). Values are followed through assignments, attribute and subscript "
        "reads, string building, containers and calls that are not validators, inside a "
        "function in source order (a value validated on one branch only stays tainted), and "
        "across project functions through the call graph's resolved and probable sites: "
        "arguments into parameters and return values back, up to rules.input.max_depth "
        "function boundaries. One finding per sink and source, at the sink, with the source "
        "and the functions crossed. Exact when the source, every crossing and the sink are "
        "resolved; approximate otherwise."
    ),
    limitations=(
        "No path sensitivity and no guards: `if not cmd.isalnum(): raise` before the sink does "
        "not count; use a validator from the catalog or add the project's own. Values stored "
        "on objects (self.x = ...) or in module state, closures, callbacks and dynamic calls "
        "are not followed. A validator is trusted for every sink."
    ),
    remediation=(
        "Parse the input into the type the operation needs at the boundary (a model, a schema, "
        "int(...), an allowlist lookup), pass the parsed value on, and never build commands, "
        "queries or paths from raw input: pass argument lists, query parameters and "
        "base-relative paths. If the project has its own validator, list it in "
        "rules.input.python_validators / javascript_validators."
    ),
    noncompliant_example=(
        'cmd = request.args["cmd"]\nsubprocess.run(f"convert {cmd}", shell=True)'
    ),
    compliant_example=(
        'size = int(request.args["size"])\nsubprocess.run(["convert", "-resize", str(size)])'
    ),
)

INPUT002 = RuleSpec(
    rule_id="INPUT002",
    version="1",
    name="required configuration read as optional",
    family=INPUT_FAMILY,
    config_section=INPUT_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "os.getenv('X') / os.environ.get('X') (None when unset) or process.env.X (undefined "
        "when unset) is passed on, returned or stored without the function ever checking it."
    ),
    rationale=(
        "A missing variable then travels as a value: a connection string 'None', a port "
        "NaN, a URL ending in 'undefined'. The program starts and fails later, far from the "
        "cause. Required configuration should fail at startup."
    ),
    guarantees=(
        "A read from rules.input.python_config_reads (a call with the variable name only) or "
        "javascript_config_reads (process.env.X, process.env['X']) whose value, followed "
        "inside the function as for INPUT001, reaches a call argument, a return, an attribute "
        "or a module-level binding, while no condition of the function looks at it (if, "
        "while, assert, a ternary, &&, ||, ??, not / !). One finding per read, at its first "
        "use. Python's int(...) / float(...) and the other validators fail loudly on None and "
        "count as a check; in JavaScript, Number(undefined) is NaN and does not, while a "
        "node:assert call given the value (through nested calls) does. Severity "
        "rules.input.input002_severity (review by default: the rule cannot know which "
        "variables are required)."
    ),
    limitations=(
        "A variable that is optional by design is reported all the same. A check in another "
        "function (a later validate_config()) is not seen. A read with a "
        "fallback is DEF006's; a Python read used on its own line is DEF006's too (INPUT002 "
        "reports only uses on another line)."
    ),
    remediation=(
        "Require the variable where configuration is loaded: os.environ['X'] (KeyError), or "
        "read it, check it and raise with the variable's name; then pass the checked value "
        "inward."
    ),
    noncompliant_example="const url = process.env.DATABASE_URL;\nexport const db = connect(url);",
    compliant_example=(
        "const url = process.env.DATABASE_URL;\n"
        'if (!url) { throw new Error("DATABASE_URL is required"); }\n'
        "export const db = connect(url);"
    ),
)

# --- H6 part two: cross-site consistency (decisions 20, 21, 29) ---------------------------

CONSISTENCY_SECTION = "rules.consistency"
CONSISTENCY_FAMILY = "consistency"
DATAFLOW_SECTIONS = (INPUT_SECTION, CONSISTENCY_SECTION)

PROV001 = RuleSpec(
    rule_id="PROV001",
    version="1",
    name="made-up identifier where identifiers are issued",
    family=CONSISTENCY_FAMILY,
    config_section=CONSISTENCY_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A function's parameter is filled with an identifier the program issued "
        "(store.start_run(), createSession()) at some call sites and with a freshly made one "
        "(uuid4(), crypto.randomUUID()) at another: the made-up identifier names nothing the "
        "program knows."
    ),
    rationale=(
        "An agent that does not find where an identifier comes from invents one: the call "
        "type-checks and runs, and the record it refers to does not exist. The other call "
        "sites already show where the identifier should come from."
    ),
    guarantees=(
        "Call sites of one project function, resolved through the call graph (resolved and "
        "probable sites, in files whose role is in rules.consistency.roles). An argument is "
        "issued when its value comes, as INPUT001 follows values (attributes, str(...), "
        "helper functions up to rules.input.max_depth crossings), from a call whose name "
        "opens with one of rules.consistency.issuer_prefixes (start, create, new, register, "
        "open, begin, issue, allocate, insert); fabricated when it comes from "
        "rules.consistency.python_fabricators / javascript_fabricators (uuid.uuid4, "
        "secrets.token_hex, crypto.randomUUID, uuid.v4, nanoid). A fabricated-only argument "
        "is reported when another site passes an issued one for the same parameter."
    ),
    limitations=(
        "Intent is not known: a parameter that legitimately accepts both (a new record or an "
        "existing one) is reported too. Issuers are recognized by name only; an identifier "
        "that arrives as the caller's parameter is not classified."
    ),
    remediation=(
        "Use the identifier the program issued (start the run, create the record, and pass "
        "what that returned). If a new identifier is really wanted, create it where the "
        "other identifiers come from."
    ),
    noncompliant_example=(
        "run = store.start_run()\nrecord(run.id, step)\n...\nrecord(str(uuid4()), step)"
    ),
    compliant_example="run = store.start_run()\nrecord(run.id, step)",
)

GUARD001 = RuleSpec(
    rule_id="GUARD001",
    version="1",
    name="call left unguarded where most sites guard it",
    family=CONSISTENCY_FAMILY,
    config_section=CONSISTENCY_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "Most call sites of a function check their argument first (if has_hash(x): "
        "remove_hash(x)), and this one does not."
    ),
    rationale=(
        "When nearly every caller guards an operation, the operation probably fails without "
        "the guard; the caller that forgot it fails on exactly the input the others "
        "anticipated."
    ),
    guarantees=(
        "Call sites of one project function, resolved through the call graph (resolved and "
        "probable, in files whose role is in rules.consistency.roles), that pass a first "
        "argument. A site is guarded by g when g(...) with the same first argument (by text) "
        "holds where the call runs: inside if g(x) / if (g(x)), after if not g(x): return / "
        "raise / continue / break (and the JavaScript equivalents), after assert g(x), and "
        "through and / && (and not ... or not ...). When at least "
        "rules.consistency.guard_min_sites (3) sites exist and at least guard_min_percent "
        "(75) of them are guarded, the sites with no guard on that argument are reported "
        "(any check counts: isdir where the others use exists); the message names the most "
        "common guard."
    ),
    limitations=(
        "Guards are recognized as calls on the same argument text: a check through another "
        "variable, a try/except around the call, or a check in the caller's caller is not "
        "seen. The rule cannot know that the operation fails without the guard."
    ),
    remediation=(
        "Add the check the other callers make, or handle the failure the operation raises; "
        "if this site cannot reach the failing case, say why in a comment."
    ),
    noncompliant_example=(
        "if store.has_hash(note.id):\n    store.remove_hash(note.id)\n...\n"
        "store.remove_hash(note.id)  # the third caller forgot the check"
    ),
    compliant_example="if store.has_hash(note.id):\n    store.remove_hash(note.id)",
)

# --- MAGIC003: sentinels (decision 30) -----------------------------------------------------

SENTINELS_SECTION = "rules.sentinels"
SENTINELS_FAMILY = "sentinels"
SENTINEL_SECTIONS = (SENTINELS_SECTION,)

MAGIC003 = RuleSpec(
    rule_id="MAGIC003",
    version="1",
    name="small number standing in for a meaning",
    family=SENTINELS_FAMILY,
    config_section=SENTINELS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A -1 (by default) that stands for a value: assigned, returned, passed, or a dict / "
        "object entry (selected_index = -1, exitCode: -1), where it often encodes a meaning of "
        "the program's own that deserves a name."
    ),
    rationale=(
        "MAGIC001 allows -1, 0 and 1 because they are how code counts and indexes. Used as a "
        "value they can also mean 'nothing selected', 'never ran' or 'no limit', a contract "
        "every reader and every comparison has to know. A name (NO_SELECTION = -1) states it "
        "once."
    ),
    guarantees=(
        "A literal whose value is in rules.sentinels.values (-1 by default; only values "
        "MAGIC001 permits are checked, so nothing is reported twice) that is the whole value "
        "of an assignment (a variable, an attribute, a subscript, a class field), a return "
        "(an arrow body too), an argument or keyword argument, or a dict / object entry. Not "
        "reported: subscripts, slices, arithmetic, comparisons (indexOf(x) === -1), an "
        "UPPER_SNAKE_CASE target (the remedy), and arguments of "
        "rules.sentinels.python_index_callees / javascript_index_callees (range, slice, "
        ".pop, .split, .reshape; .slice, .at, .splice, .substr ...), where -1 is an index or "
        "a count. Approximate: the meaning is not known."
    ),
    limitations=(
        "Whether the value means something is not known; a -1 that is plain arithmetic "
        "written as a value (step = -1) is reported too. A sentinel built at run time "
        "(-len(x)) is not seen."
    ),
    remediation=(
        "If the number stands for something, name it where the meaning is defined "
        "(NO_SELECTION = -1, NEVER_RAN = -1) and use the name in every assignment and "
        "comparison; better still, use a value that cannot be confused with a real one "
        "(None, an enum member). If it is plain arithmetic, write it as such."
    ),
    noncompliant_example="state = {'selected_index': -1}\nif state['selected_index'] == -1: ...",
    compliant_example=(
        "NO_SELECTION = -1  # an index that selects nothing\n"
        "state = {'selected_index': NO_SELECTION}"
    ),
)


# --- MAGIC004 (decision 36) ------------------------------------------------------------

MAGIC004 = RuleSpec(
    rule_id="MAGIC004",
    version="1",
    name="constant name that only spells a number",
    family="magic_numbers",
    config_section="rules.magic_numbers",
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A module-level named constant whose name is only number words or digits (TWO = 2, "
        "ONE_HUNDRED = 100, VALUE_100 = 100): the name restates the value."
    ),
    rationale=(
        "MAGIC001 accepts a named constant because the name is supposed to say what the "
        "number is for. A name that spells the number says nothing more than the literal "
        "did, and it hides the literal from MAGIC001 (spec 21.1 decision 36)."
    ),
    guarantees=(
        "The constant definitions MAGIC001's named_constant_definitions covers (Python "
        "NAME = <numeric literal or literal arithmetic>, NAME: Final = ...; JavaScript and "
        "TypeScript const / export const NAME = ...). Reported when every word of the name, "
        "split at underscores, is a number word (ZERO to NINETEEN, the tens, HUNDRED, "
        "THOUSAND, MILLION, BILLION, DOZEN) or digits, after dropping filler words (NUMBER, "
        "NUM, VALUE, CONST, CONSTANT, INT, AND). Severity "
        "rules.magic_numbers.magic004_severity (review by default)."
    ),
    limitations=(
        "A name with any other word is not reported, even when the other word adds little "
        "(SPACES_TWO = 2). Ordinals (FIRST, SECOND) and other languages' number words are "
        "not number words here. Constants in classes, functions and containers are not "
        "constant definitions and are left to MAGIC001."
    ),
    remediation=(
        "Name what the number is for (INDENT_SPACES = 2, MAX_RETRIES = 3, EXIT_USAGE = 2). "
        "If it has no meaning beyond arithmetic, write the literal where it is used."
    ),
    noncompliant_example="TWO = 2\nindent = TWO",
    compliant_example="INDENT_SPACES = 2  # the report's JSON indent\nindent = INDENT_SPACES",
)


# --- MAGIC005 (the under-the-gate rounds' disguises) ---------------------------------------

MAGIC005 = RuleSpec(
    rule_id="MAGIC005",
    version="1",
    name="number written as something else",
    family="magic_numbers",
    config_section="rules.magic_numbers",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A number MAGIC001 would report, written so that it does not see it: the length of a "
        'literal written for its length (len("  "), len(("a", "b")), [a, b].length), a string '
        'converted to a number (int("30"), '
        'Number("3000"), +"30"), numbers inside an inline string that is parsed '
        '(json.loads("[2, 3]"), tomllib.loads("x = 24"), JSON.parse), or spaces given as an '
        'indent (json.dumps(v, indent="  "), JSON.stringify(v, null, "  "))."'
    ),
    rationale=(
        "Every one of these shapes appeared in the under-the-gate experiment: agents met "
        "MAGIC001 by spelling the number differently, which keeps the number and hides it. "
        "The disguise is worse than the literal: the value is still there, without a name, "
        "and now also without a digit."
    ),
    guarantees=(
        "Read from the syntax: len() of a whitespace-only string or of a tuple, list, set or "
        "dict display; .length of a whitespace-only string or an array literal; int() / "
        "float() / Number() / parseInt() / parseFloat() / unary + of a string literal that "
        "is a plain finite number; "
        "json.loads, tomllib.loads, tomli.loads, ast.literal_eval, yaml.safe_load and "
        "JSON.parse of a string literal, with every number in it; an indent of only spaces. "
        "Reported when a value is outside allowed_values (-1 as allow_unary_negative_one "
        "says), only in files where MAGIC001 applies. Severity "
        "rules.magic_numbers.magic005_severity (warning by default)."
    ),
    limitations=(
        "The length of a string with content (a prefix to strip, a format width such as "
        '"YYYY-MM-DD".length) is not reported: it says what the number is. Callees are '
        "matched by the name as written: an alias of a parser is not seen. A "
        'disguise through a name (INDENT = "  "; indent=INDENT) is not seen. Numbers in '
        "data files next to the code are not read."
    ),
    remediation=(
        "Write the number, with a name that says what it is for: INDENT_SPACES = 2, "
        'TIMEOUT_SECONDS = 30. A prefix stripped by length is text.removeprefix("0x"). A '
        "value that is configuration belongs in the configuration, read and validated once."
    ),
    noncompliant_example='indent = len("  ")\ntimeout = int("30")',
    compliant_example="INDENT_SPACES = 2\nTIMEOUT_SECONDS = 30",
)


# --- PROP001, PROP003, PROP005, PROP006, PROP007 (property contracts, milestone P1a) --------------
# docs/shockharness_property_contracts_spec.md. Opt-in: rules.property_contracts.enabled is
# false by default and in every profile, and off is not a deviation.

PROPERTY_CONTRACTS_SECTION = "rules.property_contracts"
PROPERTY_CONTRACTS_FAMILY = "property_contracts"
PROPERTY_CONTRACTS_REMEDIATION_COMMON = (
    " Declarations are requires(value, property, ...), produces(value, property, ...), "
    "preserves(result, source) and preserves_except(result, source, property, ...) from the "
    "installed runtime module; properties are string literals named in "
    "rules.property_contracts.properties."
)

PROP001 = RuleSpec(
    rule_id="PROP001",
    version="1",
    name="value missing a required property",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        'A value reaches a parameter whose function requires a property (requires(x, "p") at '
        "the top of its body), or a catalog sink that requires one, without that property."
    ),
    rationale=(
        "Some facts about a value cannot be seen in the value: normalized, redacted, issued "
        "by a registry. A declared requirement makes the fact part of the function's contract, "
        "and the check makes every path to the function prove it."
    ),
    guarantees=(
        "Python, P1a. Property sets are tracked through one function in source order: "
        "assignment copies; produces adds; preserves copies the source's set; preserves_except "
        "removes the named properties; a call to a project function reads that function's own "
        "declared result (one hop); any other operation, library call or literal carries "
        "nothing; branches meet in the intersection; loops reach a fixed point; an except "
        "handler starts from the set at the start of its try. A call that cannot be resolved "
        "(a method on a value, a callable in a variable or container, getattr) and every "
        "await, generator, and .join over a value whose items are not written out make the "
        "set unknown, reported as unknown."
    ),
    limitations=(
        "One hop: a callee whose result comes from a further call it does not declare carries "
        "only what it declares itself. Methods of classes are not resolved through their "
        "receivers. JavaScript, assignment-target sinks, compositions (f-strings, template "
        "literals) and literal_satisfies are milestone P1b."
    ),
    remediation=(
        "Route the value through the property's declared producer, or, if the property is "
        'established by something the analyzer cannot see, add produces(x, "p") at the point '
        "where it is established and make sure a test exercises it. Never remove the "
        "requirement to satisfy this finding." + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example=(
        'def fit(x):\n    requires(x, "normalized")\n    ...\n\n'
        "def shortcut(raw):\n    return fit(raw)"
    ),
    compliant_example="def pipeline(raw):\n    return fit(normalize(raw))",
)

PROP002 = RuleSpec(
    rule_id="PROP002",
    version="1",
    name="property produced outside its declared producers",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        'A produces(x, "p") in a function that is not one of the catalog\'s producers for p, '
        "when the catalog restricts p to named producers."
    ),
    rationale=(
        "A property the catalog restricts to one producer (the sanitizer, the privacy "
        "evaluator) is a claim only that function may make; a produces anywhere else is a "
        "second, unreviewed way to establish it."
    ),
    guarantees=(
        "Every valid produces of a property whose producers list is not empty, in a unit that "
        "is not one of them: a Python function named module.function or module.Class.method, "
        "a JavaScript function named path:export. A produces at module level or in a nested "
        "function is never a producer."
    ),
    limitations="An empty producers list means any unit may produce the property.",
    remediation=(
        "Route the value through the declared producer, or add this function to the "
        "property's producers in the catalog with the reviewer's agreement."
        + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example=(
        'def shortcut(x):\n    return produces(x, "normalized")  # producers: normalize'
    ),
    compliant_example="def shortcut(x):\n    return normalize(x)",
)

PROP004 = RuleSpec(
    rule_id="PROP004",
    version="1",
    name="returns with inconsistent property sets",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A function with two or more returns, one of which carries a property another does not: "
        "the function's result carries only the intersection."
    ),
    rationale=(
        "A caller sees one result set. A return that lacks what the others establish silently "
        "removes the property from every call, which is rarely what the author meant."
    ),
    guarantees=(
        "Each explicit return whose set is known and lacks a property another known return of "
        "the same function carries, reported at that return."
    ),
    limitations="Falling off the end (an implicit None or undefined) is not reported.",
    remediation=(
        "Establish the property on every return (produces or preserves), or return through one "
        "path, or accept that the result does not carry it." + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example=(
        'def load(x, ok):\n    if ok:\n        return produces(x, "validated")\n    return x'
    ),
    compliant_example=(
        "def load(x, ok):\n    if not ok:\n        raise ValueError(x)\n"
        '    return produces(x, "validated")'
    ),
)

PROP003 = RuleSpec(
    rule_id="PROP003",
    version="1",
    name="property not in the catalog",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary="A declaration names a property that rules.property_contracts.properties does not.",
    rationale=(
        "A misspelled property is a requirement nothing ever satisfies or checks: the silent "
        "success the tool exists to refuse. It is an error while allow_undeclared is false."
    ),
    guarantees=(
        "Every string-literal property argument of a resolved requires, produces or "
        "preserves_except call. Severity rules.property_contracts.severities.PROP003 (error), "
        "review when allow_undeclared is true."
    ),
    limitations="Non-literal property arguments are PROP006 and are not checked here.",
    remediation=(
        "Fix the spelling, or add the property to the catalog with its description, "
        "producers and runtime level." + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example='requires(x, "normalised")  # the catalog says "normalized"',
    compliant_example='requires(x, "normalized")',
)

PROP005 = RuleSpec(
    rule_id="PROP005",
    version="1",
    name="runtime configuration disagrees with the catalog",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A test bootstrap's enable(mode, [...]) lists static properties that are not the "
        'catalog\'s runtime = "static" set.'
    ),
    rationale=(
        "The copied runtime cannot read the catalog, so the test bootstrap states the static "
        "properties a second time. A list that drifted makes the runtime track a property "
        "that cannot carry runtime state, or skip one it should check."
    ),
    guarantees=(
        "Every call in a test-role or config-role file (conftest.py is config by default) that "
        "resolves to the runtime module's enable, whatever rules.property_contracts.roles "
        "says: a literal list of string literals as its second "
        'argument is compared, as a set, with the catalog\'s runtime = "static" properties, '
        "and the finding names those missing from the call and those the catalog does not mark "
        "static. A second argument that is not such a literal is PROP006 in the same file. "
        "`shockharness contracts static-properties` prints the list to paste."
    ),
    limitations=(
        "The predicate half of PROP005 (a verify-level property with no registered predicate) "
        "is milestone P2. Calls in production files are not checked (production never calls "
        "enable)."
    ),
    remediation=(
        "Replace the list with the output of `shockharness contracts static-properties`, or "
        "change the property's runtime level in the catalog if the bootstrap is right."
        + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example='enable("check", ["redacted"])  # the catalog marks two static',
    compliant_example='enable("check", ["cloud_disclosable", "redacted"])',
)

PROP006 = RuleSpec(
    rule_id="PROP006",
    version="1",
    name="malformed declaration",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A declaration the analysis cannot read: a property that is not a string literal, the "
        "wrong number of arguments, a keyword or starred argument."
    ),
    rationale=(
        "The analysis reads properties from the source, so a computed name is a declaration "
        "nobody can check; the call contributes nothing."
    ),
    guarantees=(
        "Resolved requires / produces / preserves / preserves_except calls: a property argument "
        "that is not a plain string literal; requires or produces with no value; produces with "
        "no property; preserves without exactly a result and a source; preserves_except "
        "without a property; any keyword or starred argument."
    ),
    limitations="Calls that do not resolve to the runtime module are ordinary calls.",
    remediation=(
        "Write each property as a string literal and pass the arguments positionally."
        + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example="requires(x, PROPERTY)",
    compliant_example='requires(x, "normalized")',
)

PROP007 = RuleSpec(
    rule_id="PROP007",
    version="1",
    name="misplaced parameter requirement",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A requires on a parameter that is not a statement at the top of the body, before any "
        "other use of the parameter, outside branches and loops."
    ),
    rationale=(
        "A function's requirements belong where a reader looks for its signature; a "
        "requirement after a use or under a condition is not part of the contract."
    ),
    guarantees=(
        "A resolved requires whose first argument is a parameter of the enclosing function, "
        "when it is nested in a branch, loop, try or with, or when an earlier statement of the "
        "body (the docstring aside) uses the parameter. It is not counted in the contract."
    ),
    limitations="A requires on a local or a call result is a mid-body check and may be anywhere.",
    remediation=(
        "Move the requires to the top of the function body, before the parameter's first use."
        + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example='def fit(x):\n    y = x.copy()\n    requires(x, "normalized")',
    compliant_example='def fit(x):\n    requires(x, "normalized")\n    y = x.copy()',
)


PROP008 = RuleSpec(
    rule_id="PROP008",
    version="1",
    name="function without a declared contract (complete)",
    family=PROPERTY_CONTRACTS_FAMILY,
    config_section=PROPERTY_CONTRACTS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        'Under enforcement = "complete" (or in complete_paths): a parameter with no requires, '
        "or a return with no produces or preserves."
    ),
    rationale=(
        "At the complete level the absence of a contract is visible: an agent cannot leave a "
        "function's assumptions unstated. requires(x) with no property records that a "
        "parameter was considered and needs nothing."
    ),
    guarantees=(
        "Python: module-level functions and methods of module-level classes (self or cls of a "
        "method excepted). JavaScript and TypeScript: module-level function declarations, "
        "module-level const functions and arrows, and class methods. Each parameter bound to a "
        "name without a header requires; each return of a value (not a bare return or None / "
        "undefined) that is not a produces, preserves or preserves_except call; an arrow's "
        "expression body counts as its return."
    ),
    limitations=(
        "Nested functions, lambdas and inline callbacks are not contract units. A destructured "
        "parameter cannot carry a requires and is not reported. A function with no return has "
        "no result contract."
    ),
    remediation=(
        'Declare what the parameter must satisfy (requires(path, "validated_path")) and what '
        "the result carries (return produces(...) or preserves(...)), or declare explicitly that "
        "there is nothing to require with requires(path) and no properties, which records the "
        "decision. If you cannot determine the contract from the code and the spec, stop and "
        "report it rather than guessing." + PROPERTY_CONTRACTS_REMEDIATION_COMMON
    ),
    noncompliant_example="def load_notes(path):\n    return read(path)",
    compliant_example=(
        'def load_notes(path):\n    requires(path, "validated_path")\n'
        "    return preserves(read(path), path)"
    ),
)


CONTRACT_RULES: tuple[RuleSpec, ...] = (
    PROP001,
    PROP002,
    PROP003,
    PROP004,
    PROP005,
    PROP006,
    PROP007,
    PROP008,
)


# --- STATE002 (2026-10-17) --------------------------------------------------------------

STATE002 = RuleSpec(
    rule_id="STATE002",
    version="1",
    name="shared object published before it is initialized",
    family="module_state",
    config_section=MODULE_STATE_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "A function assigns a newly constructed object to a shared name (a global, or a self "
        "attribute outside a constructor) and then sets the object's attributes: another "
        "thread reading the name in between gets a half-built object."
    ),
    rationale=(
        "Publishing is the moment other code can see an object. In one project, a cache "
        "getter assigned the cached service and then set its key, so a concurrent "
        "request's cache hit got a service with no key and failed. Building "
        "the object in a local and publishing it last removes the window."
    ),
    guarantees=(
        "Python. In one function, statements in source order (nested functions and classes "
        "excluded): an assignment of a call whose callee's last name is capitalized (a class) "
        "to a name the function declares global, or to self.<attr> in a method other than "
        "__init__, __new__, __post_init__, setUp or setup_method, followed by an assignment to "
        "an attribute of that name before a return or a rebinding. Reported at the "
        "publication. Severity rules.module_state.state002_severity (review by default)."
    ),
    limitations=(
        "Whether other threads read the name is not known: a single-threaded module matches "
        "too (the fix is still clearer). A factory function with a lowercase name, an object "
        "built by another function, a mutation through a method call (G.configure(...)) and "
        "JavaScript are not covered."
    ),
    remediation=(
        "Build the object in a local, set its fields, and assign the shared name last "
        "(service = EncryptionService(); service.dek = dek; _service = service). If the "
        "object must be shared while it is built, hold the lock its readers take."
    ),
    noncompliant_example="_service = EncryptionService()\n_service.dek = dek",
    compliant_example="service = EncryptionService()\nservice.dek = dek\n_service = service",
)

STATE003 = RuleSpec(
    rule_id="STATE003",
    version="1",
    name="state read outside the lock that guards its writes",
    family="module_state",
    config_section=MODULE_STATE_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "A method checks or passes on an attribute that another method only writes while "
        "holding a lock, without taking the lock itself: the value can change between the "
        "check and what the method does with it."
    ),
    rationale=(
        "A lock protects a value only where it is held. In one project, an encrypted stream's "
        "write checked that it was open and encrypted with its key before taking the lock "
        "that close() holds to close the stream and clear the key, so a write racing a "
        "logout could use a cleared key or a closed file."
    ),
    guarantees=(
        "Python. In a class, a lock is an attribute taken as with self.<lock>: whose name holds "
        "lock, mutex, cond, guard or sem; an attribute is guarded when a method other than a "
        "constructor assigns self.<attr> inside such a with. Reported: a read of it outside "
        "every such with, as an if / while / assert / conditional-expression test or as an "
        "argument of a call that is not logging, in a method that does not run with the lock "
        "held (one named *_locked, or one every self.m(...) call in the class makes under the "
        "lock or from such a method, to a fixpoint); once per attribute and method. A module "
        "works the same way with module-level locks and global names. Severity "
        "rules.module_state.state003_severity (review by default)."
    ),
    limitations=(
        "Whether other threads run the method is not known, and a deliberate lock-free fast "
        "path (a flag re-checked under the lock) matches too. Locks are recognized by name; a "
        "lock passed in, held by a caller in another class, or taken with acquire() / "
        "release() is not seen. Reads that only feed logging are not reported."
    ),
    remediation=(
        "Take the lock before the read and hold it through what the read decides: the check "
        "and the act under one with. A deliberate fast path re-checks under the lock; "
        "suppress it with that reason."
    ),
    noncompliant_example=(
        "def write(self, message):\n    if self._closed:\n        raise StreamClosed()\n"
        "    with self._lock:\n        self._file.write(message)"
    ),
    compliant_example=(
        "def write(self, message):\n    with self._lock:\n        if self._closed:\n"
        "            raise StreamClosed()\n        self._file.write(message)"
    ),
)


# --- EXC005 (0.9.0, under-the-gate round 3) ---------------------------------------------

EXC005 = RuleSpec(
    rule_id="EXC005",
    version="1",
    name="catch boundary that no catch uses",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A declared boundary (rules.exceptions.boundaries) names an exception that no catch "
        "in the files it covers catches: it approves a catch nobody has written, or no longer "
        "writes."
    ),
    rationale=(
        "A boundary is a reviewed decision that one file may catch one kind of external "
        "failure. Declared ahead of the code, or left behind after the catch is gone, it "
        "pre-approves the next catch there without review. In the under-the-gate "
        "experiment agents declared boundaries for files they had not written yet."
    ),
    guarantees=(
        "For each exception a boundary names: reported at the boundary's path line in the "
        "configuration file when no except/catch clause or capture manager in the files the "
        "boundary covers (its glob, its language; a JavaScript boundary also covers "
        "TypeScript) catches that exception, matched as EXC001 matches. Judged only when the "
        "boundary covers at least one file of the tree and every covered file was analyzed "
        "in this run. Severity warning; rules.exceptions.enabled = false turns it off."
    ),
    limitations=(
        "A boundary for a file that does not exist yet is not judged, and neither is one "
        "whose files were not all analyzed (the edit hook, check on a subdirectory). A catch "
        "whose type cannot be resolved does not count as a use."
    ),
    remediation=(
        "Remove the exception from the boundary, or the boundary itself; declare a boundary "
        "when you write the catch it approves, for the exceptions that catch handles."
    ),
    noncompliant_example=(
        '{ path = "app/cli.py", language = "python", exception = "OSError", '
        'reason = "..." }  # cli.py catches nothing'
    ),
    compliant_example=(
        '{ path = "app/io.py", language = "python", exception = "OSError", '
        'reason = "reading the input file" }  # io.py: except OSError as exc: raise ...'
    ),
)


EXC006 = RuleSpec(
    rule_id="EXC006",
    version="1",
    name="an error class derived from SystemExit",
    family="exceptions",
    config_section="rules.exceptions",
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(PYTHON,),
    summary=(
        "A class derived from SystemExit is raised like an error, but except Exception does "
        "not catch it and the process ends with its argument as the exit status."
    ),
    rationale=(
        "Deriving a domain error from SystemExit makes it skip every handler written for "
        "errors, including the ones at the boundaries that report and recover, and turns it "
        "into a silent exit. Agents in the under-the-gate experiment wrote ConfigError(SystemExit) "
        "and InputUnreadableError(SystemExit) to get an exit code without writing an entry point "
        "that maps errors to one."
    ),
    guarantees=(
        "Python: a class statement with SystemExit or builtins.SystemExit among its bases, in "
        "any role. Exact on the syntax."
    ),
    limitations=(
        "Only SystemExit itself: classes derived from KeyboardInterrupt, GeneratorExit or "
        "BaseException are framework control flow more often than not (pytest's outcomes, "
        "hypothesis's StopTest) and are not reported; nor is a base reached through another "
        "class or an alias."
    ),
    remediation=(
        "Derive the error from Exception (or a domain base under it), and let the entry point "
        "catch it and exit with the status it maps to: except ConfigError as error: "
        "raise SystemExit(EXIT_CONFIG) from error."
    ),
    noncompliant_example="class ConfigError(SystemExit):\n    pass",
    compliant_example=(
        "class ConfigError(Exception):\n    pass\n\n\ndef main():\n    try:\n        run()\n"
        "    except ConfigError as error:\n        raise SystemExit(EXIT_CONFIG) from error"
    ),
)


# --- DOM001 (decision 27) ---------------------------------------------------------------

DOM001 = RuleSpec(
    rule_id="DOM001",
    version="1",
    name="delegated handler that drops SVG targets",
    family="dom",
    config_section=DOM_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(JAVASCRIPT, TYPESCRIPT),
    summary=(
        "A delegated event handler tests event.target instanceof HTMLElement before "
        "event.target.closest(...): a click on an icon inside a button targets an SVG "
        "element, fails the test and is silently dropped."
    ),
    rationale=(
        "Delegated handlers find the element they care about with closest(), which every "
        "Element has. Narrowing the target to HTMLElement first is a type-checker habit "
        "that excludes SVG (and MathML) targets: the handler works when the text is "
        "clicked and does nothing when the icon is."
    ),
    guarantees=(
        "In one function body: if (!(X instanceof C)) followed by an early return, throw, "
        "continue or break and, later in the same block, X.closest(...); or "
        "if (X instanceof C) whose consequence calls X.closest(...). X is <expr>.target or a "
        "local assigned from one (never currentTarget, which is the element the listener is "
        "on); C is in rules.dom.classes (HTMLElement). A narrower class (HTMLButtonElement, "
        "HTMLInputElement) is a deliberate filter and not reported. Exact."
    ),
    limitations=(
        "Syntax only: a guard through a helper (isHtml(target)), a target stored on an "
        "object, or closest() reached through another variable is not seen."
    ),
    remediation=(
        "Test instanceof Element (closest is defined there), or call closest() first and "
        "narrow its result: const button = target instanceof Element ? "
        "target.closest('button') : null."
    ),
    noncompliant_example=(
        "list.addEventListener('click', (event) => {\n"
        "  if (!(event.target instanceof HTMLElement)) return;\n"
        "  const item = event.target.closest('li');\n"
        "});"
    ),
    compliant_example=(
        "list.addEventListener('click', (event) => {\n"
        "  if (!(event.target instanceof Element)) return;\n"
        "  const item = event.target.closest('li');\n"
        "});"
    ),
)
DOM002 = RuleSpec(
    rule_id="DOM002",
    version="1",
    name="floating control a press handler treats as outside",
    family="dom",
    config_section=DOM_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(JAVASCRIPT, TYPESCRIPT),
    summary=(
        "A pressable element attached to document.body (a notice, a banner, an overlay) "
        "matches none of the selectors a page-level press handler skips: its presses reach "
        "that handler as presses outside, which can leave the current mode or swallow the "
        "click before the element's own action runs."
    ),
    rationale=(
        "A handler that acts on presses outside (leave edit mode, consume the next click) "
        "lists the elements that handle their own presses. Floating UI attached to the body "
        "afterwards sits outside everything that list was written for, so its first press "
        "silently does the wrong thing."
    ),
    guarantees=(
        "Opt-in: rules.dom.press_exclusions names the functions holding the skip lists "
        "(path:function); nothing is reported while it is empty. A skip list is the "
        "closest(...) / matches(...) arguments of that function: strings, [...].join(','), "
        "and constants resolved in the file and through its imports. A control is an element "
        "passed to document.body.append / appendChild / prepend / insertBefore / "
        "insertAdjacentElement, or appended into what a function that attaches and returns "
        "such an element gives back, when the building function makes something pressable "
        "(a button, role=button, a click or pointer listener) and does not remove it again. "
        "Reported when its id, classes and tag (or its container's) match the last compound "
        "of no selector of a list. An entry whose file holds no such function is reported "
        "as unknown."
    ),
    limitations=(
        "Vanilla DOM only: jQuery, portals and framework rendering are not seen. Attribute "
        "and pseudo selectors are not evaluated, names set elsewhere than the building "
        "function are not seen, and whether the handler really acts on such presses is the "
        "project's statement in press_exclusions."
    ),
    remediation=(
        "Add the control's selector to the skip list (or give it a class the list skips), "
        "and add a browser test that presses it in each mode; if a press on it is meant to "
        "count as outside, suppress the finding with that reason."
    ),
    noncompliant_example=(
        "// mouse-events.js\nfunction isExcluded(t) { return t.closest('.modal, #menu'); }\n"
        "// notice.js\nconst card = document.createElement('aside');\n"
        "card.className = 'notice';\ncard.append(button);\ndocument.body.append(card);"
    ),
    compliant_example=("function isExcluded(t) { return t.closest('.modal, #menu, .notice'); }"),
)


DOM003 = RuleSpec(
    rule_id="DOM003",
    version="1",
    name="selection saved as text positions and found again through text nodes only",
    family="dom",
    config_section=DOM_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(JAVASCRIPT, TYPESCRIPT),
    summary=(
        "A selection or caret is saved as text positions (a range's toString().length) and "
        "later found again by walking text nodes only. A point next to an image, a mention "
        "chip, a widget or an empty block has no text position of its own, so the round "
        "trip moves it to the nearest text or finds nothing."
    ),
    rationale=(
        "Counting characters is the easy way to remember where the user was across a "
        "redraw, and it works while the content is only text. One editor's paste command "
        "saved the selection that way, and right-clicking selected images threw: "
        "a selection of images has no text. medium-editor carries hand patches for the same "
        "blind spot (startsWithImage, trailingImageCount, emptyBlocksIndex)."
    ),
    guarantees=(
        "Across files, to a fixpoint: an encoder is a named function that returns a range's "
        "or selection's toString().length (the range from createRange, getRangeAt, "
        "cloneRange, getSelection or new Range), or an encoder's result, directly or in an "
        "object. A decoder is a named function that walks a createTreeWalker or "
        "createNodeIterator with SHOW_TEXT, or tests nodeType against a text node and reads "
        "lengths, and counts with a parameter (or one of its properties); or one that passes "
        "a parameter to a decoder's position. Reported at a call of a decoder whose position "
        "argument holds an encoder's result, through locals, + and -, or a property the file "
        "stores one under. Functions are resolved in the file and through its imports; "
        "obj.name(...) is matched to a function of that name anywhere (approximate). A point "
        "measured inside if (x.nodeType === Node.TEXT_NODE) is exact and not reported."
    ),
    limitations=(
        "Whether the content can hold anything but text is not known: a round trip over a "
        "text-only element is reported too and takes a suppression with that reason. "
        "Positions counted another way (textContent.length, innerText) and walks written "
        "without a nodeType test are not seen, nor values kept in module state other than "
        "an object property, or through more than one call level of parameters."
    ),
    remediation=(
        "Keep the point as a node and offset while the node lives, or as the path of child "
        "indexes from the root (it survives a redraw that rebuilds the same structure), and "
        "test clicks with range.isPointInRange; a document model keeps selections in its own "
        "positions. If the content is text only, suppress with that reason."
    ),
    noncompliant_example=(
        "const saved = { start: textOffsetOf(root, range.startContainer, range.startOffset) };\n"
        "// ... after a redraw\n"
        "const point = textPositionToNodePoint(root, saved.start);  // walks SHOW_TEXT"
    ),
    compliant_example=(
        "const saved = { start: nodePath(root, range.startContainer), offset: range.startOffset };"
    ),
)

# --- Dead code (DEAD001, DEAD002) ---------------------------------------------------------
# Opt-in (rules.dead_code.enabled): a project-wide reachability judgment, made only when the
# run analyzed every file the configuration includes.

DEAD_CODE_SECTION = "rules.dead_code"
DEAD_CODE_FAMILY = "dead_code"
DEAD_CODE_GUARANTEES = (
    "Judged only when the run analyzed every file the configuration includes and none "
    "failed to parse. Roots: module and class bodies, test and config files, functions a "
    "decorator other than staticmethod/classmethod/property and the like registers, names "
    "in __all__, dunder methods, JavaScript constructors, methods of a class derived (also "
    "through project ancestors) from a class the project does not define or whose instance "
    "is assigned to an imported module's attribute, [project.scripts] targets, and "
    "rules.dead_code.entry_points (globs over "
    "path::qualified.name). Reached: through any call-graph edge, an unresolved call or an "
    "attribute read of the same final name, a function named as a value (passed, stored, "
    "bound, listed), an import of it that is used, and a function nested in a reached one; "
    "a method is reached while a method it overrides or that overrides it is. One finding "
    "per head (a dead function no dead function reaches), listing what only it reaches."
)
DEAD_CODE_LIMITATIONS = (
    "Names are matched loosely (any method of a called or read name counts), so dead code "
    "that shares a name with live code is not reported. Calls the analysis cannot see make "
    "live code look dead: getattr with a computed name, dispatch tables keyed by strings "
    "built elsewhere, functions only an HTML page, a template or a file outside the "
    "analysis calls. List those in entry_points. Arrow functions and function expressions "
    "count only when bound to a declared name or a class field; methods of an object "
    "literal only when the object is bound to a name."
)

DEAD001 = RuleSpec(
    rule_id="DEAD001",
    version="1",
    name="function nothing reaches",
    family=DEAD_CODE_FAMILY,
    config_section=DEAD_CODE_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A function or method that no production code calls or names and nothing registers, "
        "reported once with everything reachable only through it: a dead cluster."
    ),
    rationale=(
        "Code that lost its last caller still reads as working, and its tests still pass. "
        "In one project, a tree builder had no callers and about 400 lines hung off it; one of "
        "them was the only code that highlighted search terms, so highlighting silently "
        "stopped for a year. The cluster is the unit of decision: delete it, or reconnect "
        "the behavior it holds."
    ),
    guarantees=DEAD_CODE_GUARANTEES,
    limitations=DEAD_CODE_LIMITATIONS,
    remediation=(
        "Decide whether the behavior is still wanted. If it is, call it from where it "
        "belongs and test that path; if not, delete the cluster and the tests that only "
        "exercise it. A function reached in a way the analysis cannot see goes in "
        "rules.dead_code.entry_points with the reason in a comment."
    ),
    noncompliant_example=(
        "def build_tree(items, query):  # nothing calls it any more\n"
        "    return highlight_search_terms(render(items), query)"
    ),
    compliant_example="# deleted, or called again from the view that needs it",
)

DEAD002 = RuleSpec(
    rule_id="DEAD002",
    version="1",
    name="function only tests reach",
    family=DEAD_CODE_FAMILY,
    config_section=DEAD_CODE_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "A production function that only tests call or name: dead in production, kept "
        "alive by its tests, reported with everything reachable only through it."
    ),
    rationale=(
        "A passing test of code production never runs is false assurance: the behavior it "
        "checks is not the behavior users get."
    ),
    guarantees=DEAD_CODE_GUARANTEES,
    limitations=DEAD_CODE_LIMITATIONS,
    remediation=(
        "Either production should call it (reconnect it, and test the production path), "
        "or it and its tests should go. A test helper belongs under tests/."
    ),
    noncompliant_example=(
        "def highlight_search_terms(html, query): ...  # only tests/test_render.py calls it"
    ),
    compliant_example="# called from the renderer the notes list uses, and tested there",
)


# --- Duplicated helpers (DUP001, DUP002) ----------------------------------------------------
# Opt-in (rules.duplicates.enabled), judged only when the run analyzed every included file.

DUPLICATES_SECTION = "rules.duplicates"
DUPLICATES_FAMILY = "duplicates"
DUPLICATES_GUARANTEES = (
    "Functions with a name (a def or method; a JavaScript declaration, method, or function "
    "bound to a declared name, class field or object key) and at least "
    "rules.duplicates.min_statements statements and min_tokens tokens, in the roles "
    "rules.duplicates.roles lists. A body is compared as its syntax tokens in order, with "
    "comments, layout and the docstring dropped, parameters and locals renamed by first "
    "appearance, and a string's mention of the file's own path or the function's own name "
    "set aside. Python and JavaScript are compared separately, JavaScript and TypeScript "
    "together. Judged only when the run analyzed every included file and none failed to parse."
)
DUPLICATES_LIMITATIONS = (
    "Syntax only: two bodies that do the same thing differently are not matched, and two "
    "identical bodies calling different functions of the same name are. Drift is looked for "
    "only among functions whose names match once leading underscores and case are set aside. "
    "Copies annotated with different parameter or return types are not grouped: they are "
    "parallel implementations (one per AST type, say), which an import cannot merge."
)

DUP001 = RuleSpec(
    rule_id="DUP001",
    version="1",
    name="helper copied into several files",
    family=DUPLICATES_FAMILY,
    config_section=DUPLICATES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "The same function body, written out in two or more files: one finding per group of "
        "copies, at the first, listing the rest."
    ),
    rationale=(
        "Copies drift. A fix made to one copy does not reach the others, and the copies that "
        "were not fixed keep the bug. One project had twenty HTML escapers, one per dialog; some "
        "returned an empty string for a non-string where the others threw."
    ),
    guarantees=DUPLICATES_GUARANTEES,
    limitations=DUPLICATES_LIMITATIONS,
    remediation=(
        "Keep one definition in a shared module and import it where it is needed; delete the "
        "copies. A copy that must stay separate (an entry script that may not import the "
        "application, a vendored file) gets an inline suppression with that reason."
    ),
    noncompliant_example=(
        "// dialog-a.js and dialog-b.js\nfunction escapeHtml(value) { ... }  // the same body twice"
    ),
    compliant_example="import { escapeHtml } from './html.js';",
)

DUP002 = RuleSpec(
    rule_id="DUP002",
    version="1",
    name="copies of a helper that have drifted apart",
    family=DUPLICATES_FAMILY,
    config_section=DUPLICATES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "Functions of the same name in several files whose bodies are alike but not the "
        "same: versions of one helper that have drifted. One finding per group, with the "
        "first line where the two most common versions differ."
    ),
    rationale=(
        "A difference between copies is either a fix that reached only some of them or a bug "
        "that only some have, and the caller cannot tell which version it gets. One "
        "project's escapers drifted: some threw on a non-string, some returned an empty "
        "string, so the same bad input failed loudly in one dialog and showed blank text in "
        "another."
    ),
    guarantees=DUPLICATES_GUARANTEES
    + " Versions are linked when difflib's ratio over their tokens is at least "
    "rules.duplicates.similarity (0.85).",
    limitations=DUPLICATES_LIMITATIONS,
    remediation=(
        "Decide which version is right, keep that one in a shared module, and import it "
        "everywhere; if the difference is intended, give the functions different names that "
        "say how they differ."
    ),
    noncompliant_example=(
        "function escapeHtml(v) { if (typeof v !== 'string') throw new Error('...'); ... }\n"
        "function _escapeHtml(v) { if (typeof v !== 'string') return ''; ... }"
    ),
    compliant_example="import { escapeHtml } from './html.js';  // one version",
)


# --- Import boundaries (IMPORT002, decision 44) ---------------------------------------------
# Configured per project (rules.import_boundaries.forbidden); with no entry it reports nothing.

IMPORT_BOUNDARIES_SECTION = "rules.import_boundaries"
IMPORT_BOUNDARIES_FAMILY = "import_boundaries"

CALL_BOUNDARIES_SECTION = "rules.call_boundaries"
CALL_BOUNDARIES_FAMILY = "call_boundaries"

CALL001 = RuleSpec(
    rule_id="CALL001",
    version="1",
    name="call across a declared boundary",
    family=CALL_BOUNDARIES_FAMILY,
    config_section=CALL_BOUNDARIES_SECTION,
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A file makes a call that a [[rules.call_boundaries.forbidden]] entry keeps it from "
        "making: only the files the entry allows may write to disk, open a connection, or "
        "make whatever call the entry names."
    ),
    rationale=(
        "Some capabilities belong in one place: a security policy can keep every disk write "
        "in an encrypted writer and every outbound request in one client, so plaintext never "
        "touches disk and the network has one chokepoint. The capability is a call on "
        "something everyone imports (open, Path.write_text, shutil) or a global (fetch), so "
        "an import boundary cannot hold it, and one convenient call crosses it unseen."
    ),
    guarantees=(
        "Python, JavaScript and TypeScript. Every call of a bound file (callers globs, less "
        "allowed_callers), at any depth, a constructor call (new X) included. A call name "
        "matches the call resolved through the file's own imports and everything below it "
        "(shutil matches shutil.copy, fs/promises.writeFile matches itself); a name no "
        "import binds is a global (fetch, open), skipped when the module or the calling "
        "function binds the name itself; window. / globalThis. / self. are dropped. .method "
        "matches a method of that name on any receiver (approximate). /mode=write counts "
        "the call only when its literal mode or flags write (w, a, x or +); a mode the "
        "analysis cannot read is an unknown finding. @disk_writes and @network expand to "
        "the section's lists for the file's language. One finding per call, at the call."
    ),
    limitations=(
        "The call is judged where it is written: a wrapper that writes is reported, not its "
        "callers, and what reaches the call (plaintext or not) is property contracts' "
        "question. A client's later calls are not calls of its module (client.get after "
        "httpx.Client()): the construction is. Reading os.environ is an attribute, not a "
        "call. A method matched by name may be another type's method of that name."
    ),
    remediation=(
        "Make the call through the module the entry allows (the encrypted writer, the one "
        "client), or move the code there. If the boundary itself is wrong, change the entry "
        "in the configuration, where the change is reviewed."
    ),
    noncompliant_example=(
        "# app/notes.py, under a boundary that keeps disk writes in app/storage/writer.py\n"
        "Path(path).write_text(note.body)"
    ),
    compliant_example="storage.writer.save_note(note)  # the one module that writes",
)

IMPORT002 = RuleSpec(
    rule_id="IMPORT002",
    version="1",
    name="import across a declared boundary",
    family=IMPORT_BOUNDARIES_FAMILY,
    config_section=IMPORT_BOUNDARIES_SECTION,
    default_severity=SEVERITY_ERROR,
    implemented=True,
    languages=ALL_LANGUAGES,
    summary=(
        "A file imports a module that a [[rules.import_boundaries.forbidden]] entry keeps "
        "it from importing (a project file by path, or a package or standard-library module "
        "by name), or a name the entry's allowed_names does not list."
    ),
    rationale=(
        "Some modules must never reach others: a project's startup code and database "
        "migrations may not import its backup service, so a migration can never touch a "
        "backup. Such a boundary lives in nobody's head once the code is written; an agent "
        "adding one convenient import crosses it without knowing it was there."
    ),
    guarantees=(
        "Every import of an analyzed file, at any depth (a function's lazy import included): "
        "Python import and from-import, JavaScript and TypeScript import, export-from, "
        "require and import() with a literal specifier. An entry applies when the importing "
        "file matches one of its importers globs and none of its allowed_importers globs, "
        "and the import resolves to an analyzed file matching one of its imported globs, or "
        "names a module listed in modules or one below it (cryptography.hazmat covers "
        "cryptography.hazmat.primitives and from cryptography import hazmat; a JavaScript "
        "package covers its paths; node: is ignored). With allowed_names empty, any import of the "
        "module is reported; otherwise each name imported must be listed, and an import of "
        "the whole module (import m, from pkg import m, import * as m, a bare require, a "
        "star or side-effect import) is reported. Exact on the resolved import edges."
    ),
    limitations=(
        "Direct imports only: a forbidden module reached through another project module, or "
        "a name an allowed importer re-exports, is not reported. A project file named by path "
        "must be among the analyzed files (a check of one file does not resolve its imports "
        "to other files; a module named by name needs no other file), uses below the module "
        "(os.urandom, os.environ) are not imports, and computed specifiers "
        "(importlib.import_module(name), import(expr)) are not followed. TypeScript type-only "
        "imports are not imports."
    ),
    remediation=(
        "Do not import across the boundary: move what is needed to a module both sides may "
        "import, or have the caller pass it in. If the boundary itself is wrong, change the "
        "entry in the configuration, where the change is reviewed."
    ),
    noncompliant_example=(
        "# app/db/migrations.py, under a boundary that forbids app/services/backups.py\n"
        "from app.services.backups import restore_snapshot"
    ),
    compliant_example="# app/db/migrations.py imports only the database layer",
)


# --- MAGIC002 (decision 31) ---------------------------------------------------------------

MAGIC_STRINGS_SECTION = "rules.magic_strings"
STRING_SECTIONS = (MAGIC_STRINGS_SECTION,)

MAGIC002 = RuleSpec(
    rule_id="MAGIC002",
    version="1",
    name="string literal repeated across files",
    family="magic_strings",
    config_section=MAGIC_STRINGS_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=WITH_CSHARP,
    summary=(
        "The same string literal (a status, an endpoint, a header, an error code) is written "
        "out at several places across files: one decision copied around, which a rename or "
        "a typo in one copy splits."
    ),
    rationale=(
        "A repeated literal is a contract with no owner: nothing ties the copies together, so "
        "they drift. One name, defined where the meaning is, makes every use point at the "
        "same decision and makes a change one edit."
    ),
    guarantees=(
        "Cross-file, over the files whose role is in rules.magic_strings.roles: string "
        "literals of the configured kinds (arguments, subscripts, comparisons and plain "
        "values by default; dict / object keys and JSX attributes are opt-in) at least "
        "min_length characters long (whitespace aside), not listed in allowed, and not the "
        "message of a log call or an exception (message_callees; a callee ending in Error, "
        "Exception or Warning), that appear at least min_occurrences times in at least "
        "min_files files and are compared (==, in, case) in at least min_compared_files "
        "files (2: a decision string, not a word that repeats). One finding per value, at "
        "its first use, naming the other places. "
        "Never counted: docstrings, f-string and template parts, type annotations and "
        "TypeScript literal types, import specifiers, require() arguments, __all__ and "
        "directives. Severity: review, or error with mode = 'fail'."
    ),
    limitations=(
        "Whether two equal strings mean the same thing is not known: a word that happens to "
        "repeat (a column name, a label) is reported too. Strings built at run time and "
        "strings inside f-strings or templates are not seen."
    ),
    remediation=(
        "Define the value once where its meaning lives (an enum, a constants module, a "
        "config schema) and use the name everywhere. If the copies only look alike, leave "
        "them, or list the value in rules.magic_strings.allowed with the reason in review."
    ),
    noncompliant_example=(
        "# a.py\nif order.status == 'pending': ...\n# b.py\norder.status = 'pending'"
    ),
    compliant_example=(
        "# statuses.py\nclass Status(StrEnum):\n    PENDING = 'pending'\n"
        "# a.py\nif order.status == Status.PENDING: ..."
    ),
)


# --- Godot names (GODOT001-GODOT005, decision 51) -----------------------------------------
# C# only, judged against the files of the Godot project a script belongs to, on a
# whole-project run whose project and scene files could all be read.

GODOT_NAMES_SECTION = "rules.godot_names"
GODOT_NAMES_FAMILY = "godot_names"
GODOT_GUARANTEES_COMMON = (
    "Only names written as string literals in a C# file under a project.godot are judged, "
    "and only when the run analyzed every included file and read every project.godot, "
    "scene (.tscn) and resource (.tres) file of the project. "
)
GODOT_LIMITATIONS_COMMON = (
    "A name built at run time, or read from a variable or a constant, is not seen. "
    "GDScript files are not analyzed: what they define or add counts only through the "
    "scene and project files."
)
GODOT_REMEDIATION_COMMON = (
    "Use the generated names where Godot has them (SignalName.X, MethodName.X), and keep "
    "the other names in one class of constants."
)

GODOT001 = RuleSpec(
    rule_id="GODOT001",
    version="1",
    name="undefined input action",
    family=GODOT_NAMES_FAMILY,
    config_section=GODOT_NAMES_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(CSHARP,),
    summary=(
        'An input action read by name (Input.IsActionPressed("jump")) that the project\'s '
        "Input Map does not define and no code adds: Input reads it as never pressed."
    ),
    rationale=(
        "A misspelled or renamed action fails silently: Godot logs an error when the line "
        "runs, and the control simply does nothing. The project file says which actions "
        "exist, so the mismatch is visible before the game runs."
    ),
    guarantees=GODOT_GUARANTEES_COMMON
    + (
        "Reads: IsActionPressed, IsActionJustPressed, IsActionJustReleased, "
        "IsActionReleased, GetActionStrength, GetActionRawStrength, ActionPress, "
        "ActionRelease, IsAction, and every string argument of GetAxis and GetVector, on any "
        "receiver. Defined: the [input] section of project.godot, Godot's own ui_* actions, "
        'and InputMap.AddAction("name") anywhere in the project\'s C#.'
    ),
    limitations=GODOT_LIMITATIONS_COMMON + " An action a GDScript adds at run time is reported.",
    remediation=(
        "Add the action in Project Settings > Input Map, or correct the name. "
        + GODOT_REMEDIATION_COMMON
    ),
    noncompliant_example='if (Input.IsActionJustPressed("jupm")) Jump();',
    compliant_example=(
        'if (Input.IsActionJustPressed(Actions.Jump)) Jump();  // "jump" is in [input]'
    ),
)

GODOT002 = RuleSpec(
    rule_id="GODOT002",
    version="1",
    name="node path missing from the scene",
    family=GODOT_NAMES_FAMILY,
    config_section=GODOT_NAMES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(CSHARP,),
    summary=(
        'GetNode("Path") on the script\'s own node names a node that does not exist in a '
        "scene the script is attached to: GetNode fails there unless the node is added at "
        "run time."
    ),
    rationale=(
        "Renaming or moving a node in the editor does not update the strings that name it; "
        "the script fails only when that scene runs that line. The scene file shows the "
        "tree the path is resolved in."
    ),
    guarantees=GODOT_GUARANTEES_COMMON
    + (
        "GetNode and GetNode<T> with no receiver or a this receiver, against every scene "
        "that attaches the class's script (a script named after the class), from the node "
        "it is attached to: . and .. followed, %Name resolved to a node with Access as "
        "Unique Name, /root/Name to an autoload, and one level into an instanced scene. "
        "A path that leaves the scene's root, another absolute path, or a script no scene "
        "attaches is not judged."
    ),
    limitations=GODOT_LIMITATIONS_COMMON
    + (
        " Nodes added by code (AddChild) are not in the scene file, which is why this is "
        "a review; GetNodeOrNull is not judged, since it says the node may be missing."
    ),
    remediation=(
        "Correct the path, or get the node through an [Export] property the editor "
        "assigns, which follows renames. A node added at run time is better reached "
        "through the reference kept when it was added."
    ),
    noncompliant_example='var score = GetNode<Label>("HUD/Score");  // the node is HUD/ScoreLabel',
    compliant_example="[Export] public Label Score { get; set; }",
)

GODOT003 = RuleSpec(
    rule_id="GODOT003",
    version="1",
    name="scene connection to a missing method",
    family=GODOT_NAMES_FAMILY,
    config_section=GODOT_NAMES_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(CSHARP,),
    summary=(
        'A signal connection saved in a scene ([connection ... method="OnHit"]) targets '
        "a node whose C# class does not define that method: the connection fails when the "
        "scene loads."
    ),
    rationale=(
        "Connections made in the editor are stored by method name. Renaming the method in "
        "C# leaves the scene pointing at a name that no longer exists, and nothing fails "
        "until the scene is loaded."
    ),
    guarantees=GODOT_GUARANTEES_COMMON
    + (
        "Every [connection] of every scene whose target node has a C# script named after a "
        "project class: the method must be defined by that class, its partial "
        "declarations, or a project base class. Reported at the class's declaration. "
        "Lowercase snake_case methods (engine methods such as queue_free) are not judged."
    ),
    limitations=GODOT_LIMITATIONS_COMMON
    + " A method of an engine base class written in PascalCase is reported.",
    remediation=(
        "Reconnect the signal in the editor to the method's current name, or restore the method."
    ),
    noncompliant_example=(
        '[connection signal="body_entered" from="Hitbox" to="." method="OnHit"]\n'
        "// Player.cs defines OnBodyEntered, not OnHit"
    ),
    compliant_example="private void OnHit(Node2D body) { ... }",
)

GODOT004 = RuleSpec(
    rule_id="GODOT004",
    version="1",
    name="group nothing adds to",
    family=GODOT_NAMES_FAMILY,
    config_section=GODOT_NAMES_SECTION,
    default_severity=SEVERITY_REVIEW,
    implemented=True,
    languages=(CSHARP,),
    summary=(
        'A group read by name (GetTree().GetNodesInGroup("enemies"), IsInGroup, '
        "CallGroup) that nothing adds a node to: the read finds nothing."
    ),
    rationale=(
        "Groups are matched by string. A typo in either the read or the add makes the read "
        "empty, and an empty group looks like a level with no enemies, not like a bug."
    ),
    guarantees=GODOT_GUARANTEES_COMMON
    + (
        "Reads: GetNodesInGroup, GetFirstNodeInGroup, IsInGroup, CallGroup, CallGroupFlags "
        "(its second argument), NotifyGroup, SetGroup. Added: AddToGroup in the project's "
        "C#, groups=[...] on a node in any scene, and project.godot's [global_group]."
    ),
    limitations=GODOT_LIMITATIONS_COMMON
    + " A group added by a GDScript or an addon is reported, which is why this is a review.",
    remediation="Correct the name, or add the nodes to the group. " + GODOT_REMEDIATION_COMMON,
    noncompliant_example=(
        'foreach (var e in GetTree().GetNodesInGroup("enemy")) ...  // added as "enemies"'
    ),
    compliant_example="foreach (var e in GetTree().GetNodesInGroup(Groups.Enemies)) ...",
)

GODOT005 = RuleSpec(
    rule_id="GODOT005",
    version="1",
    name="undeclared signal name",
    family=GODOT_NAMES_FAMILY,
    config_section=GODOT_NAMES_SECTION,
    default_severity=SEVERITY_WARNING,
    implemented=True,
    languages=(CSHARP,),
    summary=(
        'A signal named as a string on the object itself (EmitSignal("Hit"), '
        'Connect("Hit", ...)) that the class does not declare: Godot reports an error '
        "when the line runs and nothing is emitted or connected."
    ),
    rationale=(
        "Godot's C# generator writes SignalName.X for every [Signal] delegate so the "
        "compiler checks the name; a string skips that check, and a renamed signal leaves "
        "the string behind."
    ),
    guarantees=GODOT_GUARANTEES_COMMON
    + (
        "EmitSignal, Connect, Disconnect and IsConnected with no receiver or a this "
        "receiver, whose first argument is a string: the class, its partial declarations "
        "or a project base must declare [Signal] delegate ... <Name>EventHandler. Lowercase "
        "snake_case names (engine signals such as body_entered) are not judged."
    ),
    limitations=GODOT_LIMITATIONS_COMMON
    + " A PascalCase signal declared by a GDScript base is reported.",
    remediation=(
        "Use SignalName.X, which the compiler checks, and declare the signal if it is missing."
    ),
    noncompliant_example=(
        'EmitSignal("Died");  // declared as [Signal] delegate void DeathEventHandler()'
    ),
    compliant_example="EmitSignal(SignalName.Death);",
)


RULES: tuple[RuleSpec, ...] = (
    MAGIC001,
    MAGIC002,
    EXC001,
    EXC002,
    EXC003,
    EXC004,
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
    VERIFY005,
    VERIFY006,
    STUB001,
    STUB002,
    ASSERT001,
    ASSERT002,
    BOOL001,
    STATE001,
    IMPORT001,
    ASYNC001,
    ASYNC002,
    ASYNC003,
    ASYNC004,
    PROCESS001,
    RESULT001,
    TYPE001,
    TYPE002,
    SLEEP001,
    RETRY001,
    BATCH001,
    STUB003,
    ROLE001,
    INPUT001,
    INPUT002,
    PROV001,
    GUARD001,
    MAGIC003,
    MAGIC004,
    MAGIC005,
    EXC005,
    EXC006,
    STATE002,
    STATE003,
    PROP001,
    PROP002,
    PROP003,
    PROP004,
    PROP005,
    PROP006,
    PROP007,
    PROP008,
    DOM001,
    DOM002,
    DOM003,
    DEAD001,
    DEAD002,
    DUP001,
    DUP002,
    CALL001,
    IMPORT002,
    GODOT001,
    GODOT002,
    GODOT003,
    GODOT004,
    GODOT005,
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
    "stubs": CATEGORY_CONTRACT,
    "assertions": CATEGORY_CONTRACT,
    "import_effects": CATEGORY_CONTRACT,
    "boolean_arguments": CATEGORY_STRUCTURAL,
    "module_state": CATEGORY_STRUCTURAL,
    "async_lifecycle": CATEGORY_CONTRACT,
    "processes": CATEGORY_CONTRACT,
    "results": CATEGORY_CONTRACT,
    "types": CATEGORY_CONTRACT,
    "sleep": CATEGORY_CONTRACT,
    "retry": CATEGORY_CONTRACT,
    "batches": CATEGORY_CONTRACT,
    ROLE_INTEGRITY_FAMILY: CATEGORY_POLICY,
    INPUT_FAMILY: CATEGORY_CONTRACT,
    CONSISTENCY_FAMILY: CATEGORY_CONTRACT,
    SENTINELS_FAMILY: CATEGORY_CONTRACT,
    "dom": CATEGORY_CONTRACT,
    PROPERTY_CONTRACTS_FAMILY: CATEGORY_CONTRACT,
    DEAD_CODE_FAMILY: CATEGORY_STRUCTURAL,
    DUPLICATES_FAMILY: CATEGORY_STRUCTURAL,
    IMPORT_BOUNDARIES_FAMILY: CATEGORY_STRUCTURAL,
    CALL_BOUNDARIES_FAMILY: CATEGORY_STRUCTURAL,
    GODOT_NAMES_FAMILY: CATEGORY_CONTRACT,
}


def category_of(rule_id: str) -> str:
    return FAMILY_CATEGORIES[get_rule(rule_id).family]


def needs_base_revision(rule: RuleSpec) -> bool:
    """Rules that compare a head revision with a base revision (diff / gate --base).
    VERIFY005 judges one revision, and a stub kept on purpose may be suppressed inline."""
    return rule.family == VERIFICATION_FAMILY and rule is not VERIFY005


def base_revision_rules() -> tuple[RuleSpec, ...]:
    """Implemented rules that only run in a revision comparison."""
    return tuple(rule for rule in implemented_rules() if needs_base_revision(rule))


def not_applicable_ids(language: str) -> frozenset[str]:
    """The rules that never run on ``language``: their family has no facts for it."""
    return frozenset(rule.rule_id for rule in RULES if language not in rule.languages)
