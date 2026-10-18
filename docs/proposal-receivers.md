# Proposal: resolving method calls through their receivers

Status: **R1 (Python) built (2026-10-18), on Tom's position below; for Fable to confirm or
change. R2 (JavaScript) and R3 (annotations) are not started.** Measured: STATUS.md,
"Receivers R1".

## The problem

A call through a method is `unknown` to property contracts: `store.get(x)`,
`self.cipher.redact(x)`, `Auth.init()`. The property contracts spec draws the line on
purpose (§5.3): this family "does not attempt to improve resolution", because
"improvements to resolution belong to the call graph, not to this family". This proposal
keeps that line. Receiver resolution goes into the shared call graph
(`src/shockharness/complexity/callgraph.py`), and every rule that reads the graph gains
from it, property contracts included.

Today the graph classifies an attribute call like this:

| Call | Confidence today |
|---|---|
| `self.m()` / `this.m()`, `m` defined in the enclosing class body | probable ("overriding is not ruled out") |
| `ns.f()` on a module alias, `C.m()` on a module-level class | probable |
| `x.m()` on a parameter or local | unresolved ("unknown type") |
| `store.m()` on a module-level value | unresolved ("unknown type") |
| `self.attr.m()`, `f().m()` | unresolved |

PROP001 and ASYNC001 treat a probable edge as `unknown`. INPUT001, PROV001 and
GUARD001 follow resolved and probable sites. CPLX005 counts both in fan-out.

## Measured on MetaList (2026-10-18, read-only)

Two scratch scripts (AST for Python, tree-sitter for JavaScript) classified every
attribute call in MetaList's production code. "Resolvable" means the receiver's class or
object is a project definition that defines the method. The scripts approximate: they
do not check rebinding, and they follow only one level of inheritance by name.

**Python** (`app/` and `main.py`: 281 modules, 494 classes, 48 module-level singletons,
8,356 attribute calls):

| Receiver | Calls | Resolvable |
|---|---|---|
| a local or parameter of unknown type (mostly `str`, `list`, `Path`) | 3,892 | — |
| a module alias, external (`re.compile`) | 891 | — |
| `self.m()`, `m` defined in the class | 738 | 738 |
| **a module-level singleton, imported** (`reminder_store.bootstrap()`) | **648** | **648** |
| a chain or subscript | 458 | — |
| a call result | 382 | — |
| `self.attr.m()`, the attribute's type unknown | 350 | — |
| a string literal (`"\n".join`) | 249 | — |
| a parameter annotated with a project class (`state: AuditState`) | 175 | 138 |
| an imported name, external | 170 | — |
| a local built by a project constructor (`state = AuditState()`) | 135 | 111 |
| a static or class method (`SafeSession.allow_reads()`) | 99 | 92 |
| `self.m()`, `m` not in the class (inherited from a library) | 60 | — |
| `self.attr.m()`, the attribute built or annotated as a project class | 47 | 47 |
| a module-level singleton, same module | 29 | 29 |
| a module alias, project | 24 | — |
| `C(...).m()` | 8 | 8 |
| `self.m()` inherited from a project base | 1 | 1 |

About **1,810** calls are resolvable. Singletons (677) and `self` methods (739) make up
four fifths of them.

**JavaScript** (`app/static/js`, vendor excluded: 234 modules, 51 classes, 107
module-level objects or singletons, 10,746 member calls):

| Receiver | Calls | Resolvable |
|---|---|---|
| a local, parameter or global of unknown type (`document`, `response`) | 5,793 | — |
| `this.m()` in a class | 1,554 | 1,154 |
| another expression (`el.classList.add`) | 1,203 | — |
| **a module-level object, imported** (`Auth.init()`, `ModeManager.init()`) | **963** | **962** |
| a call result | 384 | — |
| `this.field.m()` | 301 | — |
| a namespace import, project (`Logger.logDebug`) | 233 | 233 |
| `this.m()` in an object literal | 223 | 223 |
| a module-level object, same module | 85 | 1 |
| an imported binding, other | 7 | — |

About **2,570** calls are resolvable. MetaList's JavaScript is built from exported
object literals (`export const Auth = { init() {...} }`), so the imported-object case
is the largest after `this`.

**The third-party corpus** (the installed pip, `_pytest`, hypothesis, build and
hatchling, tests excluded: 672 modules, 1,362 classes, 21,681 attribute calls; and npm's
`lib`, 110 modules):

| Receiver | Python calls | Resolvable |
|---|---|---|
| `self.m()`, `m` defined in the class, no analyzed subclass overrides it | 2,331 | 2,331 |
| `self.m()`, inherited from a project base | 192 | 192 |
| `self.m()`, overridden in an analyzed subclass | 115 | 115 |
| a parameter annotated with a project class | 639 | 617 |
| a static or class method | 374 | 361 |
| a local built by a project constructor (including `with C() as x`) | 341 | 321 |
| `self.attr.m()`, the attribute built or annotated as a project class | 186 | 149 |
| a module-level singleton (same module and imported) | 56 | 49 |
| `C(...).m()` | 33 | 31 |

