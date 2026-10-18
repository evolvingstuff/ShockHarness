# Complexity metrics, call graph and hotspots

Milestone E adds a second, **advisory** family next to the hard rules. Every
number here is reported under `metrics.complexity`, `metrics.graph` and
`metrics.history.hotspots`, can raise the warnings `CPLX001`-`CPLX006`, and
**never fails a plain `check`**. The only way complexity touches a verdict is
`gates.complexity_regressions = "fail"` in a revision diff (`diff`,
`gate --base/--head`), and then only for a unit whose number grew above its
threshold relative to the base revision. Hard violations are never averaged
with any of this; the report keeps the dimensions apart.

Each counting convention is versioned. The version string (`cyclomatic/1`,
`cognitive/1`, `nesting/1`, `npath/1`, `size/1`) is in every finding message
and in `metrics.complexity.conventions`, so a number can always be traced to
the rules that produced it. A change to a convention bumps its version.

## Units

The unit of measurement is a **unit**: the module body, each class body
(field initializers, static blocks, class-level statements), each function or
method (`def`, `async def`, generators, JavaScript function declarations and
expressions, methods, getters, setters, constructors), each `lambda` and each
arrow function. Every unit is measured separately and **a unit's numbers
exclude the bodies of units nested inside it**. The nested definition still
counts as one statement of its parent, and the expressions evaluated in the
parent (decorators, default values, a class's bases) belong to the parent.

This is a deliberate difference from tools that fold nested lambdas into their
parent: a reader can navigate to the nested unit, and the call graph records
the relationship. The consequence is documented under *Metamorphic
properties*: extracting code into a nested or sibling unit lowers the parent's
numbers, and the extracted unit carries them instead.

Comprehensions and generator expressions are **not** units; they belong to the
unit that contains them.

Units are named by their qualified name within the module (`Outer.inner`,
`K.m`, `f.<lambda>`, `handler.<anonymous>` for an unbound arrow, `<module>`).
`metrics.complexity.functions[].key` is `path::name`, with `#2`, `#3` ... for
further units of the same name in the file (several lambdas inside one
function); keys are stable across line moves and are what the revision diff
matches on.

## Control tree

Both adapters reduce a unit's body to one language-neutral **control tree**
(`ir/model.py`, `ControlNode`), and every metric reads only that tree. Two
units with the same tree get the same numbers whatever language they were
written in; the parity table in `tests/unit/test_complexity_metrics.py` and the
Hypothesis property in `tests/property/test_complexity_fuzz.py` (random
programs rendered to both languages must produce identical trees and numbers)
enforce it.

| Node | Python | JavaScript |
|---|---|---|
| `if` / `elif` | `if`, `elif` (detected from the `elif` keyword) | `if`, `else if` |
| `loop` | `for`, `async for`, `while`, comprehension `for` clause | `for`, `for..in`, `for..of`, `while`, `do..while` |
| `try` / `handler` / `try_else` / `finally` | `try` with `except` / `except*`, `else`, `finally` | `try`, `catch`, `finally` |
| `switch` / `case` | `match` / `case` (a `case _:` or capture-all arm is the default) | `switch` / `case` / `default` |
| `conditional` | `a if c else b` | `c ? a : b` |
| `expr` | every expression: counts `and` / `or` operators and runs | counts `&&` / `\|\|` / `??` operators and runs, `&&=` / `\|\|=` / `??=` |
| `recursion` | `f(...)` inside `f`, `self.m(...)` / `cls.m(...)` inside method `m` | `f(...)` inside `f`, `this.m(...)` inside method `m` |
| `jump` | never (no labels) | labeled `break` / `continue` |
| transparent | `with`, parentheses, `pass` | `with`, labels, plain `{}` blocks, parentheses |

Optional chaining (`o?.m()`) is never counted by any metric: it propagates
absence, it does not branch (the same reading `DEF004` takes). `not` / `!`,
comparisons and `assert` are not decisions.

## cyclomatic/1

`1 +` the number of decision points:

* each `if`, `elif` / `else if` (an `else` adds nothing);
* each loop and each comprehension `for` clause, and each comprehension `if`
  clause;
* each `except` / `catch` handler (`finally` and `try/else` add nothing);
* each `match` / `switch` arm other than the default arm;
* each conditional expression;
* with `complexity.cyclomatic_counts_boolean_operators = true` (the default),
  each binary short-circuit operator: `and`, `or`, `&&`, `||`, `??`, and each
  logical assignment `&&=`, `||=`, `??=`. Setting the key to `false` is
  reported as a policy deviation because the number then counts fewer
  decisions than the convention says.

```python
def f(a, b, c):                 # cyclomatic 5
    if a and b:                 # if +1, and +1
        return 1
    return c if b else [x for x in a if x]   # conditional +1, comprehension if +1
```

## cognitive/1

Implemented from the public description of cognitive complexity: structural
increments, nesting increments, and increments for interruptions of linear
flow. It is **not a SonarSource score**. The published algorithm leaves
several constructs to each implementation, and this convention also measures
nested units separately. The report says so in
`metrics.complexity.conventions.cognitive_note` and in every `CPLX002`
message.

* `+1` **plus the current nesting level** for each `if`, loop, `match` /
  `switch`, `except` / `catch` handler and conditional expression. Each of
  these raises the nesting level for everything inside it (its condition
  included).
* `+1`, **no nesting increment**, for each `elif` / `else if`, each `else`
  (of an `if`, and of a Python loop), and a Python `try/else` body. Their
  contents are nested one level deeper than the construct they belong to,
  exactly like the `then` branch.
* `+1` for each **maximal run of one short-circuit operator** in source order:
  `a and b and c or d` is two runs; `a and (b or c) and d` is three
  (parentheses start a new run); `a || (b || c)` is two.
* `+1` per logical assignment (`x ||= v`), `+1` per direct recursive call,
  `+1` per labeled `break` / `continue`.
* `try` bodies, `finally`, `with`, parentheses, plain blocks and `case` arms
  (beyond the `switch` itself) add nothing and do not nest.
* A nested unit is a separate unit: nothing of its body is counted here, and
  it does not raise the nesting level of its surroundings.
* A comprehension `for` clause adds nothing and does not nest (a generator
  expression is linear, idiomatic code); each comprehension `if` clause counts
  as an `if`.

```python
def f(items):              # cognitive 10
    total = 0
    for item in items:                 # +1 (nesting 0)
        if item.ok:                    # +2 (nesting 1)
            if item.value:             # +3
                if valid(item):        # +4
                    total += 1
    return total
```

Flat versus nested, the canonical pair: three sequential `if` statements score
3; three nested ones score 6 (`1 + 2 + 3`). The cyclomatic number is 4 in
both cases.

## nesting/1

The deepest chain of decision constructs: `if` (`elif` / `else if` and `else`
branches sit at the depth of the `then` branch), loops, `match` / `switch`
arms, `except` / `catch` handlers, conditional expressions and comprehension
`if` clauses. Wrappers add no depth: parentheses, `with`, plain blocks,
labels, `try` bodies, `try/else`, `finally`, comprehension `for` clauses. A
unit with no decision has depth 0; a single top-level `if` has depth 1.

## npath/1

A bounded estimate of the number of acyclic paths, computed bottom-up on the
control tree with **every intermediate value clamped to `complexity.npath_cap`**
(default 10000). Nothing is ever enumerated, so the cost is linear in the tree
however large the true number is.

| Node | Paths |
|---|---|
| block | product of its statements (empty: 1) |
| expression | `1 + operators`, times the paths of any conditional nested in it |
| `if` / `elif` | `(condition - 1) + then + else`, a missing `else` counting 1 |
| loop | `(condition - 1) + body + else`, the Python loop `else` taking the place of `else`, a missing one counting 1 |
| comprehension `for` | `(iterable - 1) + body` (an expression: no extra zero-iteration path); its `if` clauses count as `if` |
| `try` | `body * try_else + sum(handlers)`, then `* finally` |
| `match` / `switch` | `(subject - 1) + sum(arms)`, `+ 1` when there is no default arm; an arm is `(guard - 1) + body` |
| conditional | `(condition - 1) + then + else` |
| recursion, jump | 1 |

A result at or above the cap is reported as `">= cap"` with
`saturated = true`; the exact number is never claimed. The estimate counts
infeasible paths, treats a loop as one branch and does not prune paths after
an early return, so it overstates. It is useful as a growth signal, not as a
test-count.

```python
def f(a, b, c, d):          # npath 16: four independent decisions
    if a: ...
    if b: ...
    if c: ...
    if d: ...
```

## size/1

Auxiliary numbers, never a verdict.

* `logical_lines`: lines of the unit's span that carry code once the comments
  on them are blanked out, minus the lines of nested units. A nested `def` /
  `class` / function declaration gives up its whole span; a nested lambda or
  arrow gives up only its interior lines, because its first and last lines
  usually carry the parent's code too (a one-line lambda is therefore counted
  in both). Docstrings are code lines.
