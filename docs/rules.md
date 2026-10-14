# Rules

`shockharness rules list` prints every registered rule with its status;
`shockharness rules explain <ID>` prints the full description. This page is the
same information for the implemented rules, plus the planned set.

Severities: `error` fails the gate (unless suppressed or the gate is set to
`warn`); `warning` and `review` are reported and counted but never fail; `note`
is informational.

## Implemented

### MAGIC001: numeric literal outside 0/1 (error, Python and JavaScript)

Every numeric literal in executable code must be exactly `0` or `1`.

**Detection guarantees.** Exact on numeric AST nodes: Python `int`, `float`,
`complex` constants; JavaScript `number` tokens including BigInt. Value-based:
`0x1`, `1.0`, `1e0`, `0b0`, `1n`, `0j` pass. A chain of unary `+`/`-` over a
literal is checked as one unit: `-1` fails unless `allow_unary_negative_one` is
true; `-0` and `-0.0` always fail; `- -1` folds to `1` and passes. Python
booleans are never flagged. Literals in Python type annotations (`Literal[2]`)
are flagged and labelled. `match`/`case` patterns, JSX attribute expressions,
and template substitutions are executable code and are scanned.

**Limitations.** Strings and regular-expression literals are not numeric nodes:
`"30"` and `/\d{3}/` are not flagged. Numbers built at runtime (`int("30")`)
are not detected. `NaN` and `Infinity` are identifiers. Files that do not parse
are reported as parse failures, never as clean.

**Configuration.** `rules.magic_numbers.*`; see `docs/configuration.md`.
Files matching `configuration_files` skip this rule and say so in the report.

**Remediation.** Find the contract behind the value. Variable policy (timeouts,
limits, sizes) becomes a required, validated configuration parameter. Invariant
mathematics or a published specification value becomes a named constant that
cites its source. Never move the number into an unexplained constant and never
add a fallback. A `0` or `1` that carries meaning (an exit code, a sentinel)
deserves a name too, even though the rule permits it.

### SUPP001: invalid suppression comment (error)

A comment containing `shockharness:` that is not exactly
`shockharness: ignore[RULEID[, RULEID]] reason="non-empty"`, or names an
unknown rule, or has an empty reason. Under `--no-inline-suppressions`, every
suppression comment is reported as SUPP001.

### SUPP002: unused suppression comment (warning)

A valid suppression whose rule produced no finding on that line. A suppression
for a disabled or unimplemented rule is reported as unused because it did
nothing.

## Registered, not implemented

These IDs are reserved and configurable now; they produce no findings and are
listed in every report under `coverage.rules_not_implemented`.

| ID | Name | Planned milestone |
|---|---|---|
| MAGIC002 | suspicious string literal (advisory) | post-B |
| EXC001 | forbidden catch | C |
| EXC002 | suppressed or converted exception | C |
| EXC003 | broad try scope / unverified boundary | C |
| DEF001 | function parameter default | D |
| DEF002 | missing mapping/object fallback | D |
| DEF003 | truthiness fallback | D |
| DEF004 | nullish fallback | D |
| DEF005 | exception-to-default | D |
| DEF006 | implicit configuration fallback | D |
| CPLX001 | cyclomatic complexity | E |
| CPLX002 | cognitive complexity | E |
| CPLX003 | nesting depth | E |
| CPLX004 | NPath estimate | E |
| CPLX005 | coupling / cycles | E |

## Rule metadata contract

Each rule has an immutable ID, a version (bumped when detection semantics
change), a default severity, a summary, rationale, detection guarantees,
limitations, remediation guidance, and compliant/non-compliant examples. All of
this is in `src/shockharness/rules/registry.py` and printed by `rules explain`.
