# Godot support: C# as a fourth language

Status: **accepted (Tom, 2026-10-19); G1 built** (spec 21.1 decision 40, STATUS.md). Tom's answers: 1, 2, 5 yes; 3 and 4 left to my judgment (both yes, as recommended); 6 the game is `~/Desktop/TheLivingLabyrinth`; 7 the recommended order.
Tom's Godot prototype is C# on Godot .NET. Its geometry and image-processing tools are
Python, which ShockHarness already covers, so nothing needs adding for them. Nothing has
been built and no package has been added. A first draft of this document targeted
GDScript. It was retargeted after Tom's correction, and GDScript is now a possible
later addition (part 5).

## Recommendation in one paragraph

Add **C#** as a fourth language, `csharp`, with its own extractors, parsed with
**`tree-sitter-c-sharp` 0.23.5**: the tree-sitter organization's grammar, MIT, abi3
wheels for every platform we test, and compatible with our pinned core. It is
syntax-only, like our Python and JavaScript analysis, and needs no .NET at run time.
Add a small **stdlib reader for Godot's text files** (`project.godot`, `.tscn`, `.tres`)
and for the **`.csproj` and `.editorconfig`**. No package is needed for these: a Godot
project's callers, node names and input actions live in the scene and project files, and
its compiler policy lives in the project files. Turn rules on for C# one family at a
time, each with fixtures and a measurement. The report lists the rules that did not run
on `.cs` files, so a C# file never looks clean for a rule that does not apply to it.
**Do not use Roslyn** inside ShockHarness. Report instead when the project's own .NET
analyzers and nullable checking are off.

## 1. Language: C#, and what C# changes compared with GDScript

C# brings most of ShockHarness's families with it: exceptions with typed catches and
`when` filters, optional parameters, `??`, `??=` and `?.`, nullable reference types,
`async`/`await` with `Task`, `using` blocks (managers), statics (module state),
attributes. More rules apply than would to GDScript, and they apply in the shapes the
rules already know from Python (typed catches) and JavaScript (`??`, promises).