* `parameters`: the unit's own parameters, receivers (`self`, `cls`) included,
  `*args` / `**kwargs` / rest parameters counted once each; 0 for module and
  class bodies.
* `statements`: statements of the unit's own body (Python: every `ast.stmt`;
  JavaScript: every statement and declaration node, blocks and labels being
  transparent). A nested definition counts as one statement of its parent.

## Rules CPLX001-CPLX004 and CPLX006

| Rule | Fires when | Threshold key (default) |
|---|---|---|
| `CPLX001` | `cyclomatic > cyclomatic_warn` | `complexity.cyclomatic_warn` (15) |
| `CPLX002` | `cognitive > cognitive_warn` | `complexity.cognitive_warn` (15) |
| `CPLX003` | `nesting > max_nesting_warn` | `complexity.max_nesting_warn` (4) |
| `CPLX004` | `npath >= npath_warn`, or saturated at `npath_cap` | `complexity.npath_warn` (200), `complexity.npath_cap` (10000) |
| `CPLX006` | `size.logical_lines > max_lines_warn`; module bodies exempt | `complexity.max_lines_warn` (50) |

`CPLX006` (0.2.0) is the length check every code-review standard has: the
longest units on a real codebase were also its worst (346, 466 and 273 logical
lines), and length is the coarsest, most legible signal. Module bodies are
exempt because a module is a container whose length is the sum of what it
holds. The count is `size/1` as defined above (nested units excluded,
docstrings counted), so extracting a helper lowers the parent's count by the
lines it gave up.

