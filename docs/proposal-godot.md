# Godot support: GDScript as a fourth language

Status: **proposed (2026-10-19), waiting for Tom's decisions** (questions at the end).
Tom is starting a game in Godot. Nothing has been built and no package has been added.

## Recommendation in one paragraph

Support **GDScript first**, as a fourth language `gdscript` with its own extractors,
parsed with the `tree-sitter-gdscript` grammar (MIT). It would be an **optional extra**,
`shockharness[godot]`, pinned exactly, because its only PyPI release comes from a
third-party fork and has wheels for three platforms (part 2). GDScript
is not in the JavaScript family the way TypeScript is. Add a small **stdlib reader for
Godot's text files** (`project.godot`, `.tscn`, `.tres`), with no new package, because a
Godot project's callers, names and configuration live in those files, not in the code.
Turn rules on for GDScript one family at a time, each with fixtures and a measurement.
The report lists the rules that did not run on `.gd` files, so a GDScript file never
looks clean for a rule that does not apply to it. **Defer C#.**

## 1. Which languages

| | GDScript | Godot C# |
|---|---|---|
| Share of Godot projects | most of them; the editor's default, and what the docs, demos and tutorials use | about 16% in the 2025 community poll, as reported by secondary sites (the official results were not checked) |
| Parser | `tree-sitter-gdscript` (one new package, see 2) | `tree-sitter-c-sharp` (a different new package) |
| Extractor work | a new extractor family, smaller than JavaScript's: no exceptions, no promises, no DOM, one class per file | a new extractor family closer to Java: exceptions, `async`/`Task`, LINQ, generics. As large as the JavaScript one |
| Rule fit | numbers, defaults, complexity, dead code; exceptions do not exist | nearly every rule, exceptions included |
| Godot specifics | the same in both: scene connections, `@export`/`[Export]`, engine callbacks, node paths | |
| Platform | everywhere Godot exports | no web export for C# projects in Godot 4 (the 4.7 docs still say so) |

**Recommendation: GDScript only.** C# would roughly double the work for a minority of
Godot projects, and Tom's game will be GDScript unless he says otherwise (question 2).
The Godot project model (part 4, G2) is language-independent and would serve C# later.

## 2. The parser

Everything below was checked on 2026-10-19 against PyPI's JSON API, GitHub and the source.