What is Godot-specific (and checked against the Godot 4.7 C# docs and source):

* **Exceptions do not crash the game.** The engine's C# bridge wraps every callback in
  `catch (Exception e) { ExceptionUtils.LogException(e); }`
  (`CSharpInstanceBridge.cs`), so an exception thrown in `_Process` or a signal handler
  is logged and the frame continues. The engine is an implicit top-level boundary: the
  rest of that callback is skipped, silently for the player.
* **Script classes must be `partial`.** Godot's source generators add members to them,
  including the nested `MethodName`, `PropertyName` and `SignalName` classes. They do
  this in memory only: the generated code is not on disk and not in the repository
  (build output goes to `.godot/mono/temp/`). ShockHarness reads source only, so it must
  know what the generators add: `SignalName.X`, `MethodName.M` and `PropertyName.P` are
  references to `X`, `M` and `P`, and `[Signal] delegate void XEventHandler(...)`
  declares the event `X`. A type's members are the union of its `partial` declarations
  across files.
* **Callers the code does not show**: engine callbacks (`public override void
  _Ready()`, `_Process(double delta)`, `_PhysicsProcess`, `_Input`, `_UnhandledInput`,
  `_Notification`, `_EnterTree`, `_ExitTree`, `_Draw`), signals connected in `.tscn`
  files (`[connection signal="pressed" from="Button" to="." method="OnButtonPressed"]`,
  using whatever name the connect dialog was given), `Call("m")`/`CallDeferred("m")`,
  `[Rpc]` methods, and animation method tracks.
* **Configuration in the editor**: `[Export]` properties (`[Export] public float Speed {
  get; set; } = 300f;`); range hints are `[Export(PropertyHint.Range, "0,500,10")]`.
  The scene's values override the initializer.
* **Numbers everywhere**: `new Vector2(320, 180)`, `new Color(1, 0.5f, 0)`,
  `Mathf.Lerp(a, b, 0.1f)`, `GetTree().CreateTimer(0.5)`. `delta` is a `double` and
  vectors are `float`, so suffixed literals (`10f`) are common.
* **Godot's toolchain**: `Godot.NET.Sdk/4.x`, `net8.0` and C# 12 by default. Godot ships
  its own analyzers (GD0001 a missing `partial`, GD01xx invalid exports, GD02xx signal
  delegates), all errors, so ShockHarness does not repeat them. A class must be named
  like its file, or Godot cannot find the script.

## 2. The parser

Checked on 2026-10-19 against PyPI's and NuGet's metadata, GitHub, and the source.

| Option | Facts | Verdict |
|---|---|---|
| **`tree-sitter-c-sharp` 0.23.5** (PyPI) | MIT, published 2026-04-14 by the tree-sitter organization's shared release workflow, with an API token. That means no provenance attestation, but the organization that publishes `tree-sitter` itself, unlike the GDScript package's third-party fork. abi3 wheels for macOS x86_64/arm64, manylinux and musllinux x86_64/aarch64, and Windows x64/arm64. Language ABI 15, which our core (`tree-sitter>=0.25.1,<0.26`) loads. Covers **C# 1 to 13**: file-scoped namespaces, records, primary constructors, collection expressions, `required`/`init`, raw strings, list/property/relational patterns, switch expressions, `T?` and `x!`, `??=`, `new()`, local functions, attributes, `partial`, `#if`/`#pragma`/`#nullable`. C# 14 (extension members) is merged upstream but unreleased (tree-sitter/tree-sitter-c-sharp#443 asks for a release). Releases are irregular (2022, 2024, 2026-04). The same version number once changed ABI (#420), which only breaks cores older than 0.25 | **Recommended**: one new runtime dependency, pinned `>=0.23.5,<0.24`. The first G1 task is to run it over the corpus and count parse failures |
| Known grammar bugs that matter | a root `ERROR` when attributes or members sit inside `#if` (#376, #377), and Godot projects use `#if TOOLS`; generics read as comparisons in some positions (#434); `cond ? [] : alt` (#406); interpolated verbatim strings (#368); `?.` precedence (#233, #172, #151) | measured in G1. A file with an `ERROR` node is a parse failure, reported, never clean, as today. If `#if` is common in the corpus, G1 may blank out inactive `#if` branches before parsing, keeping line numbers, the way a preprocessor would |
| Roslyn through pythonnet 3.2.1 and `Microsoft.CodeAnalysis.CSharp` | exact semantics: types, overloads, generated code, nullable flow. Needs an installed .NET runtime and the Roslyn DLLs at run time | rejected for ShockHarness itself: it must run in CI without .NET |
| Roslyn as a native-AOT tool emitting JSON | no .NET at run time, but a binary per OS and architecture, built and shipped by us. Whether Roslyn is AOT-clean is not verified | rejected: we would ship compiled code. Revisit only if measurement shows unresolved calls dominate the unknowns |
| A pure-Python C# parser | none maintained; ANTLR with `antlr4-python3-runtime` has no maintained C# 12 grammar and is slow | rejected |
| The project's own .NET analyzers (`Microsoft.CodeAnalysis.NetAnalyzers`, Roslynator, compiler nullable warnings CS86xx) | they run in the game's own build, which needs .NET anyway, with full semantics. SonarAnalyzer.CSharp is source-available, not open source | **complementary**: ShockHarness reads the `.csproj` and `.editorconfig` and reports when nullable checking, the analyzers or warnings-as-errors are off, or a change weakens them (part 3, TYPE002 and VERIFY003 shapes) |

**Scene, project and build files need no package.** Each `.tscn`/`.tres`/`project.godot`
section header is one line of `key=value` pairs (`[ext_resource path=... id=...]`, `[node
name=... parent=... instance=... groups=[...]]`, `[connection signal=... from=... to=...
method=...]`). Values are Variant literals that can span lines, so a stdlib reader only
needs a string- and bracket-aware scanner. `project.godot` holds `[autoload]` and
`[input]`. A `.csproj` is XML (`xml.etree`), and `.editorconfig` is INI-like.

## 3. How each rule family maps onto Godot C#

| Family | C# shape | Plan |
|---|---|---|
| **MAGIC001** numbers | literals with suffixes and separators (`10f`, `0.5d`, `2m`, `1_000`, `0x10`), judged by value as today (`1f` and `0.0f` pass). Named definitions: a `const` field, a `static readonly` field whose value is literal arithmetic, or one built with `new Vector2(...)`/`new Color(...)` from literal arguments (C# cannot make those `const`), and explicit `enum` values. The name shape is C#'s: any name, since a `const` field is itself the declaration of intent. MAGIC004 still reports a name that only spells its number. A local `const` inside a method is not covered, as Python's function-level constants are not. The remedies the message names are Godot's: a `const`, an `[Export]` property, a `Marker2D` in the scene for a position, and the engine's named values (`Vector2.Up`, `Colors.Red`). Values in `.tscn` files are data and are never scanned | **G1.** The initializer of an `[Export]` property and the numbers in attribute arguments (`[Export(PropertyHint.Range, "0,500")]` holds them as a string anyway) are question 3 |
| MAGIC002 repeated strings | node paths (`GetNode<Label>("HUD/Score")`), input actions (`Input.IsActionPressed("jump")`), group and animation names, string method names | G3, then replaced for the names Godot defines by the G4 checks |
| MAGIC003-005 | as written | G3 |
| **EXC001-003** catches | close to Python's: typed catches (`catch (IOException e)`), broad `catch (Exception)`, bare `catch { }`, `when` filters as narrowing, `throw;` versus `throw e;` (the second loses the stack trace, a possible new finding), rethrow and wrapping (`throw new X(..., e)`). Boundaries name qualified types (`System.IO.IOException`), resolved through `using` directives, global usings and the SDK's implicit usings, so their confidence is approximate | **G2.** Because the engine logs and carries on, `catch (Exception e) { GD.PushError(e.Message); }` in a callback adds nothing and loses the stack trace: it stays a finding |
| EXC004 | `return` in `finally` is a compiler error in C# (CS0157) | not applicable |
| EXC005 | as written | G2 |
| **DEF001** optional parameters | `void Hit(int damage = 10)`; overloads are the explicit alternative | G2 |
| DEF002 lookup fallbacks | `GetValueOrDefault(k, d)`, `TryGetValue(k, out v) ? v : d` and its statement forms, `FirstOrDefault()`/`SingleOrDefault()`/`ElementAtOrDefault()`/`DefaultIfEmpty(x)`, `GetMeta(name, d)` | G2 |
| DEF003 truthiness | C# has no truthiness. The nearest shape is `string.IsNullOrEmpty(s) ? d : s` | G3, as that shape only |
| DEF004 nullish | `x ?? y`, `x ??= y`, `x is null ? d : x`, `GetNodeOrNull<T>(...) ?? ...`. Also new: a statement that is only a null-conditional call (`_target?.TakeDamage(5);`), which skips silently when the target is gone | G2; the `?.` statement as a review shape after measuring it |
| DEF005 exception to default | `catch { return null; }`, `catch (FormatException) { return 0; }` | G2, as written; decision 37's entry-point exemption has no Godot equivalent |
| DEF006 configuration | `Environment.GetEnvironmentVariable(x) ?? d`, `ProjectSettings.GetSetting(name, d)`, `ConfigFile.GetValue(section, key, d)` (settings and save files), `OS.GetEnvironment` | G2 |
| **CPLX001-004, CPLX006** | `if`/`else`, `switch` sections, switch-expression arms, `&&`/`\|\|`/`??`, pattern `and`/`or`, ternaries, loops, `catch`, lambdas and local functions. Large `_Process`/`_PhysicsProcess` state machines are where game code gets complex | **G1** |
| CPLX005 coupling and cycles | C# imports namespaces, not files, so the graph is between types: a type used in another file. A type index (name to files, `partial` merged) replaces the import resolver | G3 |
| **Call graph** | units are methods, constructors, property accessors, local functions and lambdas. Resolution is much better than in Python or JavaScript because declarations carry types: `M()`/`this.M()`, `base.M()`, `Type.M()`, `new T(...)`, receivers typed by a field, parameter, local or `GetNode<T>(...)`. Overloads, interfaces, generics and extension methods make some sites probable, not exact | G3 |
| **DEAD001/002** | the dead-code section below | **G3** |
| ASSERT001/002 | `Debug.Assert` is `[Conditional("DEBUG")]`, and Godot's release exports build Release, so the shipped game has no asserts | G3 |
| RESULT001 must-use | `Error` returns of Godot APIs (`ResourceSaver.Save`, `ChangeSceneToFile`, `Connect`); a `bool` from `TryParse`/`TryGetValue` thrown away (`int.TryParse(s, out n);` leaves `n` at 0); results of pure calls thrown away (`s.Trim();`, `list.Where(...);`, `v.Normalized();`, the classic Godot one, since vectors are values) | G2, a `csharp_must_use` catalog |
| ASYNC001-003 | a `Task` dropped (`DoAsync();` with no `await`, which the compiler warns about only inside `async` methods); `async void` outside an event or signal handler; `Task.Run` with no owner; `Task.WhenAll` failures not inspected. `await ToSignal(...)` is Godot's way to wait | G3 |
| STATE001/002 | `static` mutable fields written from methods are C#'s module state, and autoloads are the other global state. STATE002's shape is the singleton `Instance = this;` at the top of `_Ready`, before the rest of the setup | G3 |
| IMPORT001 | static constructors and static field initializers that call out | G3 |
| BOOL001, STUB001-003 | `SetProcess(false)`; `throw new NotImplementedException()` and empty bodies; test code in game code; `bool IsValid() => true` | G2 |
| PROCESS001 | `System.Diagnostics.Process.Start`, `OS.Execute` | G3 |
| TYPE001/002 | escape hatches: `dynamic`, the null-forgiving `x!`, `#nullable disable`, `#pragma warning disable CS86xx`, and unchecked casts on Variants. TYPE002's shape: no `<Nullable>enable</Nullable>` in the `.csproj` (Godot's template does not set it, as far as I know; to check), or warnings that are not errors | G4 |
| SUPP001/002 | `// shockharness: ignore[...] reason="..."`, the JavaScript form | G1 |
| VERIFY001-004, ROLE001, SLEEP001 | `#pragma warning disable` without a matching restore, `[SuppressMessage]` and `GlobalSuppressions.cs` (VERIFY002); a weakened `<Nullable>`, `<NoWarn>`, `<TreatWarningsAsErrors>` or `.editorconfig` severity (VERIFY003); test frameworks: gdUnit4Net (`[TestSuite]`/`[TestCase]`), Chickensoft GoDotTest, and xUnit/NUnit on code that does not touch Godot (skip attributes, `Assert.True(true)`, fixed waits in tests) | G4 |
| INPUT001/002 | `[Rpc]` method parameters, `HTTPRequest` bodies, save files in `user://`; sinks such as `Process.Start`, `GD.Load(path)`, `GD.BytesToVarWithObjects` | later, only if the game gets multiplayer or user content |
| PROP001-008 | the runtime would be a static `Contracts` class | later |
| DOM001/002 | no DOM | not applicable |

### Dead code

DEAD001's roots today include **every method of a class derived from a class the project
does not define** (`framework_method` in `rules/dead_code.py`). That root was meant for
callbacks such as `HTMLParser.handle_*`. In Godot every script class derives from an
engine class (`Node`, `CharacterBody2D`), so every method of every script would be a root
and DEAD001 would never report anything. C# lets us be exact where Python could not:

* **`override` methods** of a base the project does not define are roots: the engine
  callbacks, `ToString`, `Dispose`. That is read from the modifier, not from a name list.
  Other methods of the class are judged like any function.
* **Implementations of interfaces the project does not define** are roots (approximate
  for implicit implementations).
* **Signals connected in scene files**: the method is rooted on the class of the script
  attached to the `to` node. When that class is unknown, the method name is rooted by
  name, which follows the rule's "loosely toward alive".
* **References the generators and the API make by name**: `MethodName.M`, `nameof(M)`,
  `Callable.From(M)`, `new Callable(this, "m")`, `Call("m")`, `CallDeferred("m")`,
  `Rpc("m")`, and animation method tracks. `Hit += OnHit` is already a reference (a
  method used as a value).
* **Attributes as registration**: `[Rpc]`, `[Signal]`, `[Export]` accessors,
  `[ExportToolButton]`, `[ModuleInitializer]`, test attributes (test roots), and `Main`.
* **Autoloads** and `run/main_scene`.

What the scene reader adds: **a whole script nothing uses**. That is a class that no
scene attaches (`[ext_resource type="Script" path="res://Player.cs"]`), no code
instantiates, references or loads, and that is not an autoload. Reflection
(`GetMethod("X")`) and computed paths go in `entry_points`, as today. `addons/` is the
vendor role by default.

### Godot names the project does not define (new rules, G4)

The commonest silent failure in a Godot project is a misspelled name. The engine reports
each of these only at run time, in the log, when that line runs:

* an input action that is not in `project.godot`'s `[input]`;
* a node path (`GetNode<T>("A/B")`, `%Unique`) that does not exist in **every** scene
  that attaches the script. It is unknown when no scene attaches it, or when the node is
  added at run time;
* a scene connection to a method the target class does not define;
* a group read (`GetNodesInGroup`, `IsInGroup`, `CallGroup`) that nothing adds,
  neither `AddToGroup` nor `groups=[...]` in a scene;
* a string signal or method name (`EmitSignal("Hit")`, `Call("on_hit")`) where the
  generated `SignalName`/`MethodName` constant exists. That last one is a typo waiting to
  happen, and Godot's docs recommend the constants.

These are new rule IDs, warnings, Godot-only. They are cheap once G3's project model
exists, and I expect them to be the most valuable part for a game.

## 4. Milestones

Each milestone ends as the others do: fixtures, unit tests, the self-gate, an entry in
STATUS.md and CHANGELOG.md, and a measurement on the corpus recorded there.

* **G1, the adapter and facts.** The dependency (once approved). `registry.CSHARP` with
  `.cs` in discovery. Excluded by default: `**/.godot/**`, `**/obj/**` and `**/bin/**`
  (`obj/` holds generated `.cs`). Roles: `*.g.cs` and `*.Designer.cs` generated,
  `addons/**` vendor, test globs. C# stays out of `ALL_LANGUAGES` and
  `JAVASCRIPT_FAMILY`; each rule opts in through its `languages` as its facts are built.
  **The 40 two-way language branches** (15 files; `if language == PYTHON ... else
  <JavaScript>`, as in RESULT001's catalog key) become explicit, so C# can never fall
  into a JavaScript branch. A coverage entry lists the rules that did not run, per
  language. Facts: parse failures, comments, numeric literals and named definitions,
  functions with their control trees, calls and locals. Rules on: MAGIC001,
  CPLX001-004, CPLX006, SUPP001/002. First task: parse the corpus and decide on `#if`
  handling. Robustness as for TypeScript: deep nesting on every supported CPython, and
  determinism.
* **G2, exceptions, defaults and results.** Catch and manager facts (`using`), C#
  exception identities and boundaries, EXC001-003 and EXC005, DEF001-006 shapes,
  RESULT001's `csharp_must_use`, BOOL001, STUB001-003.
* **G3, the Godot project model and the graph.** The stdlib reader for `project.godot`,
  `.tscn` and `.tres` (scripts attached, connections, groups, autoloads, input actions,
  the main scene, animation method tracks), cached like source facts. The type index
  with `partial` merged and the generated members modelled. The C# call graph, CPLX005,
  DEAD001/002 with the roots above and dead scripts. Also ASSERT001/002, ASYNC001-003,
  STATE001/002, IMPORT001, PROCESS001, MAGIC002-005.
* **G4, Godot names, tests and policy.** The name checks above; the `.csproj` and
  `.editorconfig` reader for TYPE001/002 and VERIFY002/003; test frameworks for ROLE001,
  VERIFY001/004 and SLEEP001.
* **Later, on demand**: dataflow (`[Rpc]`, save files), property contracts, GDScript.

**Fixtures.** Hand-written `.cs` files under `tests/fixtures/csharp/` for each rule
(compliant and not), and from G3 a small Godot .NET project fixture: `project.godot`
with an autoload and input actions, a `.csproj`, two scenes with signal connections, a
nested instance and an animation method track, and `partial` scripts that exercise each
root. The test suite needs no .NET. With Tom's local .NET SDK, `dotnet build` of the
fixture project confirms the fixtures compile, so every fixture is real C#. That is a
check run by hand and recorded in STATUS.md, not a CI dependency.

**Measurement.** Open-source Godot 4 C# code, cloned into scratch space, read only and
never committed:

* `godotengine/godot-demo-projects` `mono/` (MIT; 33 `.cs` files, six small games);
* `chickensoft-games/GameDemo` (MIT; 163 `.cs` files, 61 of them tests; Godot 4.7,
  nullable on, idiomatic but built on Chickensoft's libraries);
* `NoisyChain/Sakuga-Engine` (MIT; 227 `.cs` files, a fighting-game engine on Godot 4.7,
  close to Tom's genre).

For each: parse failures (target 0, with the `#if` count), findings per rule per thousand
lines, MAGIC001 broken down by shape (vector and colour constructors, timers, lerp
weights, `[Export]` initializers), and for DEAD the MetaList method of two random samples
of 30 heads. Then Tom's prototype is the measurement that decides the defaults.

## 5. GDScript, later

GDScript would reuse G3's Godot project model and the G4 name rules unchanged. It would
need its own extractors and its parser package, which is the problem. The only PyPI
release of `tree-sitter-gdscript` (6.1.0, MIT, 2026-09-04) was published by a
third-party fork, not by the grammar's maintainer. It has wheels for three platforms
only, and it lacks upstream fixes since July. Upstream's own PyPI publishing is an open
pull request (PrestonKnopp/tree-sitter-gdscript#91). It would be worth doing once
upstream publishes, and only if a GDScript project needs it. Facts for that day: there
is no `try` in GDScript, `and`/`or` always produce a bool, `assert()` is stripped from
release exports, and every script extends an engine class, so the dead-code problem
above applies there too, without C#'s `override` keyword.

## Questions for Tom

1. **The package.** May `tree-sitter-c-sharp` (`>=0.23.5,<0.24`, MIT, published by the
   tree-sitter organization) become the fourth runtime dependency, from G1 on?
2. **Roslyn.** Agree to stay syntax-only, with no Roslyn and no .NET at run time, and to
   report the project's own analyzer and nullable settings instead?
3. **Game numbers.** Should the initializer of an `[Export]` property count as a named
   definition like a `const`? Recommended: yes, since the editor is the configuration
   surface. Should a `static readonly` value-type field built from literals
   (`static readonly Vector2 Spawn = new(64, 32);`) count? Recommended: yes. Everything
   else stays MAGIC001 until measured.
4. **Default include.** Add `**/*.cs` to the default `include` when G1 ships, as H-TS did
   for TypeScript? Recommended. This moves verdicts for C# repositories, with the
   not-applicable rules listed.
5. **Downloads for measurement.** May I clone the three corpus repositories into
   scratch space (read only, never committed)?
6. **Where is the prototype?** From this session I see `/Applications/Godot.app` 4.6.1
   without the .NET folder, no `dotnet` on the PATH, and `~/Desktop/Godot`, which is a
   GDScript project from February. Which path, and which Godot version, should
   measurements use? Which test framework will you use, if any?
7. **Order.** G1, then G2, G3 and G4? An alternative is G3 (dead code and the project
   model) before G2, if unused scripts and broken connections worry you more than
   swallowed exceptions.