About **4,170** calls are resolvable. Libraries differ from MetaList in one way that
matters: singletons are rare (49 against MetaList's 677), and `self` methods and
annotations carry the weight. 115 `self.m()` calls (4%) go to a method an analyzed
subclass overrides, which is what keeps those probable. npm's `lib` is CommonJS
(`require`), which the scratch script does not follow; of its 321 `this.m()` calls in a
class, 230 are defined in the class.

## What to resolve, and at what confidence

Each kind needs a reason it cannot be wrong, or it stays probable.

1. **Module-level singletons and objects** (Python 677, JavaScript 963).
   * Python: `name = C(...)` at module level.
   * JavaScript: `const name = new C()`, an object literal, or `Object.freeze({...})`.
   * **Resolved** when the name is bound exactly once in its module, never written
     through `global` or reassigned, and either used in that module or imported by name.
   * The target is `C.m`, or the object literal's method.
   * A JavaScript object whose method is assigned later (`Auth.showLoginModal = ...`)
     stays unresolved.
2. **`self.m()` / `this.m()`** in a class that defines `m` (Python 739, JavaScript 1,154).
   * **Resolved** when no analyzed subclass overrides `m`. This is a closed world over the
     analyzed files. A subclass outside them (a library's user) is not seen, and the edge's
     reason says so.
   * **Probable** when an analyzed subclass overrides it, as today.
3. **A local built by a constructor** (Python 111 plus 8 `C(...).m()`).
   * **Resolved** when the local is bound once in the unit.
4. **Static and class methods**, and **namespace imports** (Python 92 plus 24,
   JavaScript 233). The target is exact when the class or module defines the name.
   * **Resolved**. Today they are probable for no reason that applies to them.
5. **Annotations** (Python 138 parameters plus 47 attributes).
   * An annotation is a claim that only a type checker verifies, and MetaList configures
     none (decision 33). So: **probable** by default.
   * **Resolved** only when the project configures a checker, if decision 33's detection
     lands.
6. **`this.m()` in an object literal** (JavaScript 223).
   * `this` depends on how the method is called (`const f = Auth.m; f()` loses it).
   * **Probable**.

The unknown-type locals and parameters (3,892 and 5,793) stay unresolved. They are
mostly builtin values (`str.strip`, `document.getElementById`) that no project contract
applies to.

## What the rules would see

* **Property contracts.** A resolved method call is checked against the method's
  contract. Arguments map past the receiver: argument `i` of `obj.m(...)` is parameter
  `i + 1` of an instance method, and of a class method; for a static method it is
  parameter `i`.
  * A `requires` on `self` itself is the spec's open question 3 (typestate). It stays out
    of scope here.
  * Results compose as they do for functions.
  * Every unknown finding that becomes a pass or a violation is the measure the spec asks
    for.
* **ASYNC001.** A promoted `self.m()` edge to an `async def` turns an `unknown` finding
  into a violation. **This can make a passing gate fail** if ASYNC001 gates. It needs a
  corpus measurement and a changelog note, like decision 34.
* **INPUT001, PROV001 and GUARD001** follow more sites: more findings, possibly new
  ones.
* **CPLX005 fan-out** counts more edges. Units near the threshold may start to warn.
* **Cache.** The graph changes, so the cache schema moves.

## Suggested milestones

* **R1 (Python):** singletons, `self` methods with the subclass check, constructed locals,
  static and class methods; the argument offset in property contracts. Measured on
  MetaList and the third-party corpus, with every rule's finding diff, before it ships.
* **R2 (JavaScript):** imported objects and singletons, `this` in classes, namespace
  imports.
* **R3, if decision 33 lands:** annotations resolve when a checker is configured.

## Questions for Fable and Tom

Tom's position (2026-10-18), for Fable to confirm or change:

1. **Closed world: yes.** `self.m()` is resolved when no analyzed subclass overrides `m`,
   and the edge's reason says "no override among the analyzed files".
2. **No switch.** The promotions ship in the next release with a changelog note, as
   decision 34 did, after the finding diff on MetaList and the corpus is measured and
   recorded.
3. **Annotations: probable** without a configured type checker, resolved with one.
4. **The corpus: measured** (above), before R1.

The questions as asked:

1. Is a closed world over the analyzed files acceptable for promoting `self.m()` to
   resolved? Or should it be resolved only for classes the project does not export or
   publish?
2. Should promotions that can add findings to gating rules (ASYNC001, INPUT001) ship
   behind a switch for one release? Or should they ship directly, with a changelog note?
3. Are annotations probable without a configured type checker, and resolved with one?
4. Should the third-party corpus get the same receiver count before R1, to check that
   MetaList is typical?