**NPath folded into cognitive** (`complexity.npath_only_without_cognitive`,
0.2.0, default `true`). NPath explodes on long sequences of independent `if`s
(a 466-line dispatcher scores `>= 10000` even when every branch is trivial)
and mostly repeats what cognitive complexity says with less resolution. When a
unit is above both `cognitive_warn` and `npath_warn`, it is reported once, as
`CPLX002`, with the NPath estimate in the same message; a unit above the NPath
threshold alone is still `CPLX004`. With the option `false` both findings
appear. `metrics.complexity.functions[].npath` is unchanged either way, and
revision diffs still compare NPath per unit.

Every finding is a `warning`, anchored on the unit's first line with the unit
as its `scope`, and its message names the measured value, the threshold and
the convention version (the `CPLX002` line also carries the NPath number when
`CPLX004` was folded into it):

```text
src/a.py:1:1: CPLX002 warning: cognitive complexity of function f is 17, above cognitive_warn = 15 (convention cognitive/1; not a Sonar score)  [def f(a, b):]
```

They can be disabled per path with `[[overrides]]` and suppressed inline on
the unit's first line like any finding. `complexity.enabled = false` turns
the whole family off; the report then says `metrics.complexity.status =
"disabled"` and lists the six rules under `rules_disabled` for every file.

## Call graph (`metrics.graph`)

Every call site of every unit becomes an edge with a **confidence**, and the
report counts edges and call sites per confidence. An unresolved call is
never presented as resolved.

| Confidence | Meaning |
|---|---|
| `resolved` | a direct call of a name that is a function or class defined in the module (or nested in the caller), or a name bound by an import: the target is the unit when the imported module is among the analyzed files and defines that name, an `external` symbol otherwise. In Python also a method through an exact receiver (`docs/proposal-receivers.md`, R1): `self.m()` / `cls.m()` that the class or a project base defines when no analyzed subclass overrides `m`; a module-level singleton bound once to a constructor (`store.save()`, imported or not); a local the function constructs once; `Class.m()`; and an attribute call on an analyzed module alias (`u.helper()`) |
| `probable` | an attribute call on a JavaScript module alias (`ns.helper()`, `u.helper()` after `const u = require(...)`) or on an external Python one (`os.path.join`), a `self.m()` / `this.m()` call that the enclosing class body defines and an analyzed subclass overrides (or, in JavaScript, may), a call through a Python import the module rebinds, a static call on a JavaScript module-level class, or a known function passed as an argument (higher-order use: whether it is called is not known) |
| `unresolved` | a computed callee (`o[k]()`, `getattr(o, n)()`, `f()()`, `(c ? f : g)()`), a method call on a parameter, local or other value of unknown type, an unbound name, or an attribute of `self` / `this` that the class body does not define (inherited, assigned or dynamic) |

Targets are `unit` (a key in `metrics.complexity.functions`), `external` (a
symbol such as `requests.get` or `src/util.js::helper` for a name an analyzed
module re-exports but does not define), `builtin` (Python builtins, a fixed
list of JavaScript globals such as `console`, `Math`, `JSON`, `fetch`;
resolved but excluded from fan-out) or `unresolved` (the callee as written).

Per unit, `metrics.graph.units[]` reports `fan_in` (distinct units with a
resolved or probable edge into it), `fan_out` (distinct analyzed-unit targets),
`fan_out_external`, `fan_out_total` and the number of call sites per
confidence. Edges with the same source, target, confidence and kind are
aggregated with a `calls` count and the first call's span.