| Option | Facts | Verdict |
|---|---|---|
| **`tree-sitter-gdscript` 6.1.0** (PyPI) | MIT. Language ABI 14, which our pinned core (`tree-sitter>=0.25.1,<0.26`) accepts (0.25 loads ABI 13-15). abi3 wheels for **macOS arm64, manylinux x86_64 and Windows x64 only**: macOS x86_64, Linux aarch64 and musl build from the sdist and need a C compiler. **Its only release (2026-09-04) was published by a third party**: the PyPI provenance names the Trusted Publisher `repowise-dev/tree-sitter-gdscript`, a fork made that day, whose newest commit is from 2026-07. Upstream's own PyPI publishing is still an open pull request (PrestonKnopp/tree-sitter-gdscript#91). So the wheel lacks upstream fixes since July, among them `%` node paths (#99, 2026-10-18) | **Recommended, with conditions**: an exact pin; before adoption, the sdist compared with upstream's source at the matching commit; and a move to the upstream package once #91 lands |
| Upstream grammar (PrestonKnopp/tree-sitter-gdscript) | MIT. Maintained by Preston Knopp, with contributions from GDQuest. Last commit 2026-10-18, 7 open issues, two of them new precedence bugs (`as`, #101; `**`, #102). Its corpus covers the Godot 4 syntax we need: annotations (`@export`, `@onready`, `@tool`, `@abstract`), `:=`, `Array[T]` and `Dictionary[K, V]`, lambdas, `await`, `static func`, `class_name`, `enum`, `signal`, inner classes, both setter/getter forms, `&"name"`, `$` and `%` node paths, `match` with `when` guards, and variadic `...args` (4.5). Not checked: `super` (probably an ordinary call) and typed signal arguments | the grammar itself is sound; only its Python distribution is the problem |
| `tree-sitter-language-pack` 1.22.1 | MIT, includes GDScript, the Godot resource grammar and C#. Its README says grammars are **fetched at first use** | rejected: a network download at run time is not acceptable for a deterministic gate |
| `tree-sitter-languages` 1.10.2 | no release since 2024-02, incompatible with py-tree-sitter 0.22 and later | rejected: dead |
| gdtoolkit 4.5.0 (gdlint/gdformat) | MIT, pure Python, so it installs everywhere, on a Lark parser (`lark==1.2.2`); covers Godot 4.5 syntax. No commits since 2025-10. Two packages, and a parse tree unlike tree-sitter's, so no shared node helpers, spans or error recovery | the fallback if Tom rejects the PyPI grammar: it costs two packages instead of one, and parsing is slower |
| Our own wheel of the upstream grammar | it would make ShockHarness ship compiled code and a package of our own to maintain | not recommended |

**Why an optional extra and not a fourth runtime dependency.** The wheel gaps would make
`pip install shockharness` need a C compiler on Intel Macs and Linux ARM for every
Python and JavaScript user, for a language most of them never use. With the extra, a
project whose `include` matches `.gd` files but lacks the extra gets those files as
unsupported sources, with "install `shockharness[godot]`" in the message. They are never
reported clean. The extra is the first in the project, and it needs Tom's approval like
any package.

**Scene and resource files need no package.** The Godot resource grammar
(`tree-sitter-godot-resource` 0.7.0) is not on PyPI. The `.tscn`/`.tres`/`project.godot`
text format is simple. Each section header is one line of `key=value` pairs:
`[gd_scene]`, `[ext_resource path=... id=...]`, `[node name=... parent=... instance=...
groups=[...]]`, and `[connection signal=... from=... to=... method=...]`, as written by
Godot's `resource_format_text.cpp`. Property values are Variant literals, which can span
lines. A stdlib reader of a few hundred lines needs only a string- and bracket-aware value
scanner, and can skip most property values. `project.godot` has the same format
(`[autoload]` holds `Name="*res://path"`).

## 3. How each rule family maps onto GDScript

GDScript facts that drive the mapping. Each `.gd` file is one class: it `extends` an
engine class (`Node` by default for most scripts, `RefCounted` with no `extends`), and
`class_name` makes it a global name with no import. There is no `try`/`except`: errors are
`Error` return codes (`OK`, `ERR_*`), `null` returns, `push_error()` lines in the log, and
`assert()`, which release exports strip. `and`/`or` always produce a bool, never an
operand, as the bytecode generator shows, so `a or b` is not a value fallback. Godot's own
warnings already cover unused variables, unreachable code, `MISSING_AWAIT`,
`RETURN_VALUE_DISCARDED` and the typing warnings. The last two families are ignored by
default, and no warning fails an export.

| Family | GDScript shape | Plan |
|---|---|---|
| **MAGIC001** numbers | Numbers are everywhere in game code: `Vector2(320, 180)`, `Color(1, 0.5, 0)`, `lerp(a, b, 0.1)`, `create_timer(0.5)`. The remedies are the language's own: a top-level `const SPEED = 300.0` (Godot's own CharacterBody2D template writes `const SPEED = 300.0` and `const JUMP_VELOCITY = -400.0`), an `@export` variable the designer tunes in the editor, a `Marker2D` in the scene for a position, and the engine's named values (`Vector2.UP`, `Color.RED`) | **G1.** A script's top level is module level. Covered as named definitions: `const NAME = <literal arithmetic>`; `const NAME = Vector2(...)`/`Color(...)`/`Rect2(...)` with literal arguments (a built-in value type, which GDScript allows in a `const`); explicit `enum` values; and the initializer of an `@export` variable (question 3). Everything else is reported, as in Python. Values set in `.tscn` files are data and are never scanned. The remediation text names the Godot remedies |
| MAGIC002 repeated strings | GDScript is full of strings that are really names: input actions (`"jump"`), groups, animation names, node paths, method names | **G3**, then replaced for the names Godot defines by the G4 rules (a name checked against its definition is better than a name repeated) |
| MAGIC003-005 | apply as written | G3 |
| **EXC001-005**, EXC004 | no `try`, no `finally`: **not applicable**, listed as such | Silent failure takes other shapes in GDScript: a discarded `Error` (RESULT001), an error answered with `push_error()` and carrying on (EXC002's spirit; candidate rule), `get_node_or_null` and `as` casts that give `null` |
| **DEF001** parameter defaults | `func hit(damage := 10)`, `func f(x = null)` | G3, as written |
| DEF002 lookup fallbacks | `dict.get(k, d)`, `get_meta(name, d)` | G3 |
| DEF003 truthiness | `x if x else y`. `a or b` gives a bool in GDScript, so it is not a fallback and is not reported | G3 |
| DEF004 nullish | `x if x != null else y`, `if x == null: x = y`, `get_node_or_null(...)` followed by a substitute | G3 |
| DEF005 exception to default | no exceptions; the analogue is `if err != OK: return <default>` | G3, as a new GDScript shape of DEF005 |
| DEF006 configuration | `ProjectSettings.get_setting(name, default)`, `ConfigFile.get_value(section, key, default)` (settings and save files), `OS.get_environment` | G3 |
| **CPLX001-004, CPLX006** | `if`/`elif`/`else`, `for`, `while`, `match`, ternaries, `and`/`or`, lambdas. Large `_process`/`_physics_process` state machines are where game code gets complex | **G1**, as written |
| CPLX005 coupling and cycles | the module graph is `extends`, `preload`/`load` of `res://` paths, `class_name` uses and autoload names | G2 |
| **Call graph** | `f()` and `self.f()` in the same script; `super.f()`; `extends` chains (a path or a `class_name`); `ClassName.f()` for static functions; typed receivers (`var p: Player`); autoload names; later `$Node.f()` through the scene the script is attached to. The rest stays unresolved, as today | G2 |
| **DEAD001/002** | See below: today's roots would hide everything | **G2** |
| ASSERT001/002 | `assert()` is removed from release exports, so an assert that checks a save file or network input is gone in the shipped game | G3; ASSERT002 becomes "behavior relies on asserts", since every release export strips them |
| RESULT001 must-use | Godot's `RETURN_VALUE_DISCARDED` is off by default and covers every return. ShockHarness's catalog names the ones that carry failures, the `Error` returns thrown away: `connect`, `ResourceSaver.save`, `DirAccess.make_dir_recursive_absolute`, `change_scene_to_file`, `HTTPRequest.request`, `JSON.parse`; `FileAccess.open` returning `null` unchecked | G3, a `gdscript_must_use` catalog |
| ASYNC001 | a coroutine (a function with `await`) called without `await`. Godot has a `MISSING_AWAIT` warning | G3, only if measurement shows the engine's warning misses cases; otherwise G5 makes sure the warning is on |
| ASYNC002/003, DOM001/002, PROCESS001, RETRY001, BATCH001, IMPORT001 | no equivalent, or very rare in games (`OS.execute`) | not applicable; IMPORT001's nearest shape is `static var x = f()` and `_static_init()` |
| BOOL001, STUB001-003 | `add_child(node, true)`; `pass` bodies, `push_warning("TODO")`; `preload("res://test/...")` in game code; `func is_valid(): return true` | G3 |
| SLEEP001 | in tests (`await wait_seconds(1)` in GUT, `await_millis` in gdUnit4). In game code a timer is gameplay, so production code is excluded | G5 |
| STATE001/002 | no module globals; the shared state is autoload members and `static var` | later |
| TYPE001/002 | untyped `var`, `Variant`, `as` casts and `@warning_ignore("unsafe_...")`. Godot's own warnings already check typing; what they cannot do is make it stick | G5: read the `debug/gdscript/warnings/*` levels in `project.godot`; report a project that types its code while the warnings that enforce it are off or not errors (TYPE002's shape), and a change that lowers one (VERIFY003's shape) |
| SUPP, VERIFY001-004, ROLE001 | `@warning_ignore(...)` and `# gdlint:` comments are suppressions; GUT `pending()` and skipped scripts, gdUnit4 skips are skip markers; `assert_eq(x, x)` is a neutralized assertion; a test file is one whose class extends `GutTest` or `GdUnitTestSuite` | G1 for ShockHarness's own suppression comments; the rest G5 |
| INPUT001/002 | the game's remote input is `@rpc` function parameters, `HTTPRequest` bodies and save files in `user://` (players edit them); sinks are `load(path)`, `Expression.execute`, `bytes_to_var_with_objects`, `OS.execute` | later, only if the game has multiplayer or loads user content |
| **PROP001-008** property contracts | the runtime would be a `class_name Contracts` script with static `requires`/`produces`/`preserves` | later; nothing in a first game needs it |

### Dead code: the game-specific problem

DEAD001's roots today include **every method of a class derived from a class the project
does not define** (`framework_method` in `rules/dead_code.py`): a framework calls those.
Every GDScript script extends an engine class, so as it stands every method of every
script would be a root and DEAD001 would never report anything on Godot code. GDScript
needs its own roots instead, which are the callers the code does not show:

* **Engine callbacks**: `_ready`, `_process`, `_physics_process`, `_input`,
  `_unhandled_input`, `_enter_tree`, `_exit_tree`, `_notification`, `_init`, `_draw`,
  `_gui_input`, `_integrate_forces`, `_get`/`_set`/`_get_property_list`, the drag-and-drop
  callbacks, `_get_configuration_warnings`, `EditorPlugin` hooks and so on. They come from a
  shipped list for the supported Godot version, which a project can extend, not from
  "starts with `_`": signal handlers are `_on_*` and must stay judgeable.
* **Signals connected in scene files**: `[connection signal="pressed" from="Button"
  to="." method="_on_button_pressed"]` in a `.tscn`. With the scene reader, the method is
  rooted on the script attached to the `to` node. When the node has no known script,
  the method name is rooted by name, which matches the rule's "loosely toward alive".
* **Names in strings**: `Callable(self, "m")`, `call("m")`, `call_deferred("m")`,
  `connect("sig", ...)`, `rpc("m")`, `call_group("g", "m")`, `propagate_call`,
  `has_method`. Method-call tracks in animations (`"method": &"m"` in `.tscn`, `.tres`
  and `.anim` files) are callers too. `sig.connect(_on_x)` is already a reference (a
  bare name used as a value).
* **Annotations and properties**: `@rpc` functions (remote callers), `set = _set_x, get =
  _get_x` and inline `set(value):` blocks, `@export_tool_button`.
* **Autoloads** (`[autoload]` in `project.godot`) and `run/main_scene`.

A new judgment the scene reader makes possible: **a whole script nothing uses**. A
script that no scene attaches, nothing `preload`s or `load`s, no `extends` names, whose
`class_name` nothing mentions, and that is not an autoload. A computed path
(`load("res://levels/" + name + ".gd")`) is an unknown, not a reference, so it goes in
`entry_points` as today. `addons/` is the vendor role by default, so plugins are not
judged.

### Godot names the project does not define (new rules, G4)

The thesis of ShockHarness is "no silent failure", and in Godot the commonest silent
failure is a misspelled name. `Input.is_action_pressed("jupm")` is false forever; a renamed
node makes `$HUD/Score` `null`; a renamed method breaks a scene connection. The engine
reports each of these only at run time, in the log, when that line runs. With the
`project.godot` and `.tscn` reader, these become checkable:

* an input action that is not in `project.godot`'s `[input]`;
* a node path (`$A/B`, `%Unique`, `get_node("A/B")`, `@onready var x = $A`) that does
  not exist in **every** scene that attaches the script. It is unknown when no scene
  does, or when the node is added at run time;
* a scene connection to a method the target script does not define;
* a group read (`get_nodes_in_group`, `is_in_group`, `call_group`) that nothing adds,
  neither `add_to_group` in code nor `groups=[...]` in a scene.

These are new rule IDs, warnings, Godot-only. I expect them to be the most valuable part
for a game, and they are cheap once G2's project model exists.

## 4. Milestones

Each milestone ends as the others do: fixtures, unit tests, the self-gate, an entry in
STATUS.md and CHANGELOG.md, and a measurement on the corpus recorded in STATUS.md.

* **G1, the adapter and facts.** The `shockharness[godot]` extra (once approved), with
  the missing-extra message. `registry.GDSCRIPT`,
  outside `ALL_LANGUAGES` and `JAVASCRIPT_FAMILY`, with each rule opting in through its
  `languages` as its facts are built. `.gd` in discovery. `**/.godot/**` excluded,
  `addons/**` the vendor role, GUT and gdUnit4 test globs. Parse failures, comments,
  numeric literals and named definitions, functions with their control trees, calls and
  locals. **The 40 two-way language branches** (15 files: `if language == PYTHON ...
  else <JavaScript>`, as in RESULT001's catalog key) become explicit, so GDScript can
  never fall into a JavaScript branch. A coverage entry lists the rules that did not run
  per language. Rules on: MAGIC001, CPLX001-004, CPLX006, SUPP001/002, STUB001.
  Robustness checks as for TypeScript: deep nesting on every supported CPython, and
  determinism.
* **G2, the Godot project model and the graph.** The stdlib reader for `project.godot`,
  `.tscn` and `.tres`, covering sections, `ext_resource`s, nodes and their scripts,
  connections, groups, autoloads, input actions, the main scene and animation method
  tracks. This is facts only, cached like source facts. The GDScript call graph and
  CPLX005. DEAD001/002 with the roots above and dead scripts.
* **G3, defaults, results and the small rules.** DEF001-006 shapes, RESULT001's
  `gdscript_must_use` (Error returns), ASSERT001/002, BOOL001, STUB002/003, MAGIC002-005,
  ASYNC001 if the engine's behavior makes it a real failure.
* **G4, Godot names.** The four checks above.
* **G5, tests and policy.** GUT and gdUnit4: ROLE001, VERIFY001-004, SLEEP001 in tests;
  `@warning_ignore` as suppressions; the `project.godot` warning levels as a tool
  configuration (TYPE002 and VERIFY003 shapes).
* **Later, on demand**: dataflow (`@rpc`, save files), STATE001 for autoloads,
  property contracts, C#.

**Fixtures.** Hand-written `.gd` files under `tests/fixtures/gdscript/` for each rule
(compliant and not), and from G2 a small Godot project fixture: a `project.godot` with an
autoload and input actions, two scenes with signal connections, a nested instance and an
animation method track, plus scripts that exercise each root. No Godot binary is needed.
If Tom has Godot installed, `godot --headless --check-only --script` over the fixtures
confirms the grammar and the engine agree on what parses.

**Measurement.** Two open-source Godot 4 code bases, cloned into scratch space, read
only and never committed: `godotengine/godot-demo-projects` (MIT, about a hundred small
projects; the breadth of engine idioms and many `.tscn` connections, the test for DEAD's
roots) and a large real one such as Pixelorama (MIT; parser stress and real complexity).
For each: parse failures (target 0), findings per rule per thousand lines, MAGIC001
broken down by shape (constructors, timers, lerp weights, `@export`s), and for DEAD the
MetaList method: two random samples of 30 heads, each judged dead or alive. Then Tom's
game, once it has code, is the measurement that decides the defaults.

## Questions for Tom

1. **The package.** May `tree-sitter-gdscript==6.1.0` become a dependency from G1 on,
   as the optional extra `shockharness[godot]` and pinned exactly? It was published by a
   third-party fork, so I would first check its sdist against upstream's source, and move
   to an upstream release when one exists. The alternatives are in part 2.
2. **C#.** Defer it? (Recommended. Your game is GDScript unless you say otherwise.)
3. **Game numbers.** Should the initializer of an `@export` variable count as a named
   definition, like `const` (recommended: yes, since the editor is the configuration
   surface)? And should a `const` of a built-in value type with literal arguments
   (`const SPAWN := Vector2(64, 32)`) count (recommended: yes)? Everything else stays
   MAGIC001, measured before any further change.
4. **Default include.** Add `**/*.gd` to the default `include` when G1 ships, as H-TS
   did for TypeScript (recommended)? This moves verdicts for Godot repositories, with the
   not-applicable rules listed.
5. **Downloads for measurement.** May I clone `godot-demo-projects` and Pixelorama into
   scratch space (read only, never committed)?
6. **Your setup.** Which Godot version is the game on, and will you test with GUT,
   gdUnit4, or neither for now? This decides which syntax G1 must parse and which test
   framework G5 does first.
7. **Order.** G1, then G2 (dead code and the project model), then G4 (names), then G3
   and G5? I put G4 before G3 because misspelled names are the bug a new Godot project
   hits first. The default is the numbered order.