Module edges (`metrics.graph.module_edges`) come from Python `import` /
`from ... import` (absolute and relative) and JavaScript `import`, `export ...
from`, `export * from` and `require(...)` with a literal specifier. They are
`resolved` (the target is an analyzed file), `external` (a package that is not
analyzed, including the standard library) or `unresolved` (`import(expr)`,
`require(variable)`, a relative target that is not among the analyzed files,
or a relative import climbing above the root). A Python module's absolute
name starts at the first directory on its path that has an analyzed
`__init__.py` (`src/pkg/mod.py` is `pkg.mod`); names are never matched by
suffix, so `import json` is external even when a file called `json.py` is
analyzed. `from pkg import mod` where every imported name is a submodule is an
edge to the submodules, not to the package `__init__`.

`metrics.graph.cycles` lists the strongly connected components of two or more
modules over resolved module edges (Tarjan, iterative), each with the import
that closes the cycle from every member. `metrics.graph.shared_mutable_state`
lists module-level mutable bindings (containers, `let` / `var`, names declared
`global`) written from more than one unit, as approximate notes.

### CPLX005

Fires once per **cycle** (0.2.0; 0.1.0 fired once per member, which let a
75-module JavaScript cycle drown two five-module Python cycles) and once per
unit whose `fan_out_total` is above `complexity.fan_out_warn` (default 20; 30
in the `recommended` profile, where the fan-out finding is `review` under
`fan_out_severity = "review"` instead of a warning). Shared mutable state is
a note in `metrics.graph`, not a finding.

A cycle finding is anchored on the lexically first member of the cycle, at its
import into the cycle, so its fingerprint does not change when unrelated
modules are added or when the other members move; if `CPLX005` is disabled
for that member by an override, the first member where it is active carries
the finding. The message says how many modules take part and in which
language, lists up to eight members (then `... and N more`; the full
membership is always in `metrics.graph.cycles`), names the import that enters
the cycle, and notes that a Python cycle fails at import time whereas an
ES-module cycle is usually resolved at call time. For the same reason the text
report lists Python cycles before JavaScript cycles, as a group after the
per-file findings; JSON findings keep their path order.

## Hotspots (`metrics.history.hotspots`)

For every analyzed file with history: `score = log1p(churn) *
normalized_complexity`, where `churn` is the file's commit count inside the
history horizon and `normalized_complexity` is the file's summed cognitive
complexity (`metrics.complexity.files[path].cognitive_total`) divided by the
largest such total among the analyzed files. File granularity, sorted by
score. It needs both history and complexity: outside a repository, without
git, or with `complexity.enabled = false`, `hotspots` is `null` and
`hotspots_reason` says which input is missing. Hotspots never gate.

## Revision diff

`diff` and `gate --base/--head` compare each head unit with the unit of the
same key at base. `metrics.complexity.regressions` lists every head unit that
is above a threshold **and** whose value grew (a unit absent at base counts
as grown from nothing). `gates.complexity_regressions` decides what that means:
`warn` (default) adds a gate reason and nothing else, `fail` fails the gate
(exit 1), `ignore` says nothing. The findings themselves are still warnings
and still appear as `new` / `fixed` / `unchanged`.

### Abstraction displacement (experimental, off by default)

`complexity.abstraction_displacement = true` adds, in diff mode only,
`metrics.graph.abstraction_displacement`: units whose own cognitive score fell
between base and head while the cognitive score summed over everything
reachable from them through **resolved** call edges grew. It is the
measurable part of the heuristic in the specification: work that moved out of
sight rather than away. Every entry carries `confidence: approximate` and
`experimental: true`, there is no rule ID for it, and delegation is not
declared bad by it; probable and unresolved edges are not followed, so a
helper reached through a JavaScript module alias is invisible to it.

## Metamorphic properties

The tests pin what a refactoring may and may not do to the numbers:

* **Whitespace and renaming** change nothing but `logical_lines`, which is a
  line count by definition.
* **Extracting a helper** (top-level block or loop body) keeps the file's
  summed cognitive score at or above the original minus the helper's own
  score, keeps the verdict, and adds a resolved edge and one to the caller's
  fan-out. Extracting code that sits two or more decision levels deep *does*
  lower the file sum by the nesting increments it no longer pays, which is the
  point of the metric; the graph still records the delegation.
* **Splitting a function into sequential helpers** keeps the summed score and
  grows the graph by exactly the number of new calls; the architecture
  assessment moves to fan-out instead of disappearing.

## What is not measured

Nothing here proves correctness. The call graph is static and best effort
(see `docs/limitations.md`); per-function churn, rename following, data flow,
interface quality and change-impact radius are post-v1 research (Milestone
H in the specification).
