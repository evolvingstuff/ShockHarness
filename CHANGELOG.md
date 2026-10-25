# Changelog

All notable changes to ShockHarness. Format follows Keep a Changelog; versions
follow Semantic Versioning. The report `schema_version` is tracked separately.

## [Unreleased]

## [0.31.0] - 2026-10-25

Skill guidance only: writes that run later, and lists drawn and acted on.

**Upgrading from 0.30.1.** No new dependency, no analysis change and no configuration
change: findings, the gate and baselines are as in 0.30.1 (the cache rebuilds once, as with
every version). Four skills changed (`async-lifecycle` and `write-compliant-code` gained
guidance; the version pin in `adopt-shockharness` and `pre-commit-review`), so `check` says
`skills: 4 out of date`. Run `shockharness skills update --agent claude` (or `codex`) and
commit the result.

### Added
- **The `write-compliant-code` skill: what is drawn and what is acted on.** A checklist line:
  the rows a list shows and the item its index selects come from one function, never two
  filters of the same field kept in step by hand. Skill wording rather than a rule
  (`docs/ideas.md`): one true case against four unrelated filters measured.
- **The `async-lifecycle` skill: writes that run later.** Code after an `await`, and a
  `blur`/`focusout` handler that closing a dialog can fire, runs in a later state (the
  dialog closed, the lookup replaced, the value already set): check, at the write, what
  it depends on. Skill wording rather than a rule (`docs/ideas.md`): from two crashes in
  one application's dialog, each tied to its own state store.

## [0.30.1] - 2026-10-24

The package's text no longer names the application its lessons came from.

**Upgrading from 0.30.0.** No analysis change, no configuration change: findings, the gate
and baselines are as in 0.30.0. The version pin changed in two skills
(`adopt-shockharness`, `pre-commit-review`), so `check` says `skills: 2 out of date`; run
`shockharness skills update --agent claude` (or `codex`). A configuration written by an
earlier `init` keeps its old comments; they are comments only.

### Changed
- **Shipped text names no project.** The rule explanations (`rules explain`), the comments
  in the bundled defaults (which `init` copies into a new configuration) and three code
  comments told their lessons with one application's name and internal function names;
  they now say "one project" and use generic examples (`CommandQueue.run:1`,
  `app/services/backups.py`). The lessons and every rule's behavior are unchanged.

## [0.30.0] - 2026-10-24

Skill guidance only: three lessons from MetaList's recent bugs, for tests and for blank
checks.

**Upgrading from 0.29.0.** No new dependency, no analysis change and no configuration
change: findings, the gate and baselines are as in 0.29.0 (the cache rebuilds once, as with
every version, since the version is part of its key). Four skills changed
(`verification-integrity` and `write-compliant-code` gained guidance; the version pin in
`adopt-shockharness` and `pre-commit-review`), so `check` says `skills: 4 out of date`. Run
`shockharness skills update --agent claude` (or `codex`) and commit the result.

### Added
- **The `verification-integrity` skill: simulated input.** A helper that simulates a
  keystroke derives every effect (the key event, the browser's editing command) from the
  same modifiers, ideally from one table: ⇧⌘V is Paste and Match Style, not ⌘V's paste.
  From MetaList's browser suite, whose helper held Shift but always sent `paste`.
- **The `write-compliant-code` skill: blank means no visible character.** `strip()` and
  `trim()` leave zero-width characters (U+200B to U+200D, U+2060; Python also U+FEFF), so
  text a person typed or pasted is tested for blankness through one shared check that
  removes them. Skill wording rather than a rule (`docs/ideas.md`): MetaList has about 245
  `strip()`/`trim()` emptiness checks, and which ones see a person's text is not in the
  syntax.
- **The `verification-integrity` skill: samples a parser really meets.** A parser,
  detector or guesser is tested on samples its real producer made (Markdown as editors
  and AI chats write it, files as tools export them), and round-tripped where the
  producer is available. Skill wording rather than a rule (`docs/ideas.md`): from
  MetaList's paste-format guesser.

## [0.29.0] - 2026-10-23

Call boundaries: only the files a project names may write to disk, open a connection or
make any other call it lists.

**Upgrading from 0.28.0.** No new dependency.
* **CALL001 does nothing until a project writes an entry.** For example, keeping disk
  writes in one module: `[[tool.shockharness.rules.call_boundaries.forbidden]]` with
  `callers = ["app/**"]`, `allowed_callers = ["app/storage/writer.py"]`,
  `calls = ["@disk_writes"]` and a `reason`. `docs/configuration.md` (Call boundaries) has
  the catalogs and the syntax.
* **Baselines.** The bundled defaults gained the `call_boundaries` table, so the
  configuration digest changes: a baseline recorded under 0.28.0 still applies, with the
  "created under a different configuration" note until it is recreated.
* **Cache.** The cache schema is 38: the first run rebuilds it.
* **Skills.** Three skills changed (`fix-violations` gained a CALL001 row; the version pin
  in `adopt-shockharness` and `pre-commit-review`), so `check` says
  `skills: 3 out of date`. Run `shockharness skills update --agent claude` (or `codex`)
  and commit the result.

### Added
- **CALL001: call boundaries, "only these files may call it" (Python, JavaScript).**
  A `[[rules.call_boundaries.forbidden]]` entry binds `callers` (less `allowed_callers`)
  and forbids `calls`: a qualified name with everything below it, resolved through the
  file's imports (`shutil`, `os.replace`, a global like `fetch`), a method on any receiver
  (`.write_text`, approximate), either with `/mode=write` (only a literal write mode or
  write flags count; an unreadable mode is an unknown finding), or a shipped catalog,
  `@disk_writes` or `@network`, per language. It keeps disk writes in one writer and the
  network behind one client, which IMPORT002 cannot (`open` and `fetch` are not imports).
  Nothing fires until a project writes an entry. On MetaList: 73 disk writes in 27 files
  and 47 browser `fetch` calls in 28 files outside its API client, each one real. The
  cache schema is 38 (an `open` call's mode is a new fact).

## [0.28.0] - 2026-10-23

A new rule, ASYNC004, for commands that freeze while a page is not drawn, and skill
guidance on clamps.

**Upgrading from 0.27.0.** No new dependency.
* **ASYNC004 needs your gates.** Out of the box it watches only `navigator.locks.request`.
  A project with its own command queue names it under `[tool.shockharness.rules.async_lifecycle]`,
  for example `gates = ["navigator.locks.request:last", "CommandGate.run:1",
  "CommandGate.runWhenFree:1"]`, and `check` then reports any `.finished` a command waits on.
  Without gates, nothing changes.
* **Baselines.** The bundled defaults gained `gates`, so the configuration digest changes
  again: a baseline recorded under 0.27.0 still applies, with the "created under a
  different configuration" note until it is recreated.
* **Cache.** The cache schema is 37: the first run rebuilds it.
* **Skills.** Four skills changed (`async-lifecycle` and `write-compliant-code` gained
  guidance; the version pin in `adopt-shockharness` and `pre-commit-review`), so `check`
  says `skills: 4 out of date`. Run `shockharness skills update --agent claude` (or
  `codex`) and commit the result.

### Added
- **ASYNC004: a gated command waits on the page being drawn (JavaScript, TypeScript).**
  A browser does not run animations for a page it does not draw, so an awaited
  `.finished` inside a command that holds a gate (a command queue, a Web Lock) holds the
  gate until the page is shown, and every later command waits. The rule follows awaited
  and returned calls through the call graph, across files, from each gate's callback to
  the await, and reports the await once, naming every command that reaches it. Gates
  are `rules.async_lifecycle.gates` (`callee:index` or `callee:last`); the default is
  `navigator.locks.request:last`, and a project adds its own queue (`CommandGate.run:1`).
  On MetaList before its fix: one finding naming the 10 reference-navigation commands
  that froze; after it, none. The cache schema is 37 (the facts gained fields).
- **The `write-compliant-code` skill: clamps on measured values.** A clamp
  (`Math.max(0, x)`, `clampNumber(x, 0, n)`) on a value the code believes always lies
  inside the bound hides the case where it does not; assert the bound, or make the
  out-of-range value impossible where it is chosen. A clamp that is part of the request
  (a slice from 0) stays. Skill wording rather than a rule (`docs/ideas.md`): from
  MetaList's return-to-the-list bug, where a saved offset clamped to 0 moved the list
  80px.

## [0.27.0] - 2026-10-22

Paths where no inline suppression counts, and DEF002/DEF004 stop reporting lazy
initialization.

**Upgrading from 0.26.0.** No new dependency.
* **Fewer findings, never more.** Fields and module variables filled on first use
  (`this.#x ??= new Map()`, C# `_x ??= new X()`) are no longer reported. A suppression
  written for one is now unused (a SUPP002 warning: delete it), and a baseline entry for
  one is listed as stale.
* **Baselines.** The bundled defaults gained the `suppressions` table, so every
  repository's configuration digest changes. A baseline recorded under 0.26.0 is still
  applied, with a note that it was created under a different configuration;
  `shockharness baseline create` again removes the note.
* **Skills.** Two skills changed (the version pin in `adopt-shockharness` and
  `pre-commit-review`), so `check` says `skills: 2 out of date`. Run
  `shockharness skills update --agent claude` (or `codex`) and commit the result.

### Changed
- **Lazy initialization is not a fallback (DEF002, DEF004).** A field or a module
  variable filled on first use with a value built for it (`this.#x ??= new Map()`,
  `channel ??= new Channel()` on a module `let`, C# `_channel ??= new Channel(...)`,
  Python `self.x = self.x if self.x is not None else X()`) is no longer reported. A
  constant, a parameter, a local or a parameter's property is still a fallback. On
  14 code bases the only change is Sakuga-Engine's three lazy channel fields.

### Added
- **Paths where no inline suppression counts (`suppressions.forbidden`).** An entry
  names `paths` (globs) and a `reason`; in a matching file every
  `shockharness: ignore[...]` comment is a SUPP001 error quoting the glob and the reason,
  and the finding it names stays, as `--no-inline-suppressions` does for a whole run.
  For code whose findings are resolved by a change, never silenced: MetaList's policy
  note asks for it on `tests/regression/adversarial/**`. A ban is not a deviation;
  removing an entry or dropping a path from it is a VERIFY003 loosening. With no entry
  (the default) nothing changes.

## [0.26.0] - 2026-10-22

Import boundaries can now name packages and standard-library modules and say which files
alone may import them, and the `async-lifecycle` skill covers scroll positions measured
before an await.

**Upgrading from 0.25.0.** No new dependency, and existing configurations, findings and
the gate are as in 0.25.0: an IMPORT002 entry written before means what it meant, and the
new keys (`modules`, `allowed_importers`) only add findings where a project writes them.
Three skills changed (`async-lifecycle`'s new section, and the version pin in
`adopt-shockharness` and `pre-commit-review`), so a repository with installed skills sees
one line from `check` (`skills: 3 out of date ...`), and its agent hears it once from the
hook. Run
`shockharness skills update --agent claude` (or `codex`) and commit the result.

### Added
- **The `async-lifecycle` skill: positions measured across an await.** After awaiting
  something that changes the page, do not animate to a position measured once; place at
  once, or scroll to the element and re-measure it each frame. Skill wording rather than a
  rule: a prototype found MetaList's find-in-list scroll bug, but its other sites were the
  same shape with no failure (`docs/ideas.md`).
- **Import boundaries for named modules, and "only these files may import it"
  (IMPORT002).** A `[[rules.import_boundaries.forbidden]]` entry can now name packages and
  standard-library modules (`modules = ["httpx", "cryptography.hazmat"]`), each with
  everything below it (`from cryptography import hazmat` included). A JavaScript package
  covers its paths, a scoped package is one name, and `node:fs` is `fs`. An entry can also
  exempt files with `allowed_importers`, so "only `app/services/public_http.py` may import
  `httpx`" is one entry. `imported` is now optional; one of `imported` and `modules` is
  required. A module named by name is judged from the importing file alone, so the
  edit-time hook sees it too. Dropping a module or exempting another file is a VERIFY003
  loosening. Existing entries mean what they meant. From MetaList's policy note; on
  MetaList, four entries shaped like it found the same 31 import sites a line count does.
  ShockHarness's own configuration now keeps `subprocess` in `history/git.py`.

## [0.25.0] - 2026-10-22

The skills now reach an agent through the commands it runs: `init` installs them, and
`check` says when a repository's agent has none.

**Upgrading from 0.24.0.** No new dependency and no analysis change: findings, the gate,
the report and the configuration digest are as in 0.24.0. A repository with its own
configuration whose coding agent has no ShockHarness skills installed now sees one line
from `check` with the install command (for example `shockharness skills install --agent
claude`); run it and commit the skills and the pointer line it adds to `CLAUDE.md` or
`AGENTS.md`, or set `notify_missing = false` under `[tool.shockharness.skills]` if the
repository wants none. Repositories with skills installed see nothing new.

### Added
- **`init` installs the agent skills.** An agent that adopts ShockHarness by running its
  commands never read the setup guide's skills step, so the skills never reached it (a
  repository adopted on the day the skills shipped never had them). `init` now installs
  them for every coding agent whose files are in the project: `.claude/` or `CLAUDE.md`
  for Claude Code (`.claude/skills`), `.agents/` or `AGENTS.md` for Codex and the other
  agents that read `AGENTS.md` (`.agents/skills`). An agent whose skills are installed is
  left alone. `--agent claude|codex` chooses instead of the detection; `--no-skills`
  writes only the configuration. With no agent's files it prints both install commands.
- **`skills install` adds a pointer line** to `CLAUDE.md` (claude) or `AGENTS.md` (codex)
  telling the agent to read the matching skill before it writes code, created when absent
  and kept when the file already names the skills directory. `init` does the same.
- **`check` says when no skills are installed.** While a project with its own
  configuration has an agent's files and no ShockHarness skills for that agent (in the
  project or under the home directory), `check` prints one line on stderr after the report
  with the exact command; the report and the gate are unchanged. With no agent's files it
  names both commands. The new key `skills.notify_missing = false` records that a
  repository wants no skills; like `cache`, the `skills` table is not part of the
  configuration digest, so baselines and the cache are unaffected.

### Fixed
- The README said six skills ship; there are eight. `docs/skills.md`'s example pointer line
  listed six names.

## [0.24.0] - 2026-10-22

The setup guide becomes its own skill, `adopt-shockharness`, and `check` and the edit-time
hook now tell agents when a project's installed skills are behind the installed
ShockHarness.

**Upgrading from 0.23.0.** No new dependency and no analysis change: findings, the gate
and the report are as in 0.23.0. A project that installed the skills (`skills install`)
sees one line from `check` after upgrading, and its agent hears it once from the hook:
seven skills out of date and one new. Run `shockharness skills update --agent claude` (or
`codex`) and commit the result; a skill file someone edited is reported as a conflict, as
before. Projects without installed skills see nothing.

### Added
- **`check` and the edit-time hook say when the installed skills are behind.** When a
  project's skills (installed by `skills install` for Claude Code or Codex) are older than
  the installed ShockHarness, `check` prints one line on stderr with the counts and the
  exact command (`shockharness skills update --agent claude`), and the hook feeds it back
  to the agent once per upgrade. The gate and the report are unchanged. Agents learn that
  an update is due without anyone reading the release notes.

### Changed
- **The setup guide is its own skill, `adopt-shockharness`.** Each of the seven skills
  carried the README's 151-line "Adopting ShockHarness" section; it now lives in the new
  eighth skill alone, and the others end with a pointer to it. `skills install` writes
  eight skills, and `skills update` adds the new one and refreshes the seven it installed
  (a skill file someone edited is reported as a conflict, as before). The
  space it frees lets `fix-violations` and `write-compliant-code` (both at their 500-line
  limit before) carry the guidance for the newer rules. `write-compliant-code`'s principle
  9 now says a state the user can reach is no failure: disable the control or say so,
  never throw.

## [0.23.0] - 2026-10-22

C# for Godot .NET, fourth milestone (Godot names the project does not define, C#
suppressions and build settings, C# test frameworks), VERIFY006 (a test file deleted
while its code remains), EXC006 (an error class derived from `SystemExit`), and SLEEP001
leaving zero-delay yields alone.

**Upgrading from 0.22.0.** No new dependency, and nothing can fail a gate that passed
unless a project raised a severity to `error`:

- **Python and JavaScript projects:** EXC006 (warning) is new for Python; VERIFY006
  (warning) reports deleted test files in `diff` and `gate --base`; SLEEP001 reports fewer
  findings (no zero delays).
- **C# projects** (those with `"**/*.cs"` in `include`): GODOT001, GODOT003 and GODOT005
  are warnings and GODOT002 and GODOT004 review, on whole-project runs; TYPE002 can report
  a `.csproj` with nullable reference types off (review); VERIFY001-VERIFY004 now read C#
  tests, and VERIFY003 compares `.csproj`, `Directory.Build.props` and `.editorconfig`
  in a diff (warning). New configuration keys are additions
  (`[tool.shockharness.rules.godot_names]`, `rules.sleep.csharp_sleep_apis`).

The cache schema is "36", so the first run after upgrading rebuilds the cache.

### Added
- **GODOT001-GODOT005 (C#, Godot projects): names the project does not define** (spec
  21.1 decision 51, milestone G4). Input actions not in `project.godot`'s Input Map
  (GODOT001), `GetNode` paths missing from the scenes that attach the script (GODOT002,
  review), editor connections to a method the target class does not define (GODOT003),
  groups nothing adds to (GODOT004, review), and string signal names the class does not
  declare (GODOT005). Whole-project runs only, when every scene and project file could be
  read; `[tool.shockharness.rules.godot_names]`. Cache schema "36".
- **C# suppressions, type escapes and build settings** (decision 52). VERIFY002 and
  TYPE001 read `#pragma warning disable`, `#nullable disable`, `[SuppressMessage]` and
  `// ReSharper disable`; TYPE001 reports `dynamic` and the null-forgiving `x!` (not the
  `null!`/`default!` late-initialization idiom); TYPE002 reports a `*.csproj` whose
  nullable reference types are off; VERIFY003 compares `*.csproj`,
  `Directory.Build.props` and `.editorconfig` (Nullable, TreatWarningsAsErrors,
  WarningsAsErrors, NoWarn, AnalysisMode/Level, analyzer severities).
- **C# test frameworks and sleeps** (decision 53). NUnit, xUnit, MSTest, gdUnit4 and
  GoDotTest cases, assertions, tautologies and skip attributes feed VERIFY001, VERIFY004
  and ROLE001; SLEEP001 reads `rules.sleep.csharp_sleep_apis` (`Thread.Sleep`,
  `Task.Delay`, `OS.DelayMsec`, `OS.DelayUsec`, `AwaitMillis`).
- **VERIFY006 (warning, needs a base revision): a test file deleted while its code
  remains** (spec 21.1 decision 50). In `diff` and `gate --base`, a test file of the base
  that the head neither has nor renamed is reported when every project module it imported
  is still there: the checks went, the code stayed. Tests that imported no project code,
  and tests deleted with their code, are not reported. Across MetaList's dead-code commit
  it reports the two test files whose modules stayed.
- **EXC006 (warning, Python): an error class derived from `SystemExit`** (spec 21.1
  decision 49). `except Exception` does not catch it, and raising it ends the process with
  its argument as the exit status. The remedy is an `Exception` subclass the entry point
  maps to an exit status. In the under-the-gate experiment it finds the two builds that
  did this; nothing in MetaList, ShockHarness or 672 files of pip, pytest, hypothesis,
  build and hatchling. Cache schema "35".

### Changed
- **SLEEP001 (version 2) leaves a zero delay alone.** `await asyncio.sleep(0)`,
  `setTimeout(resolve, 0)` and `setTimeout(resolve)` yield to the event loop; they do not
  wait for anything. On MetaList 4 of its 75 SLEEP001 findings go, among them
  `tagging_run.py`'s deliberate yield; nothing else changes. Cache schema "34".

### Fixed
- **The VERIFY001-VERIFY004 comparison honours each rule's languages**, as the per-file
  and cross-file phases do since G1. No verdict changed: C# had no verification facts
  before G4.

## [0.22.0] - 2026-10-21

STATE003 (state read outside the lock that guards its writes), and a call-graph fix for
names a function imports inside its body, which MetaList found through VERIFY005 false
positives.

**Upgrading from 0.21.0.** No new dependency, and nothing can fail a gate that passed
unless a project raised a severity to `error`:

- **STATE003** is on for Python production code at `review`.
- **The call-graph fix** resolves calls of function-local imports and of a module body's
  own imports. The rules that read the call graph can report differently, all at warning
  or review by default: VERIFY005 drops stubs it wrongly called stale; DEAD001/DEAD002
  (opt-in) can find a function a same-name fallback had kept alive; CPLX005 fan-out can
  rise on module bodies; ASYNC001-ASYNC003, INPUT001, ASSERT001, PROV001 and GUARD001 can
  see calls they missed. Property contracts and IMPORT002 do not use it.

The cache schema is "33", so the first run after upgrading rebuilds the cache.

### Added
- **STATE003 (review, Python): state read outside the lock that guards its writes** (spec
  21.1 decision 48). An attribute (or module `global`) that other code only writes while
  holding a lock, checked or passed on outside it, can change between the read and what
  follows. Methods named `*_locked`, or only called under the lock, are exempt, as are
  reads that only feed logging. Severity `rules.module_state.state003_severity`. On
  MetaList it reports the two reads of its encrypted-log race before the fix and not
  after, and the same race still present in a sibling class. Cache schema "33".

### Fixed
- **A name a function imports inside its body is now resolved** in the call graph
  (Python and JavaScript), like a module-level import: `from m import n` in a function
  binds `n` as a local, and a call of it was left unresolved. VERIFY005 then reported a
  patch of `m.n` as stale although the code reaches it on every call: MetaList reported
  8 such stubs in 5 tests against 0.21.0, all gone. Because the module body's own imports
  now resolve its calls too, the dead-code rules see one more truly dead function on
  MetaList (a same-name fallback had kept it alive), and two module bodies there count
  more resolved calls toward CPLX005 fan-out.

## [0.21.0] - 2026-10-21

C# for Godot .NET, third milestone: ShockHarness reads Godot's project and scene files,
resolves C# calls across files, finds dead code and unused scripts, and runs more of the
existing checks on C#.

**Upgrading from 0.20.0.** No new dependency. Nothing changes for a project that does not
add `"**/*.cs"` to its `include`. A project that does gets new findings, all warning or
review by default, so a gate that passed still passes unless the project raised one of
those sections to `error`: CPLX005 fan-out and file cycles, MAGIC002-MAGIC005, ASYNC001,
STATE001, IMPORT001, PROCESS001, STUB002 and STUB003, and, where `rules.dead_code` is on,
DEAD001/DEAD002. The new catalog keys (`csharp_task_apis`, `csharp_operations`,
`csharp_process_apis`, `csharp_index_callees`) are additions; `mock_modules` gains C#
mocking libraries, which only C# imports can match. The cache schema is "32", so the
first run after upgrading rebuilds the cache.

### Added
- **Godot projects and the C# call graph, milestone G3 part one** (decision 46).
  - ShockHarness reads a Godot project's `project.godot`, `.tscn` and `.tres` files
    (scripts attached to nodes, editor signal connections, animation method tracks,
    autoloads), with the standard library.
  - C# calls resolve through a project-wide type index (`partial` classes merged, typed
    receivers, `this`/`base`, static calls, constructors); CPLX005 reports C# fan-out and
    file cycles.
  - DEAD001 and DEAD002 run on C# (opt-in, as for every language) with Godot's roots:
    engine callbacks while their script is in use, scene connections, method names in
    strings and `MethodName.X`, `[Rpc]`, autoloads. A Godot script nothing uses is one
    finding for its class. Cache schema "32".
- **The per-file families on C#, milestone G3 part two** (decision 47): MAGIC002-MAGIC005,
  ASYNC001 (a dropped `Task`), STATE001 (static mutable fields), IMPORT001 (static
  initialization), PROCESS001 (`Process.Start`, `OS.Execute`), STUB002 (`using Moq;` in
  production code) and STUB003 run on C#. New catalogs: `csharp_task_apis`,
  `csharp_operations`, `csharp_process_apis`, `csharp_index_callees`; `mock_modules` adds
  `Moq`, `NSubstitute`, `FakeItEasy` and `Bogus`.

## [0.20.0] - 2026-10-21

IMPORT002 (imports across boundaries a project declares) and DOM003 (selections saved as
text positions and found again through text nodes only).

**Upgrading from 0.19.0.** No new dependency, and nothing can fail a gate that passed:

- **DOM003** is on by default for JavaScript and TypeScript in the production role, at
  `review`, which never gates. A project with a web editor may see new review findings;
  `rules.dom.dom003_severity` sets their severity.
- **IMPORT002** reports nothing until a project adds a
  `[[rules.import_boundaries.forbidden]]` entry.

The text report's "rules applied" line lists both new rules. The cache schema is "31", so
the first run after upgrading rebuilds the cache.

### Added
- **DOM003 (review, JavaScript and TypeScript): a selection saved as text positions and
  found again through text nodes only** (spec 21.1 decision 45). A position taken with a
  range's `toString().length` and later passed to a function that walks text nodes back
  (a `SHOW_TEXT` walker, or a walk testing `nodeType`) loses any point next to an image or
  other non-text node. Encoders and decoders are found across files, through imports,
  wrappers, locals and object properties; a point tested to be a text node is exempt.
  Severity `rules.dom.dom003_severity`. On MetaList it reports five calls before its
  right-click-on-images fix (the bug's two among them) and three after; on medium-editor,
  three calls of its export/import selection pair. Cache schema "31".
- **IMPORT002 (error, configured, Python and JavaScript): an import across a declared
  boundary** (spec 21.1 decision 44). `[[rules.import_boundaries.forbidden]]` entries name
  the files they bind (`importers` globs), the modules those may not import (`imported`
  globs), the names they may still take (`allowed_names`, required) and a `reason`. Every
  import is judged through its resolved edge, lazy imports included, so dotted, relative,
  submodule and JavaScript path imports of the module are all caught; with allowed names, an
  import of the whole module is reported. There is no entry by default, so nothing changes
  until a project declares one. Removing an entry, narrowing its globs or allowing more
  names is a loosening. On
  MetaList with its BKP001 pairs: none at 4d4e9847, and all four of four added imports, two
  of which BKP001 misses.

## [0.19.0] - 2026-10-19

VERIFY005 (a test's stub the code under test no longer reaches), the `diff` fix for the
whole-project rules, and DUP001/DUP002 leaving parallel implementations alone.

**Upgrading from 0.18.0.** No new dependency. Two changes can alter findings:

- **VERIFY005** is a new rule in the verification family, on wherever
  `rules.verification` is on, at that section's severity (`warning` by default, which
  does not gate). A project that set `rules.verification.severity = "error"` can see a
  gate fail on a stale stub; the fix is to stub what the code now calls, or to remove the
  stub, or a reasoned inline suppression.
- **`diff` and `gate --base`** judge DEAD001, DEAD002, DUP001 and DUP002 against each
  revision's own files, so their findings no longer show as new merely because files
  were added between the revisions; a gate that failed on those can now pass.

The DUP001/DUP002 change only removes groups. The cache schema is "30", so the first run
after upgrading rebuilds the cache.

### Fixed
- **`diff` and `gate --base` judged the whole-project rules against the working tree.**
  DEAD001, DEAD002, DUP001 and DUP002 (since 0.17.0) asked whether every included file
  was analyzed by listing the working tree's files, not the exported revision's. In a
  diff where files were added, the base revision then looked partial, those rules did
  not run on it, and their findings in the head showed as new. The check now lists the
  tree the files come from, and runs once per analysis instead of once per rule.

### Added
- **VERIFY005 (warning, Python): a stub the code under test no longer reaches** (spec 21.1
  decision 43). A test's `monkeypatch.setattr`, `mock.patch` or `patch.object` of a project
  function that none of the tests running it reaches: the test runs the real code it meant
  to stub out. Tripwires (stubs that raise, fail the test, or record into a list asserted
  empty) are exempt. It runs in a plain `check`, on whole-project runs, and may be
  suppressed inline with a reason. On MetaList it reports the four stubs a namespace
  switcher refactor stranded, and nothing before or after. Cache schema "30".

### Changed
- **DUP001 and DUP002 leave parallel implementations alone:** copies whose parameters or
  return are annotated with different types (a function over `ast.AST` and its twin over
  a tree-sitter `Node`) are not grouped, since an import cannot replace one with the
  other. On MetaList one DUP001 group goes (`_render_report` over two report types). Cache
  schema "29".
- **ShockHarness runs DUP001 and DUP002 on itself.** Its 20 groups of copied helpers are
  merged into one definition each, most of the tree-sitter ones into the new
  `ir/tree_sitter_common.py` shared by the JavaScript and C# adapters; four copies kept on
  purpose carry a reasoned suppression.

## [0.18.0] - 2026-10-19

C# for Godot .NET (opt-in, milestones G1 and G2), DUP001 and DUP002 (duplicated helpers),
`join` compositions in property contracts, and the dead-code false positives MetaList
found.

**Upgrading from 0.17.0.** One new runtime dependency, `tree-sitter-c-sharp`. C# is
opt-in: nothing changes for a project that does not add `"**/*.cs"` to its `include`.
DUP001 and DUP002 are opt-in and `review`. Two changes can alter findings:

- **Property contracts:** a `.join` with no `join` rule in the catalog now carries
  nothing, like an f-string with no rule, so a finding it reaches changes from unknown
  to violation. With the default `review` severities nothing gates; a project that set
  `PROP001` to `error` can see a gate fail where the join reaches a sink, and the fix is
  a `join` composition rule or a sanitizing producer.
- **BOOL001:** the default `allowed_callees` adds Godot's setters (below), so a project
  using the defaults gets fewer BOOL001 findings, never more.

The DEAD001/DEAD002 fixes only remove false positives. The cache schema is "28", so the
first run after upgrading rebuilds the cache.

### Added
- **C# (Godot .NET), milestone G1** (spec 21.1 decision 40, `docs/proposal-godot.md`).
  `.cs` files are parsed with `tree-sitter-c-sharp` (a new runtime dependency, approved
  2026-10-19) and checked by MAGIC001, CPLX001-CPLX004, CPLX006, SUPP001 and SUPP002. The
  other rules do not run on C# yet: `coverage.rules_not_applicable` lists them, and the
  text report warns. Named numbers in C#: `const` fields, `static readonly` and
  `[Export]` members of literal arithmetic or of a Godot value type built from literals
  (`static readonly Vector2 Spawn = new(64, 32);`), and explicit enum values.
  - **C# is opt-in.** The default `include` does not list `**/*.cs`; a project turns
    C# on by adding `"**/*.cs"` to its own `include` (docs/configuration.md). Upgrading
    changes nothing for a project with `.cs` files that relies on the default include.
    The default `exclude` adds `**/.godot/**`, `**/bin/**/*.cs` and `**/obj/**/*.cs`, and
    the default roles `**/*.g.cs` and `**/*.Designer.cs` (generated) and `**/*Tests.cs`
    and `**/*.Tests/**` (test); none of them matches a file the defaults analyze today.
  - `coverage.rules_not_applicable`: per analyzed language, the implemented rules that
    never run on it.
- **C# exceptions and defaults, milestone G2 part one** (decision 41). EXC001-EXC003,
  EXC005 and DEF001-DEF006 run on C# (opt-in). Catch types are matched as written, by
  their last segments (`IOException` against a `System.IO.IOException` boundary); a
  `when (e is A or B)` filter narrows; `throw e;` is EXC002 (it resets the stack trace).
  Boundaries accept `language = "csharp"`. Defaults: optional parameters (not
  `[CallerMemberName]` ones), `??`/`??=` (not `?? throw`), null ternaries,
  `string.IsNullOrEmpty` ternaries, `GetValueOrDefault`, LINQ `*OrDefault`, `GetMeta`,
  `TryGetValue`/`ContainsKey` ternaries, environment reads, `ProjectSettings.GetSetting`
  and `ConfigFile.GetValue` fallbacks. Cache schema "28".
- **C# results, Boolean arguments and placeholders, G2 part two** (decision 42).
  RESULT001 (a new `rules.results.csharp_must_use` of pure calls), BOOL001 and STUB001
  (`throw new NotImplementedException()`) run on C#.
  - `rules.boolean_arguments.allowed_callees` adds Godot's `SetShaderParameter`, `Set`,
    `SetDeferred`, `SetMeta`, `SetValue`, `SetSetting`, `Call`, `CallDeferred`, `Rpc`,
    `RpcId` and `EmitSignal`, whose first argument names what the Boolean is for. A
    project that sets its own `allowed_callees` keeps its list.
- **DUP001 and DUP002 (review, opt-in, Python and JavaScript): helpers written out in
  several files, and copies that have drifted apart** (spec 21.1 decision 39). DUP001:
  identical function bodies in two or more files, compared with comments, layout and
  local names set aside and with a string's mention of its own file or function replaced.
  DUP002: functions of the same name (leading underscores and case aside) in several files
  that are alike but not the same, with the first line where they differ; constructors and
  overrides within one class family are left out.
  - Turn them on with `[tool.shockharness.rules.duplicates] enabled = true`. Settings:
    `roles`, `min_statements`, `min_tokens`, `similarity`, `severity`,
    `dup002_severity`. Turning the family off, removing a role or raising a threshold is
    a VERIFY003 loosening.
  - On MetaList, outside its browser test scripts: 43 DUP001 and 24 DUP002, among them
    copies that throw different exception types and one that escapes a selector the other
    does not. Cache schema "27"; the function shapes add about 9% to a cold run.
- **Property contracts: `join` compositions.** `"sep".join(items)` (Python) and
  `[a, b].join(sep)` (JavaScript) compose by the catalog's `join` rules. The parts are a
  non-literal separator and the items: the elements of a list, tuple, set or array
  literal, or the element expression of a comprehension or generator expression. A
  finding names the part that falls short (`"\n".join(prefix + line for line in
  text.splitlines())` names `prefix + line`).
  - A join over any other value (a variable, `.map(...)`) stays unknown, with a message
    that says so.
  - A join that a catalog has no `join` rule for now carries nothing, like an f-string
    with no rule: such findings change from unknown to violation. On MetaList: 15 more
    PROP004 review findings (functions returning `""` on one path and a join on
    another), nothing gating.

### Changed
- **write-compliant-code skill:** a checklist item for values the program offers and then
  checks. Where code rejects a value outside a set ("not a known tag") that other code
  offers the user, both build from one function, and a test checks that every offered
  value is accepted. From MetaList, where two separately built tag vocabularies drifted
  apart; no static rule can see the drift across an HTTP request.

### Fixed
- **A rule's `languages` is now honored for every family.** The per-file phase ran
  MAGIC001/MAGIC004/MAGIC005, EXC001-EXC003, DEF001-DEF006, the complexity rules and
  ROLE001 on any file, and the cross-file phases read every file's facts, whatever the
  rule's languages; this changed nothing while every language had every family. No
  Python, JavaScript or TypeScript verdict changes.
- **DEAD001/DEAD002 false positives MetaList found** (155 findings, 134 real): methods of
  an exported instance (`export const S = Object.freeze(new Store())`, then
  `S.createScope()`); a method called on a call's result (`Guard(\n x\n).check()`); a
  function another module re-exports; a method of a class whose framework base is a
  grandparent (`server_bind` under `ThreadingHTTPServer`); the methods of a stream
  assigned to `sys.stdout`; `[project.scripts]` targets. On MetaList: 154 findings to
  145, the nine removed all among those false positives, nothing added. Cache schema "26".

## [0.17.0] - 2026-10-19

DEAD001 and DEAD002 (spec 21.1 decision 38): functions nothing in production reaches,
reported by cluster.

**Upgrading from 0.16.0.** No change makes a passing gate fail: both rules are opt-in
(`rules.dead_code.enabled`, off by default) and `review`. The cache schema is "25", so
the first run after upgrading rebuilds the cache.

### Added
- **DEAD001 and DEAD002 (review, opt-in, Python and JavaScript): functions nothing in
  production reaches** (spec 21.1 decision 38). One finding per dead head, listing what
  is reachable only through it; DEAD002 when only tests reach it.
  - Turn them on with `[tool.shockharness.rules.dead_code] enabled = true`. Settings:
    `roles`, `entry_points` (globs over `path::qualified.name` for callers the analysis
    cannot see), `severity` and `dead002_severity`. Turning the family off, adding an
    entry point or removing a role is a VERIFY003 loosening.
  - Judged only when the run analyzed every included file: a run over a path, and the
    edit hook, report nothing.
  - New per-file facts: functions named as values, attribute uses, registering
    decorators and `__all__`. Cache schema "25"; the facts add about 4% to a cold run.
  - On MetaList: 154 findings, among them the `build_note_tree` cluster that held the
    lost search highlighting. On ShockHarness: 16. The 12 dead functions are deleted (108
    lines), and the repository now turns the rules on, with the contracts runtime's public
    API as its one entry point.

### Removed
- Internal functions nothing in production called, found by DEAD001/DEAD002:
  `shockharness.analysis.analyze_file` (use `analyze_files([file], ...)` or
  `shockharness.api.analyze_paths`), `shockharness.skills.skill_names` (read
  `SKILL_NAMES`), `python_receivers.receiver_parameter`, and eight unused helpers. None
  was part of the documented API.

## [0.16.0] - 2026-10-19

TYPE002 (spec 21.1 decision 33), and ShockHarness checks its own annotations with mypy.

**Upgrading from 0.15.0.** No change makes a passing gate fail: TYPE002 is `review` and
reports once per run, only for a project with at least 20 annotated functions and no type
checker configured. The cache schema is "24".

### Added
- **TYPE002 (review, Python): type annotations nothing checks** (spec 21.1 decision 33).
  It reports once per run when at least half of the production functions, and at least
  20 of them, carry an annotation and the root configures no type checker (mypy,
  pyright, basedpyright, pyre or ty).
  - Settings: `rules.types.annotated_share`, `min_annotated_functions` and
    `type002_severity`. Relaxing any of them is a VERIFY003 loosening, and threshold
    loosenings now compare decimal values too.
  - On MetaList it reports nothing, because MetaList configures `[tool.mypy]`. On
    ShockHarness itself it reports 2,226 of 2,226 functions.
  - Cache schema "24".
- **ShockHarness checks its own annotations:** `mypy --strict` over `src` (`[tool.mypy]`
  in `pyproject.toml`, `mypy` in the dev extra) runs in CI. Its 29 findings were fixed
  without `cast` or `# type: ignore`: narrowing, real annotations, and asserts on
  internal invariants. One of them was `config.section` used to read a scalar, which the
  policy tier now reads with `value_at`.

## [0.15.0] - 2026-10-18

The property-contracts phase reuses each file's findings while nothing they depend on
changed.

**Upgrading from 0.14.0.** No change makes a passing gate fail: the findings are
identical to a full recompute. The report's `coverage.cache` gains `contracts_reused` and
`contracts_files`. A `contracts.json` written by 0.14.0 is not read, so the first run
computes the phase for every file.

### Changed
- **The property-contracts phase is incremental.** Each checked file's findings are
  cached with what they depended on:
  - every name its analysis resolved, and where to;
  - the text of every module involved, including modules reached only through a
    memoized callee result;
  - JavaScript existence checks;
  - for an override check, the analyzed classes.

  A later run reuses a file's entry while all of that holds, and computes only the other
  files. On MetaList an edit to one file recomputes 3 to 7 of 981 files: a check after
  an edit takes about 10 s, where 0.14.0 took about 16.6 s, and the findings are
  identical to a full recompute in every scenario tried. `coverage.cache` gains
  `contracts_reused` and `contracts_files`, and `stale` now means some files reused
  their entry.

## [0.14.0] - 2026-10-18

MAGIC005, the disguised numbers of the under-the-gate rounds, and skill wording from the
same experiment.

**Upgrading from 0.13.0.** One change can make a passing gate fail: **MAGIC005 is a new
warning**, reported where MAGIC001 applies. On MetaList and the third-party corpus it
reports nothing. To lower it, set `rules.magic_numbers.magic005_severity = "review"`
(VERIFY003 reports that as a loosening). The cache schema is "23".

### Added
- **MAGIC005 (warning): a number written as something else**, the disguises agents used
  under the gate:
  - `len("  ")` of whitespace, the length of a display;
  - `int("30")`, `Number("3000")`, `+"30"`;
  - numbers inside a parsed inline string (`tomllib.loads("max_age_hours = 24")`,
    `JSON.parse`);
  - `indent="  "` or a module-level constant of spaces.

  It applies where MAGIC001 applies, so the test exemption covers it, and reports
  values outside `allowed_values`. The setting is
  `rules.magic_numbers.magic005_severity`. Measured: no findings on MetaList or the
  third-party corpus, and 11 of the 12 production disguises in the experiment's gated
  builds. Cache schema "23".
- The behavior suite gains `magic001/report-indent`, with the detectors `spaces_indent`
  and `whitespace_length`.

### Changed
- The skills: a boundary names what the outside world raises, never the project's own
  error; asserts are not for validating configuration either; MAGIC005's shapes are
  named beside MAGIC004's.
- ShockHarness's own code strips prefixes with `removeprefix`/`removesuffix` instead of
  slicing by `len("0x")`.

## [0.13.0] - 2026-10-18

JavaScript methods through their receivers (`docs/proposal-receivers.md`, R2), and a fix
for PROP005 with a JavaScript registration module.

**Upgrading from 0.12.0.** One change can make a passing gate fail:
- **The call graph resolves more JavaScript calls** (below). ASYNC001 sees an `async`
  method of a singleton or object called without `await`. On MetaList that is two
  ASYNC001 violations, and both are real. CPLX005 counts the new edges. On the corpus
  nothing changes. Existing findings keep their fingerprints.
- The cache schema is "22", so the first run after the upgrade analyzes every file.

### Changed
- **JavaScript methods through exact receivers** (`docs/proposal-receivers.md`, R2;
  cache schema "22"), in property contracts and in the call graph:
  - `this.m()` in a class's instance method, resolved when no analyzed subclass
    overrides `m` and probable when one does;
  - a module-level object literal's method (`export const Auth = { init() {...} }`,
    `Object.freeze({...})` too), unless its module assigns that method again;
  - a module-level `new` singleton (`export const store = new Store()`), in its module
    or imported by name;
  - a constructed local, and `new Store().m()`;
  - in the call graph also `Class.m()`, and `ns.f()` / `u.f()` through a namespace
    import or `require`.

  `this` in an object literal's method is probable in the graph and unknown to the
  contracts: it depends on how the method is called. A default import's attribute stays
  probable.

  **This can make a passing gate fail**, like R1. On MetaList it adds two ASYNC001
  violations: `CommandPalette.notifyAppUpdate()` is an `async` method of a singleton,
  called without `await` in `main.js` and `auth.js`. Four CPLX005 messages change
  wording and keep their fingerprints. On the corpus nothing changes.

### Fixed
- **PROP005 with a JavaScript `registration_module` crashed** (0.11.0 and 0.12.0) with a
  `TypeError`, because R1 passed the Python index's receivers to the JavaScript index.

## [0.12.0] - 2026-10-18

Faster warm runs, from MetaList's report ("41 seconds WITH cached files").

**Upgrading from 0.11.0.** No change makes a passing gate fail: the findings are
identical. The report's `coverage.cache` block gains `contracts`, and a cache directory
gains `contracts.json`.

### Changed
- **Faster warm runs.**
  - The cache decoder builds one decoder per type, instead of reading type hints and
    building an error path for each of millions of objects.
  - The property contracts look up method overrides by name, and walk each unit's body
    once.
  - **The property-contracts phase is cached** (`contracts.json`). Its findings are
    reused while every analyzed file and every other file it looked at or read is
    unchanged. `coverage.cache.contracts` says `hit`, `miss`, `stale` or `off`. This is
    the one exception to "cross-file work is recomputed on every run".

  On MetaList's tree (981 files, contracts on, every file cached), 0.11.0 took 26.4 s.
  It now takes 16.6 s when the contracts are computed and 8.2 s when they are reused.
  The findings are identical.

## [0.11.0] - 2026-10-18

Methods through their receivers, in Python (`docs/proposal-receivers.md`, R1), and
MetaList's crash report on 0.10.0.

**Upgrading from 0.10.0.** One change can make a passing gate fail:
- **The call graph resolves more Python calls** (below), so CPLX005 counts more fan-out
  targets. On MetaList that is 4 new CPLX005 warnings. On the third-party corpus
  (32,667 findings) nothing changes. No ASYNC001, INPUT001, PROV001 or GUARD001 finding
  appeared or disappeared on either. Existing findings keep their fingerprints.
- Property contracts are still opt-in. In a repository that enables them, calls that
  were `unknown` can become passes or PROP001 violations.
- The cache schema is "21", so the first run after the upgrade analyzes every file.

### Added
- **Property contracts resolve Python methods through their receivers**
  (`docs/proposal-receivers.md`, R1). A method call is checked against the method's
  contract, and its result composes, when the receiver's class is exact:
  - `self.m()` / `cls.m()` in a class no analyzed subclass overrides `m` in;
  - a module-level singleton bound once to a constructor call (`store = Store()`), in its
    module or imported;
  - a local the function constructs once;
  - `Class.m()` and `Class(...).m()`.

  The arguments start after the `self` or `cls` the receiver supplies. A property is not
  a method. Calls that were `unknown` can become passes or PROP001 violations. The family
  is opt-in, so no gate that has it off changes.

### Fixed
- **Property contracts no longer crash on an object literal's methods (JavaScript).**
  With the family enabled, `shockharness check` exited 3 with `KeyError: 'document'` on any
  method of an object literal that reads a name its enclosing unit does not bind
  (`export const Tracker = { start() { document.addEventListener(...) } }`, a stream
  source's `start(controller)`). The flow walked into those methods' bodies, while the
  unit's names were collected without entering them. Every nested function, method and
  class is now its own unit for both. From MetaList on 0.10.0.

### Changed
- **The call graph resolves Python methods through exact receivers**
  (`docs/proposal-receivers.md`, R1; cache schema "21").
  - `self.m()` / `cls.m()` that the class or a project base defines are `resolved` when
    no analyzed subclass overrides `m`, and stay `probable` when one does. The reason
    names the overriding class.
  - These are `resolved` too: a module-level singleton's method (`store.save()`,
    imported or not), a constructed local's method, `Class.m()` through a module-level
    class or an import, and an attribute call on an analyzed module alias (`u.helper()`).
  - JavaScript is unchanged (R2).

  **This can make a passing gate fail.** CPLX005 counts the new edges in fan-out.
  ASYNC001 reports a dropped coroutine from a promoted `self.m()` as a violation, not
  unknown. INPUT001, PROV001 and GUARD001 follow the new sites. See STATUS.md for the
  measured diff on MetaList and the third-party corpus. Existing findings keep their
  fingerprints.

## [0.10.0] - 2026-10-18

Property contracts (opt-in, milestones P1a to P3), STATE002, and MetaList's feedback on
0.9.0.

**Upgrading from 0.9.0.** No change makes a passing gate fail:
- **Property contracts are off** in every profile until
  `rules.property_contracts.enabled = true`. Their findings are `review`, except PROP003
  (an unknown property name), which only a repository that turned the family on can hit.
- **STATE002 ships at `review`** and only reports.
- **ASYNC003** reports fewer findings (a top-level batch checked on the next line).
- The cache schema is "20", so the first run after the upgrade analyzes every file.

### Added
- The README section "What ShockHarness insists on": the disciplines each rule family
  enforces.
- Property contracts, milestone P3 (spec v0.12):
  - **Parametric summaries (decision 48).** `preserves(result, x)` on a parameter that
    requires nothing passes on what each caller's argument carried, in both languages.
  - **`enforcement = "complete"` and `complete_paths`** with `PROP008` (review): a
    parameter without `requires`, or a return without `produces`/`preserves`, in a
    module-level function or method.
  - **`shockharness exceptions`** lists every no-property `requires(x)` under `complete`
    (the sorry count).
  - **Skills.** The seventh skill, `property-contracts`. `write-compliant-code` gains
    principle 10, and `fix-violations` the PROP001 and PROP008 procedures.
  - **Behavior suite.** Three PROP001 cases (unambiguous, judgment, ask) with
    `requires_removed`, `produces_without_test` and `callee_moved_to_tests` detectors.
  - VERIFY003 reports `enforcement` lowered and `complete_paths` narrowed.
- Property contracts, milestone P2 (spec v0.8):
  - **Transitive results.** A callee's result is followed through its own calls, up to
    `max_depth` (3); deeper calls and recursion are unknown. A function returning
    another's result carries the property through.
  - **Await and generators (§5.2c).** `await` of a project async function gives its
    result. A `for`/`for await` over a project generator binds its item set; `yield
    from`/`yield*` delegate. A coroutine used without `await` carries nothing.
  - **New rules:** `PROP002` (a produces outside the declared producers) and `PROP004`
    (returns with different properties).
  - **PROP005's predicate half:** with `runtime_mode_required = "verify"`, each
    non-static property the `registration_module` never registers.
  - **`verify` mode and `register(name, predicate, description)`** in both runtime files.
  - A TypeScript fixture, the §13.2 metamorphic tests, and `docs/property-contracts.md`.
  - VERIFY003 reports `runtime_mode_required` lowered, and `max_depth` lowered while
    `fail_on_unknown` is false. Raising `max_depth` is never a loosening. While
    `fail_on_unknown` is true, a `max_depth` change either way is a review-level
    analysis-scope change in a revision diff (decision 47, which corrects §8).
  - The `"<name>[]"` target matches by the receiver's final identifier (decision 43).
- Property contracts, milestone P1b (JavaScript; spec v0.7):
  - **JavaScript and TypeScript files.** `requires` / `produces` / `preserves` /
    `preserves_except` are checked at call sites. Contracts are read one hop through
    `import`, `require`, re-exports and `export default`, as `path:export`.
  - **Callee sinks**: project, package and global, such as `fetch:1`.
  - **Assignment-target sinks** in both languages: `target = "innerHTML"`, or
    `"headers[]"` for a subscript of a named receiver.
  - **Compositions** (`template_literal`, `concat`, `fstring`, `format`) and
    `literal_satisfies`. The finding names the part that falls short.
  - **The JavaScript runtime file** `contracts.js` with `contracts.d.ts`, installed by
    `shockharness contracts install --language javascript`. It is identity until
    `enable("check", staticProperties)` or the pre-load object
    `globalThis.__shockharnessContracts`.
  - **Checks:** PROP005 and PROP006 for JavaScript test bootstraps, and `config
    validate` for JavaScript references.
  - **VERIFY003** reports added or wider composition rules, `literal_satisfies` set, and
    target sinks removed.
- Property contracts, milestone P1a (opt-in, Python; spec v0.5). The family is off by
  default and in every profile.
  - **Declarations:** `requires` / `produces` / `preserves` / `preserves_except`.
  - **Checks:** at call sites against the callee's own declared contract (one hop,
    across files) and at catalog callee sinks (`callee:N`, keyword arguments mapped for
    project callees).
  - **Rules:** `PROP001` (review), `PROP003` (error unless `allow_undeclared`),
    `PROP006` and `PROP007` (review).
  - **Unknown:** every await, generator and `.join` build.
  - **Configuration:** `rules.property_contracts` with `config validate` resolving the
    catalog's references. VERIFY003 covers every key.
  - **Runtime:** the runtime file `src/shockharness/contracts/runtime/contracts.py`
    (identity until `enable("check", static_properties)`; `check` mode; static
    properties counted by `report()`).
  - **Install:** `shockharness contracts install --language python --dest PATH` and
    `--check`, recorded in `.shockharness-contracts.json`. Nothing is published.
  - `RESULT001` permits the four declarations as statements when they resolve to the
    runtime module.
  - Spec v0.6 (decisions 37 and 38):
    - `enable` raises unless its second argument is a list of strings.
    - `PROP005` (review) reports a test bootstrap's `enable(...)` whose literal list is
      not the catalog's `runtime = "static"` set, and a non-literal list is `PROP006`.
    - `shockharness contracts static-properties` prints the list to paste.
    - The §11.1 fixture uses the `produces(preserves(expr, x), "p")` idiom.
- `STATE002` (`rules.module_state`, review, Python): a shared object published before
  it is initialized. A global, or `self.<attr>` outside a constructor, is assigned a
  new object and then has its fields set in the same function, so another thread can
  read it half-built. Severity `rules.module_state.state002_severity`. From MetaList's
  encryption-service race. Measured: exactly MetaList's two pre-fix functions, nothing
  else in about 2,500 files. The cache schema is "20".

### Changed (feedback from MetaList on 0.9.0)
- `ASYNC003`: a `Promise.allSettled(...)` at a script's top level is checked against
  the statements that follow it in its block, as one inside a function is checked
  against the function. A top-level batch checked on the next line, inside a
  top-level `try`, is no longer reported; one that nothing after it checks still is.
  The cache schema is "19".

## [0.9.0] - 2026-10-17

Fewer reasons to work around the gate: the findings of the under-the-gate experiment
(three rounds) and of MetaList. New rules ship at `warning` or `review` (decision 9).

**Upgrading from 0.8.0.** No change makes a passing gate fail:
- **Named constants (decision 36).** MAGIC001 no longer reports the literal of a
  module-level named constant definition (`MAX_PAGES = 8`, `const SETTLE_MS = 400`,
  `CHUNK_BYTES = 64 * 1024`) in any profile. `named_constant_definitions = "allow"` is
  now the strict default too; `"report"` is a tightening. An existing
  `# shockharness: ignore[MAGIC001]` on such a line now matches nothing and is a
  SUPP002 warning: delete the comment and keep the citation as a plain comment.
- **Fewer false alarms.** DEF005 (an entry point's exit status inside a boundary,
  decision 37), DEF002 (an assigned grouping `setdefault`) and BOOL001 (assertion
  arguments) report fewer findings.
- **New findings, never failing the gate.** EXC005 (warning) and MAGIC004 (review) are
  new; they report but never fail.

### Added
- `EXC005` (`rules.exceptions`, warning): a declared catch boundary naming an
  exception that no catch in the files it covers catches, reported at the
  boundary's line in the configuration file. Judged only when every covered file
  was analyzed in the run. From the under-the-gate experiment, where agents
  declared boundaries ahead of the code.
- `MAGIC004` (`rules.magic_numbers`, review, Python, JavaScript and TypeScript): a
  named constant whose name only spells a number (`TWO = 2`, `ONE_HUNDRED = 100`,
  `VALUE_100 = 100`). Severity `rules.magic_numbers.magic004_severity`.

### Changed
- MAGIC001 under `strict`: named constant definitions are allowed (decision 36). The
  `recommended` and `minimal` profiles no longer set the option, since it is the
  default. Measured before the change: 965 MetaList findings, all 35 in
  ShockHarness's own `src`, and 58 in the under-the-gate experiment's agent-written
  builds go away, and no constant name among them only spells a number.
- The skills say a fixed value is a module-level named constant that cites its
  source, with no suppression, never named after its value or disguised. They also
  say:
  * a failed read or write is reported, never dropped;
  * a boundary is declared for the catch being written;
  * a project error never derives from `SystemExit`;
  * test values stay in the test;
  * the `python -O` refusal is only for code that asserts.
- `DEF002`: `x = m.setdefault(k, <empty container>)` whose next statement mutates `x`
  is the grouping idiom, like the chained form, and is not reported.
- `DEF005` (decision 37): inside a declared boundary, an entry point's handler that
  returns a named non-zero exit status (`return EXIT_UNREADABLE`) is not reported.
  The entry point is `main`, a function called under `if __name__ == "__main__":`, or
  one named in `[project.scripts]`. The remediation says not to re-implement a
  library's validation to avoid its exception.
- `BOOL001`: the expected value of an assertion (`assertEqual(x, True)`,
  `assert.equal(v, true)`) is not reported. MetaList had 159 of its 353 findings there.
- ShockHarness's own configuration drops its `constants.py` MAGIC001 override.
- The consumer upgrade check injects a literal in an expression, and the examples
  keep their RFC citations as plain comments.
- The cache schema is "18".

## [0.8.0] - 2026-10-17

The edit-time hook for Claude Code, decisions 34 and 35, MAGIC002, DOM001 and DOM002,
and two more rounds of MetaList feedback. New rules ship at `warning` or `review`
(decision 9).

**Upgrading from 0.7.0.** Two changes can move a gate verdict, and a third changes
new projects:
- **Switching a rule off is now an error (decision 35).** `check` and the edit
  hook compare the configuration file with the accepted one (the merge base with
  `origin/HEAD`, else `HEAD`). Every loosening except a catch boundary naming one
  file is a `VERIFY003` error until a person commits it. In `diff` and `gate
  --base`, the same changes since the base are errors too (they were warnings), so
  a pull request that switches a rule off fails. Set
  `rules.verification.rule_switching_severity = "warning"` for the old behavior;
  that is itself a reported deviation.
- **`DEF002` statement forms (decision 34)**, below.
- `shockharness init` now writes the test exemption (`MAGIC001` and `DEF001` off for
  the test role). Existing configuration files are not changed.

**DEF002 statement forms.** `DEF002` (version 2) now recognizes the `return` statement form of
the membership fallback in Python: `if k in m: return m[k]` followed by
`return v`, and `if k not in m: return v` followed by `return m[k]`. It is an
error under `missing_value_fallbacks = "forbid"`, like `m[k] if k in m else v`,
so a gate that passed can fail. Measured: MetaList 20, ShockHarness's own `src`
8 (fixed in the same change), pip, pytest, hypothesis, build, hatchling and npm
together 1.

### Added
- Spec 21.1 decision 34: `DEF002` follows fallback helpers. A call of a
  module-level function of the same file whose body (after a docstring and
  checks that only raise) is a lookup with a default that is one of its
  parameters (`m.get(k, default)`, `getattr(o, a, default)`, either membership
  form, `try: return m[k]` / `except KeyError: return default`) is reported at
  the call, with the argument as the fallback. New mode
  `rules.defaults.fallback_helpers`, `"review"` in strict for this release.
  MetaList's `_mapping_value_or`, whose 26 literal defaults reset 11 server-kept
  reminder fields on every edit, gives 32 such findings on its pre-fix tree.
  The `fix-violations` skill and DEF002's remediation no longer recommend a
  helper that returns a stand-in for a missing value. The cache schema is "17".
- Spec 21.1 decision 35, from the under-the-gate experiment (round 2):
  - `shockharness init`, and `skills install` in a project with no
    configuration, write the test exemption ShockHarness's own configuration
    has (`roles = ["test"]`, `disable = ["MAGIC001", "DEF001"]`). The skills
    say `init` has done it.
  - `check` and the edit hook report every rule the configuration switches
    off since the accepted configuration (the merge base with `origin/HEAD`,
    else `HEAD`, else what `init` writes) as `VERIFY003`. Every loosening
    counts except a catch boundary naming one file. The new key
    `rules.verification.rule_switching_severity` (default `"error"`) sets the
    severity, so `check` fails until a person commits the change. The hook
    feeds it back as soon as the configuration file changes, whichever tool
    changed it. `coverage.accepted_configuration` says what was compared.
  - `skills install --hook --lock` writes the project's configuration
    (boundaries aside) as a `--policy` file under
    `~/.config/shockharness/locks/` and runs the hook with it.
  - **Behavior change:** in `diff` and `gate --base`, a configuration change
    that switches a rule off is now a `VERIFY003` error (it was a warning, per
    decision 9), so such a pull request fails the gate. Set
    `rule_switching_severity = "warning"` to keep the old behavior; that is
    itself a reported deviation.
- Edit-time feedback for Claude Code: `shockharness hook claude-code post-edit`
  reads a `PostToolUse` tool call on stdin, analyzes the edited file and feeds
  its findings (`--fail-on`, `warning` by default) back to the agent with exit 2.
  `skills install --agent claude --hook` appends the hook to the project's
  `.claude/settings.json` (once, never replacing existing hooks); without
  `--hook`, it offers it.
  The hook skips files that are not source (`pyproject.toml`, `README.md`).
  It also runs after shell commands (matcher `Edit|Write|MultiEdit|Bash`) and
  then checks the source files `git status` shows as changed since its last run:
  agents often write files through the shell. Each run is logged in
  `.shockharness-cache/hook/runs.jsonl`; `skills install --hook` updates an older
  matcher.
- `DOM002` (`rules.dom`, review, JavaScript and TypeScript, opt-in): a pressable
  element attached to `document.body` (directly, or appended into a container a
  function attaches and returns) that matches no selector of the skip lists named
  in `press_exclusions` (`"path:function"`): its presses reach that handler as
  presses outside (decision 32). Skip lists follow constants and helper calls
  through imports. Nothing is reported while `press_exclusions` is empty. New
  keys: `press_exclusions`, `dom002_severity`. The cache schema is "16".

### Changed (MetaList's rule ideas)
- `MAGIC003`: not reported for a name in the new `standard_targets` (`tabIndex`,
  where HTML defines `-1`), nor for a `-1` passed to a callee the same file also
  passes `1` (`move(-1)` beside `move(1)`).
- `RESULT001`: a method of a string literal is recorded as the `str` method, and
  `str.join` is in the Python defaults, so `", ".join(parts)` alone on a line is
  reported. The cache schema is "15".
- Skills: `pre-commit-review` asks that an element attached to `document.body`
  is skipped by every page-level "outside press" handler and pressed by a
  browser test in each mode; `fix-violations` warns that a fallback helper
  (`_mapping_value_or`) is `.get` under another name, and asks whether a type
  checker runs before acting on TYPE001.

### Changed (feedback from MetaList on 0.7.0, second round)
- `RESULT001`: a catalog entry can give the number of positional arguments the
  pure callee takes (`.replace/2-3`, JavaScript `.replace/2`); a call with
  another count is a different method of that name (`location.replace(url)`,
  `Path.replace(p)`, `store.replaceAll({...})`) and is not reported. A call in a
  `try` body with a handler is not reported (`host.encode("idna")` run to
  validate). `.join` left the Python defaults: on a name it was `Thread.join`
  in every case measured. On the 790-file corpus 25 findings became 5.
- `ASYNC001`: a `void` call is not reported when the project registers a global
  unhandled-rejection listener that reports (`window.addEventListener(
  "unhandledrejection", ...)`, `process.on("unhandledRejection", ...)`).
- `GUARD001`: not reported when the callee checks that argument itself among its
  leading statements (`if not isinstance(tags, str): raise TypeError(...)`).
- `STUB003` runs across files: a method of a class some project class extends is
  a hook default and is not reported; an override that repeats an always-yes
  base method is reported as redundant. Bases are resolved through imports.
- `ROLE001`: the default `support_files` cover `**/*fixture*` (singular),
  `**/*helper*`, `**/support/**` and `**/*_support.*`.
- The cache schema is "14".

### Changed (feedback from MetaList on 0.7.0)
- `ASYNC003` does not report a Python `gather(..., return_exceptions=True)` in a
  `finally` / `except` block of a function that cancelled tasks before it (the
  wait for cancellation to finish).
- `PROCESS001` does not report an exit status returned to the caller with the
  result (`return subprocess.run(...)`, or through a returned name).
- `INPUT002` counts a `node:assert` call given the value (`assert(...)`,
  `assert.ok`, `assert.equal`, through nested calls) as a check.
- `ASSERT001` reports an assert once, listing every external source that reaches
  it (it reported one finding per source).
- Dataflow: a method called on a computed receiver (`Path(p).read_text()`,
  `conn.cursor().execute(q)`) now matches `.name` catalog entries. The cache
  schema is "12".

### Added
- `MAGIC002` (`rules.magic_strings`, review, Python, JavaScript and TypeScript):
  a string literal written out at least 3 times in at least 2 files and compared
  (`==`, `in`, `===`, `case`) in at least 2 of them, reported once at its first
  use with the other places (decision 31). Messages of log calls and exceptions,
  docstrings, f-string and template parts, annotations, TypeScript literal types,
  import specifiers and UPPER_SNAKE_CASE definitions are never counted. New keys:
  `roles`, `min_length`, `min_occurrences`, `min_files`, `min_compared_files`,
  `kinds`, `message_callees`, `allowed`. No rule is left unimplemented:
  `coverage.rules_not_implemented` is `[]`, and the text report omits the line
  when the list is empty. The cache schema is "13".
- `DOM001` (`rules.dom`, warning, JavaScript and TypeScript): a delegated event
  handler that tests `event.target instanceof HTMLElement` before
  `event.target.closest(...)`, which silently drops clicks on SVG icons inside
  buttons (decision 27). The cache schema is "11".

## [0.7.0] - 2026-10-17

Milestones H4, H5, H-TS and H6 of specification section 21, ROLE001, the assert
rework, MAGIC003, and feedback rounds from MetaList. Every new rule ships at
`warning` or `review` (decision 9).

**Upgrading from 0.6.0.** Three changes can move a gate verdict:
- TypeScript (`.ts`, `.tsx`, `.mts`, `.cts`) is analyzed by default: a
  TypeScript repository gets its MAGIC001, EXC and DEF findings (errors) instead
  of unsupported-source warnings. Set `include` to the 0.6.0 globs to keep the
  old scope.
- `-1` is allowed by default (`allow_unary_negative_one = true`): fewer MAGIC001
  errors in `strict` and `minimal`.
- A very long Python expression is analyzed instead of crashing (or, on CPython
  3.11, is a parse failure with its reason).

Otherwise: ASSERT001 reports only asserts on external input (fewer warnings);
the CLI refuses to run under `python -O`; existing configurations stay valid;
caches are invalidated automatically (cache schema "10").

### Added (MAGIC003, decision 30)
- `MAGIC003` (`rules.sentinels`, review): a `-1` standing for a value (assigned,
  returned, passed, a dict / object entry), where it often encodes a meaning of
  the program's own (`selected_index = -1`, `sys.exit(-1)`). Subscripts, slices,
  arithmetic, comparisons, UPPER_SNAKE targets and arguments of index callees
  (`range`, `.split`, `.slice`, `.at` ...) are never reported. `values` can add
  `0` or `1`.

### Changed (MAGIC001, feedback from MetaList)
- **`-1` is allowed by default** (`rules.magic_numbers.allow_unary_negative_one =
  true` in every profile; it was true only in `recommended`): Python's last-item
  and all-but-last idioms (`items[-1]`, `text[:-1]`) and JavaScript's
  `indexOf(...) === -1`. On MetaList's code, all 262 findings for it were such
  idioms. A strict project that reported `-1` gets fewer findings; `false` keeps
  the old behavior and is no longer a deviation, while turning it on in a project
  that had it off is a loosening `VERIFY003` reports.

Milestone H6, part two (decision 29): cross-site consistency. Both rules are
review findings (decision 9), so no gate verdict changes.

### Added (H6 part two)
- `PROV001` (`rules.consistency`): a parameter filled with a made-up identifier
  (`uuid4()`, `crypto.randomUUID()`) at one call site while other sites pass an
  identifier the program issued (`store.start_run()`, `createSession()`),
  followed through attributes, `str(...)` and helper functions.
- `GUARD001` (`rules.consistency`): a call made without the check of its
  argument that at least 75 percent of the function's call sites (and at least 3)
  make first (`if has(x): remove(x)`, `if (!has(x)) return;`, `assert has(x)`).
- Dataflow facts record each call's first argument and the guards in effect.
- The cache schema is "9".

### Changed (asserts, decision 28)
- **ASSERT001 version 2 reports only an assert that checks external input**: one
  whose test depends, followed like INPUT001 (across functions too), on request
  data, a configuration read, or `rules.assertions.external_reads` (`sys.argv`,
  `input`, `open`, `json.load`, `requests.get`, ...). Internal invariants are
  never reported; version 1 reported every production assert, which pushed
  agents to delete them. Fewer findings than 0.6.0 wherever asserts state
  invariants.
- New `ASSERT002` (review): production code relies on asserts and no analyzed
  code reads `sys.flags.optimize`; one finding per run asking for a startup
  check. New keys `rules.assertions.assert002_severity` and `external_reads`.
- The CLI refuses to run under `python -O` / `PYTHONOPTIMIZE` (exit 2):
  ShockHarness checks its own invariants with assert.
- The skills encourage asserting internal invariants (write-compliant-code
  principle 9) and say never to delete an assert to satisfy a finding.
- Dataflow: an imported name is now a read wherever the import is (a
  function-level `from flask import request` was a local).

### Changed (feedback)
- STUB001: a JavaScript error message is a TODO placeholder only when it opens
  with `TODO` in capitals or `todo` followed by `:` or `(`; `"Todo toggle
  missing"` (a name) no longer is. `rules.stubs.markers` match only a comment
  line that opens with the marker, not the word inside a sentence.
- IMPORT001 does not apply to scripts run directly: a file whose first line is a
  shebang, or one the new `rules.import_effects.script_files` (`scripts/**`,
  `bin/**`; adding a glob is a deviation) matches that no analyzed file imports.
  The exemption is listed in `files[].rules_disabled` (origin `script`).

### Fixed
- A Python file with a very long expression (about 1000 terms or more, such as a
  long string concatenation) crashed the analysis with an internal error (exit
  3): the H3 stub collector recursed once per tree level. It now walks with an
  explicit stack. On CPython 3.11, where `ast.parse` itself cannot build such a
  tree inside the tool, the file is a parse failure with the reason, governed by
  `parse_errors` like any unparseable file. 0.6.0 is affected.

Milestone H6, part one (specification section 21, decision 26): external input.
Both rules are advisory (decision 9), so no gate verdict changes.

### Added (H6)
- Dataflow facts: each function's value dependencies (`ModuleFacts.dataflow`),
  for Python, JavaScript and TypeScript.
- `INPUT001` (`rules.input`, warning): request data (Flask, Django/Starlette,
  Express/Koa, Lambda events) that reaches a shell, `eval`, deserialization, a
  file path, a query, a redirect or an outbound URL without a validator,
  followed through assignments, string building and calls, and across project
  functions through the call graph (`max_depth`, 3 crossings). The message names
  the source, its location and the functions crossed.
- `INPUT002` (`rules.input.input002_severity`, review): `os.getenv("X")`,
  `os.environ.get("X")` or `process.env.X` passed on, returned or stored without
  any check in the function.
- A sink entry that is not `"callee:N"` is a configuration error.

### Changed (H6)
- The cache schema is "8".

Milestone H-TS of specification section 21 (decision 25): TypeScript.

### Added (H-TS)
- TypeScript is a third language: `.ts`, `.mts`, `.cts` and `.tsx` are parsed
  with `tree-sitter-typescript` (a new runtime dependency, pinned
  `>=0.23.2,<0.24`, approved in decision 8) and analyzed by every JavaScript
  rule: magic numbers (literal types are reported as annotations), exceptions,
  defaults (typed and `constructor(private x = v)` parameters), complexity and
  the call graph, H2-H5 and ROLE001. `report.files[].language` and
  `coverage.languages` gain `"typescript"` (an additive enum value in
  `report-v1.schema.json`).
- `TYPE001` for TypeScript: `any`, type assertions (`x as T`, `<T>x`; not
  `as const`), non-null assertions (`x!`, new `rules.types.report_non_null`,
  switching it off is a deviation) and `@ts-ignore` / `@ts-expect-error` /
  `@ts-nocheck` (under `report_type_ignore`).
- Type-only imports and exports (`import type`, `{ type X }`, `export type ...
  from`) are erased: no import fact and no module edge, so a type-only cycle is
  not a cycle and ROLE001 ignores type-only imports of test files.
  `import x = require("m")` is a module import. A `./m.js` specifier resolves to
  `m.ts` / `m.tsx` (`.mjs` to `.mts`, `.cjs` to `.cts`) when no `m.js` is
  analyzed.

### Changed (H-TS)
- **The default `include` adds `**/*.ts`, `**/*.tsx`, `**/*.mts` and
  `**/*.cts`, and the default `exclude` adds `**/*.d.ts`.** A TypeScript
  repository on the defaults is now analyzed instead of listing its files as
  unsupported sources, so its gate verdict can change (MAGIC001, EXC001-EXC003
  and DEF001-DEF006 are errors). To keep the previous scope, set `include` to
  `["**/*.py", "**/*.js", "**/*.mjs", "**/*.cjs"]`. Python and JavaScript
  verdicts are unchanged.
- The default test role adds `**/*.test.ts`, `**/*.spec.ts`, `**/*.test.tsx`,
  `**/*.spec.tsx`, `**/*.test.mts`, `**/*.spec.mts`; the default config role
  (and the legacy `configuration_files`) adds `*.config.ts`, `*.config.mts`,
  `*.config.cts`.
- A JavaScript exception boundary also covers TypeScript files; a TypeScript
  boundary (`language = "typescript"`) covers TypeScript only.
- The cache schema is "7".

### Fixed (H-TS)
- JavaScript: a function's parenthesized parameters are now its locals (they
  were not, so mutating a parameter that shadows a module binding counted as a
  write to that binding).
### Added (ROLE001, spec 21.1 decision 24)
- `ROLE001` (`rules.role_integrity`, category `policy_integrity`): a
  production-role file that imports a test-role file through the module graph
  (warning, exact: shipped code shielded from the production rules), and a
  test-role file with no test case that matches none of `support_files`
  (`empty_test_severity`, review by default).
- `VERIFY003` also reports, in a revision diff, a file the base classified as
  production that the head classifies as test (a new `file_roles` glob, or a
  move under one).

Milestone H5 of specification section 21: API-catalog rules. Seven new rules
ship at `warning` or `review` (decision 9), so no gate verdict changes; the
golden corpus has no H5 findings, and the 0.3.0 regression runs with them off.

### Added (H5)
- `PROCESS001` (`rules.processes`): a shell command built from data (f-string,
  template, `+`, `%`, `.format`) run through a shell; `subprocess.run` without
  `check=True`, `subprocess.call`, `os.system`, `child_process.spawnSync` whose
  exit status is thrown away or never read.
- `RESULT001` (`rules.results`, production and test): a must-use call used as a
  statement (`sorted(xs)`, `name.strip()`, `items.map(f)`); method entries are
  approximate.
- `TYPE001` (`rules.types`, review, Python): `Any` in annotations, `cast(...)`,
  `# type: ignore`, each switchable.
- `SLEEP001` (`rules.sleep`, review): fixed sleeps, marked as polling in loops.
- `RETRY001` (`rules.retry`): endless retry loops whose handler never gives up;
  unbounded `tenacity` / `retrying` / `backoff` decorators.
- `BATCH001` (`rules.batches`): loops whose per-item handler only passes,
  continues or logs.
- `STUB003` (`rules.stubs.stub003_severity`, review): a check named
  `is_*`/`can_*`/`validate*`/... that always returns `True`.

### Changed (H5)
- The cache schema is "6".
- This repository's own configuration sets `rules.types.report_any = false`
  (its configuration and report values are dynamic TOML/JSON data); casts and
  `type: ignore` stay reported.

Milestone H4 of specification section 21: async lifecycle. Three new rules ship
at `warning` (decision 9), so no gate verdict changes; the golden corpus has no
async findings, and the 0.3.0 regression runs with them off.

### Added
- `ASYNC001` (Python, JavaScript): a coroutine or Promise created and dropped:
  a call that is a whole statement, or a JavaScript `void` call, whose callee is
  a configured coroutine/Promise API (`asyncio.sleep`, `fetch`, `fs/promises`
  ...) resolved through the file's imports, or a project function declared
  `async`, resolved across files by the call graph (a probable edge is
  `unknown`).
- `ASYNC002` (Python): `create_task(...)` / `ensure_future(...)` with the task's
  handle dropped, unless a configured supervisor (`asyncio.TaskGroup`,
  `anyio.create_task_group`, `trio.open_nursery`) bound the receiver.
- `ASYNC003` (Python, JavaScript): `gather(..., return_exceptions=True)` and
  `Promise.allSettled` whose results are thrown away or never checked for
  failure in the enclosing function.
- `[tool.shockharness.rules.async_lifecycle]`: `enabled`, `severity`, `roles`
  (production and test), `fail_on_unknown`, `python_coroutine_apis`,
  `javascript_promise_apis`, `supervisors`; every loosening is a policy
  deviation.
- A sixth bundled skill, `async-lifecycle`.

### Changed
- The cache schema is "5" (async facts are cached).
- With ASYNC001 active, units are measured and the call graph is built even
  when `complexity.enabled = false` (neither is reported then).

### Schema
- Report shapes are unchanged (`schema_version` "1"): the new rule IDs appear in
  `coverage.rules_implemented`, findings and SARIF rules, in category
  `contract_integrity`; `gate.unknown_gating_families` can name
  `async_lifecycle`.

## [0.6.0] - 2026-10-16

Milestone H3 of specification section 21: syntax-level guardrails. Seven new
rules ship at `warning` (`BOOL001` at `review`) until their precision is measured
(decision 9), so no gate verdict changes: with the new rules switched off, the
golden corpus keeps its 0.3.0 verdicts under every profile, and with them on no
gate status, exit code or hard-violation count changes (both pinned in
`tests/unit/test_profile_regression.py`).

### Added
- `EXC004` (`rules.exceptions`, every role): `return`, `break` or `continue` that
  leaves a `finally` block, discarding the exception in flight. Python and
  JavaScript, including labeled jumps.
- `STUB001` (`rules.stubs`): `raise NotImplementedError`, `raise NotImplemented`,
  a function whose body is only `pass`/`...`/a docstring, `throw new
  XError("not implemented")`; abstract API (`@abstractmethod`, `@overload`,
  `ABC`/`Protocol`/`ABCMeta` classes) exempt; optional comment `markers`.
- `STUB002` (`rules.stubs`): production imports of mocking or fake-data libraries
  (`mock_modules`) or of modules under test path segments (`test_path_segments`).
- `ASSERT001` (`rules.assertions`, Python): `assert` in production code;
  type-narrowing asserts allowed by default (`allow_type_narrowing`).
- `BOOL001` (`rules.boolean_arguments`, review): a Boolean literal passed
  positionally to a call with several arguments; `allowed_callees`.
- `STATE001` (`rules.module_state`): a module-level mutable binding written by a
  function, method or arrow; `[[allowed]]` entries with a reason.
- `IMPORT001` (`rules.import_effects`): configured side-effecting calls
  (processes, network, sockets, threads, deletion, `fetch`, `setInterval`)
  executed at import time, resolved through the file's own imports.
- `write-compliant-code` principle 8, "prefer immutable values": frozen
  records, tuples and frozensets, `Object.freeze`, new values preferred over
  mutated inputs (discouraged, not forbidden; local variables may be mutated
  freely); STATE001's remediation
  and `fix-violations` point at it.
- Each new section has `enabled`, `severity` (`warning`/`error`/`review`, the
  findings' severity) and `roles` (default `["production"]`); every loosening
  of them is a policy deviation, reported by VERIFY003 and protected by
  `--policy`.

### Changed
- The tool's own code: six `assert`s that checked real invariants raise
  explicitly; `schema.Field` is an `ABC` with abstract methods; the codec's type
  hint cache uses `functools.cache` instead of a module-level dict.
- The content-hash cache schema is "4" (guardrail facts are cached); earlier
  caches are invalidated.

### Schema
- Report shapes are unchanged (`schema_version` "1"); the new rule IDs appear in
  `coverage.rules_implemented`, findings and SARIF rules, and the new categories
  map `STUB*`, `ASSERT001`, `IMPORT001` to `contract_integrity` and `BOOL001`,
  `STATE001` to `structural`.
- Configuration: the five `rules.*` tables above.

## [0.5.0] - 2026-10-16

Feedback round F4 (`docs/shockharness-suggestions-4.md`, from agents running
ShockHarness on a real project; spec 21.1 decisions 12, 13 and 18). Verdicts are
unchanged except where listed under Changed; `tests/unit/test_profile_regression.py`
pins each intended difference against the 0.3.0 snapshot.

### Added
- `shockharness exceptions PATH...`: one read-only list of every inline
  suppression (rules, reason, used or unused), every malformed one, every policy
  deviation and `exclude` pattern with the file and line (or profile, policy
  file or command line) it comes from, the `--policy` attempts, and with
  `--baseline` the baseline's entries per rule and per file. Text or JSON
  (`schemas/exceptions-v1.schema.json`, `report_kind = "exceptions"`); exit 0,
  or 2 on an invalid configuration; never gates.
- `DEF002` kind `discarded_removal`: `m.pop(k, None)` as a statement is a
  `review` finding in every profile whose message asks whether `del` is right.
- Skills: a "propose a rule" step in `fix-violations` and `pre-commit-review`;
  output validation (principle 7) in `write-compliant-code`; a worked
  "absence is a normal state" example in Python and JavaScript.
- Docs: Python 3.10 projects (run the gate as its own job on 3.11+), empty
  trees, and the checks a layered checker should keep until H3-H-TS land.

### Changed
- `DEF002` no longer reports a `.get(...)` call that is itself a decorator
  (`@router.get("/x")`); a `None`-fallback lookup assigned to a name whose next
  statement is an `if` without `else` that only raises when the name is `None`,
  falsy, not callable or not an instance; or `m.setdefault(k, <empty
  container>)` whose result is immediately mutated (the grouping idiom). In the
  golden corpus this removes one review finding (`def_mapping_get.py:47`).
- `DEF002` remediation names three cases: the key must exist (index it), absence
  is a normal state (explicit `if k in m:` or a named helper), or the value comes
  from outside (validate where it enters).
- The `recommended` profile sets `rules.defaults.fail_on_unknown = false`:
  `DEF*` findings the analyzer could not establish are reported and do not gate.
  `strict` is unchanged. A `fail_on_unknown = false` is now a policy deviation
  whenever `strict` says `true`, whether a profile or the repository sets it.

### Schema
- New `schemas/exceptions-v1.schema.json` for `shockharness exceptions --format json`.
- Check, diff and baseline report shapes are unchanged (`schema_version` "1").
  The new `discarded_removal` kind is a fact kind; findings show it only through
  their message.

## [0.4.0] - 2026-10-16

Milestone H2 part 2 of specification section 21: `VERIFY003` reports a change
that loosens the policy that judges it (configuration, files dropped from
analysis, baselines, workflows, other tools' settings); `--policy FILE` adds an
organization floor the repository cannot loosen; a fifth agent skill,
`verification-integrity`. A plain `check` without `--policy` keeps its 0.3.0
verdict.

Milestone H2 part 1 of specification section 21: verification integrity.
`VERIFY001`, `VERIFY002` and `VERIFY004` compare a head revision with its base
in `diff` and `gate --base/--head` and report what the change added to weaken
its own checks. They ship at `warning` (spec 21.1 decision 9) and change no
existing verdict: a plain `check` reports them as not applicable.

Milestone H1 of specification section 21: the `unknown` finding status with
per-family `fail_on_unknown`, and file roles. Every existing test, the golden
corpus under all three profiles and the self-gate keep their 0.3.0 verdicts
and exit codes (pinned by `tests/unit/test_profile_regression.py`).

### Added
- `VERIFY003` (looser policy), in `diff` and `gate --base/--head`: a new
  policy deviation, an ordered setting moved to its looser end (gate modes,
  `unsupported_sources`, `parse_errors`, VERIFY severity, fan-out severity), a
  raised complexity threshold, a narrower `include` or wider `exclude`; files
  the base analyzed that the head configuration no longer does; fingerprints
  added to a ShockHarness baseline; in a GitHub Actions job that runs
  ShockHarness, the job removed, `continue-on-error: true`, `if: false`,
  `--exit-zero`, `--profile minimal|recommended`, `--parse-errors warn` or an
  older version pin; codes added to ruff/flake8 ignore, per-file-ignores and
  exclude lists or removed from ruff `select`, deselecting pytest `addopts`,
  removed `testpaths`, coverage `omit`/`exclude_lines`, a lowered or removed
  `fail_under`, an ESLint rule turned down or removed (JSON `.eslintrc`). An
  unreadable or unparseable file makes its comparison `unknown`.
- `--policy FILE` on every command that loads configuration: a
  `[tool.shockharness]` file that must live outside the analysis root, layered
  between the profile and the repository's configuration. A repository key
  that would loosen a key the policy sets is dropped (the policy's value
  applies), noted, and reported as `VERIFY003`, in a plain `check` too.
- In a revision diff the VERIFY rules use the stricter of the run's and the
  base revision's `rules.verification` (strictest of base): a change cannot
  disable, lower or exempt the rules that report it.
- The reusable workflow `check.yml` takes `policy-repository`, `policy-ref`,
  `policy-path` and a `policy-token` secret, clones the policy into
  `$RUNNER_TEMP` and passes `--policy`.
- A fifth bundled skill, `verification-integrity`: fix the cause instead of
  skipping, suppressing or loosening, and what each VERIFY finding means.
- `VERIFY001` (added test skip, expected-failure or focus marker: pytest and
  unittest markers, `pytestmark`, `pytest.skip` / `self.skipTest` in a test
  body; `describe` / `it` / `test` with `.skip` / `.only`, `x*` and `f*`
  spellings), `VERIFY002` (added blanket suppression comment: `noqa`,
  `type: ignore`, `pylint: disable`, `pragma: no cover`, `mypy:
  ignore-errors`, `eslint-disable*`, `@ts-ignore` / `@ts-expect-error` /
  `@ts-nocheck`, `istanbul` / `c8` / `v8 ignore`, `shockharness: ignore`;
  narrow ones on request), `VERIFY004` (added tautological assertion, a test
  whose assertions all disappeared, a test whose body became empty). Only
  additions are reported; what existed at base is debt. Renames detected by
  git are followed. A file whose base version could not be analyzed, or whose
  rename status could not be established, yields `unknown` findings. Test-role
  files for VERIFY001/004; every role except generated and vendor for VERIFY002.
- `[tool.shockharness.rules.verification]`: `enabled`, `severity`
  (`"warning"` default in every profile, `"error"`, `"review"`),
  `fail_on_unknown` (default `false`), `allowed_skip_reasons`,
  `report_narrow_suppressions`. `severity = "review"` and each allowed skip
  reason are policy deviations; `severity = "error"` tightens and is not.
- Finding categories: `policy_integrity` (VERIFY), `contract_integrity`
  (MAGIC, EXC, DEF, SUPP), `structural` (CPLX). The text output of `diff` and
  `gate` lists policy-integrity findings first under their own heading and
  prints a `verification:` line; `check` lists the rules that need a base
  revision on their own line instead of under "rules applied".
- Every finding has a `status`: `violation` (the rule established the property
  and it does not hold) or `unknown` (the rule could not establish it).
  Severity is unchanged and orthogonal. Unknown today: `EXC001` on a catch
  whose only obstacles are exception types that do not resolve, on a promise
  rejection handler that references a function the module does not define, on
  a `with` whose capture-manager binding cannot be established and on a capture
  manager with no readable exception type; `DEF002` on `m.get(k, v)`,
  `m.setdefault(k, v)`, `m.pop(k, v)` and `m.get(k)` whose receiver is not
  proven a mapping. A bare `except`, an untyped JavaScript `catch` and an
  inline untyped rejection handler stay `violation`, as does a catch naming
  one resolved type that no boundary approves. The inventory is in
  `docs/rules.md` (Finding status) and kept as a test
  (`tests/unit/test_unknown_inventory.py`) that fails when a new place
  produces an unresolved state or a finding without a recorded decision.
- `fail_on_unknown` (boolean) per rule family, in the family's own table:
  `rules.exceptions` and `rules.defaults` default to `true` (both families
  have always failed closed on these findings), `rules.magic_numbers` and
  `complexity` to `false` (they produce no unknown findings). `true`: unknown
  findings gate by severity exactly as before. `false`: they are reported,
  counted in `gate.unknown`, add to no other count, never fail the gate, and a
  gate reason says how many were reported only. Setting a family to `false`
  where its profile says `true` is a policy deviation.
- File roles: every file gets exactly one of `generated`, `vendor`,
  `config`, `test`, `docs` (the first whose `[tool.shockharness.file_roles]`
  globs match, in that order) or `production`. Documented defaults: test =
  `tests/**`, `test/**`, `**/__tests__/**`, `**/test_*.py`, `**/*_test.py`,
  `**/*.test.js`, `**/*.spec.js`, `**/*.test.mjs`, `**/*.spec.mjs`,
  `**/conftest.py`; config = the 0.3.0 `configuration_files` list; generated =
  `**/generated/**`, `**/*_pb2.py`, `**/*.min.js`; vendor = `**/vendor/**`,
  `**/third_party/**`; docs = `docs/**`. Roles never change which files are
  discovered or analyzed.
- `[[tool.shockharness.overrides]]` accepts `roles = ["test"]` instead of
  `paths` (exactly one of the two per entry, validated), reported as a policy
  deviation (`... for file role(s) test: <reason>`) and with origin
  `overrides[i]` like a path override.
- The text report marks unknown findings (`EXC001 error (unknown): ...`) and
  prints an `unknown:` trailer line with the count and the families that gate
  on it.

### Changed
- The `verification:` line of `diff` and `gate` text output reads
  `RULES against base X: N source file(s) compared (...); M policy file(s) and
  K baseline(s) checked; severity S`, and `policy:` lines name the
  `--policy` file and each attempt before the policy deviations.
- `coverage.rules_not_implemented` is `["MAGIC002"]`.
- A `shockharness: ignore[...]` comment naming a VERIFY rule is a `SUPP001`
  error and suppresses nothing: a change cannot excuse its own weakening of
  the checks inline (spec 21.1 decision 5).
- The content-hash cache schema is "3" (verification facts are cached with the
  other per-file facts); caches written by earlier builds are invalidated.
- The MAGIC001 configuration-file exemption is expressed on the config role:
  `exclude_configuration_files = true` exempts files whose role is `config`
  (and a `generated`/`vendor` file a config glob also matches, which was exempt
  in 0.3.0). The `rules_disabled` reason now names the config role pattern;
  the origin is still `configuration_file`. `rules.magic_numbers.configuration_files`
  is the legacy spelling of `file_roles.config` (kept through 0.x): set alone
  it replaces the config role's globs as it replaced the exempt list before;
  set together with `file_roles.config` the lists are merged. A config note
  says which.
- The cache schema is `"2"` (entries carry finding status and file role); a
  0.3.0 cache directory is invalidated and rebuilt on the first run.
- This repository's own `tests/**` override is now `roles = ["test"]`, and its
  `file_roles.config` is empty (its one `conftest.py` is test code).

### Schema
All additive under report `schema_version` "1" (the new properties are
optional in `schemas/report-v1.schema.json`, so 0.3.0 reports still validate):
- H2 part 2: `config.policy` (`path`, `digest`, `keys`; `null` without
  `--policy`) and `config.policy_attempts` (`key`, `policy_value`,
  `attempted_value`, `reasons`) in reports and diff reports;
  `coverage.verification.policy` (`configuration`, `workflows_checked`,
  `workflows_note`, `files_compared`, `baselines`, `read_errors`) and
  `coverage.verification.policy_attempts` in diff reports; `VERIFY003` in
  `coverage.rules_implemented` and `rules_needing_base_revision`. The
  configuration origin `policy` in `config effective`.
- H2: `findings[].category` (`policy_integrity` | `contract_integrity` |
  `structural`), in reports, diff reports and SARIF `properties.category`;
  `coverage.rules_needing_base_revision`; `coverage.verification`
  (`status` `not_applicable` | `analyzed` | `disabled`, and in a diff the base
  commit, files compared, new, renamed and unanalyzable-base counts, rename
  detection state, severity and settings); `summary.by_category`; diff
  `summary.new_policy_integrity`; SARIF rule `properties.category` and
  `properties.needs_base_revision`.
- `findings[].status` (`violation` | `unknown`).
- `files[].role` and `files[].role_pattern` (the deciding glob, `null` for
  production).
- `coverage.roles`: files per role, every role listed.
- `summary.by_status` (both statuses listed) and `summary.by_role` (findings
  per role of their file, every role listed).
- `gate.unknown` and `gate.unknown_gating_families`.
- SARIF results: `properties.status`; `level` still comes from the severity.
- Diff reports (`schemas/diff-v1.schema.json`): `findings[].finding_status`
  (a diff finding's `status` keeps meaning new/fixed/unchanged), and
  `gate.unknown` / `gate.unknown_gating_families`.
- Configuration: `rules.verification` table (H2); `file_roles` table; `fail_on_unknown` in
  `rules.magic_numbers`, `rules.exceptions`, `rules.defaults` and
  `complexity`; `overrides[].roles`; `overrides[].paths` is no longer required
  (one of `paths`/`roles` is).

## [0.3.0] - 2026-10-15

The third feedback round, from `docs/shockharness-suggestions-3.md`
(the same 906-file codebase run with 0.2.0). All five items are below; the
content-hash cache (item 3, deferred from the first brief's item 6) is the
largest.

### Added
- The content-hash cache of per-file results. Parse facts, rule findings and
  per-unit complexity metrics are stored under `cache.directory` (default
  `.shockharness-cache/` under the analysis root; `cache.enabled` default
  true; `--no-cache` on `check`/`scan`/`gate PATH...` bypasses reading and
  writing for one run). The key is the tool version, the effective
  configuration digest, the host (interpreter and JavaScript grammar), the
  language and the SHA-256 of the file's bytes; any difference is a miss, a
  header difference invalidates everything. Cross-file work (call graph,
  cycles, suppressions, fingerprints, baseline matching, diffs, history) is
  always recomputed; `baseline create` and revision diffs never read the
  cache. Entries are JSON (never pickles), written atomically; a corrupt,
  unreadable or schema-mismatched index or entry is counted and described
  once under `coverage.cache` and ignored. `coverage.cache` (`status`,
  `directory`, `reason`, `hits`, `misses`, `invalidated`, `errors`,
  `problems`) is the one report block that differs between a cold and a warm
  run; the text output prints a `cache:` line. On this repository a warm run
  takes a fifth of a cold one. Library API: `AnalysisOptions` gains a
  required `cache` field (`CACHE_CONFIGURED` | `CACHE_BYPASSED`),
  `analyze_files` a `cache` argument and `build_report` the coverage block.
  The `cache` table is excluded from the configuration digest, so toggling or
  moving the cache keeps baselines valid. The directory is skipped by
  discovery like `.git`, listed in the repository's and both examples'
  `.gitignore`, and documented in `docs/configuration.md`, Cache.
- `EXC001`/`EXC002` resolve a capture manager bound to a name: `capture =
  CapturedExceptionContext(T); with capture:` (81 of the 82 captures in that
  codebase) and `s = suppress(T); with s:` are the same catch as the inline
  form, resolved to the most recent binding of the name in the same function
  or module body. The confidence is `exact` when nothing stands between the
  assignment and the `with`, `approximate` when the assignment sits in a
  branch or loop the `with` is not inside (or the name is also a parameter or
  a comprehension target), and `unresolved` (an untyped catch, never the older
  binding) when the name was rebound in between, is bound by `with ... as`, or
  is bound to a listed manager only in another scope. A name never bound to a
  listed manager is an ordinary `with`. IR: `ManagerFact` now carries a
  `ManagerCall` (inline form) or a `NameResolution` (bound form).
- `rules.magic_numbers.named_constant_definitions = "allow"` accepts literal
  arithmetic as the value of a module-level constant: `CHUNK_BYTES = 64 *
  1024`, `const MAX_MS = 30 * 60 * 1000;` (numeric literals, unary `+`/`-`,
  parentheses, `+ - * / // % **`; JavaScript the same set). Any name, call,
  attribute, subscript or non-numeric literal in the expression keeps every
  literal reported; `"report"` is unchanged. Specification section 5 and
  section 19 (decision 16) record it.
- `EXC002`'s message for a handler that consists only of a transparent guard
  call (`catch (error) { rethrowUnexpectedError(error); }`) ends with the
  three remedies: handle the expected error after the guard, log it and
  continue with a stated reason, or suppress the finding with a reason. No
  behaviour change.

### Schema
- Report schema 1 gains `coverage.cache` (required), the `cache` table joins
  the configuration schema, and `config_digest` no longer covers the `cache`
  table. No existing field changed.

### Changed
- Glob patterns: a leading `/` or `./` anchors the pattern to the analysis
  root. `/main.py` and `./main.py` match only the root-level `main.py`;
  `/src/*.py` matches `src/a.py` but not `src/sub/a.py` or `other/src/a.py`.
  Patterns without either prefix keep their semantics (no slash: basename
  anywhere; with a slash: whole relative path). This changes `./pattern` from
  "the same as `pattern`" to "root-anchored", and `config validate` now
  accepts a leading `/` (it was an error). `include`, `exclude`,
  `overrides[].paths`, `rules.magic_numbers.configuration_files` and boundary
  paths all honour the anchor.

## [0.2.0] - 2026-10-14

The feedback round after the first run of 0.1.0 on a 906-file codebase
(`docs/shockharness-suggestions.md`): precision, noise and adoption cost.
Items 1-5 and 7-9 of that document are implemented here; item 6 (a
content-hash cache) is deferred to a later release.

### Added
- `rules.magic_numbers.named_constant_definitions` (`"report"` | `"allow"`):
  a numeric literal that is the whole value of a module-level named constant
  definition (`MAX_PAGES = 8`, `_WAIT: Final = 10.0`, `const SETTLE_MS = 400;`,
  `export const N = -3;`) is marked by both adapters
  (`NumericLiteral.constant_definition`). `strict` keeps `"report"`, so the
  specification's reading (a named constant is not automatically justified)
  is unchanged there; `recommended` and `minimal` use `"allow"`. `"allow"` is
  a reported policy deviation. Containers, expressions, chained targets, class
  and function bodies and definitions nested in module-level blocks are
  reported either way. Specification sections 5 and 19 record the decision.
- `CPLX006` unit size: a warning when a unit's `size/1` logical line count is
  above `complexity.max_lines_warn` (default 50 in every profile); module
  bodies are exempt. Registered with full metadata, part of
  `rules_applied`/`rules_disabled`, revision diffs and the summary.
- `complexity.npath_only_without_cognitive` (default `true`): a unit above
  both `cognitive_warn` and `npath_warn` is one `CPLX002` finding whose
  message carries the NPath number; `false` restores the separate `CPLX004`.
  A unit above the NPath threshold alone is still `CPLX004`.
- `rules.exceptions.transparent_guards`: guard callees
  (`["rethrowUnexpectedError"]`) that re-raise anything unexpected. A handler
  whose first statement calls a listed guard with the caught exception as its
  only argument is narrowed by it: `EXC001` does not report the catch and
  `EXC002` classifies the statements after the guard (nothing after it still
  swallows; a literal return after it is `EXC002`'s, not `DEF005`'s). Each
  guard is a reported deviation. `CatchFact` gains `guard_call`, `guard_body`
  and `narrowed_from`.
- Python `isinstance` guards: `except Exception as exc:` whose first statement
  is `if not isinstance(exc, T): raise` (or a tuple) is checked by `EXC001` as
  a catch of `T`; the message says what it was narrowed from.
- Boundaries may list several classes for one path with one reason:
  `exceptions = ["OSError", "ProcessLookupError"]` alongside the single
  `exception = "..."` form; exactly one of the two per entry is validated, and
  the entry is one deviation line naming every class. `EXC003` is unchanged.
- `check --summary` (also on `scan` and `gate PATH...`): a first-contact
  overview (findings by rule and top-level directory and by severity, the ten
  files with the most policy findings, complexity counts, parse failures,
  elapsed time) followed by the unchanged totals and `gate:` line.
- `complexity.fan_out_severity` (`"warning"` | `"review"`): the severity of
  `CPLX005` fan-out findings; both are advisory, so neither is a deviation.

Second batch, from `docs/shockharness-suggestions-2.md` (coverage gaps found
against the project's own linter); items 1-4 are implemented, item 5 (a
plugin API) is a design note for later:

- `EXC001`/`EXC002` see exception capture through context managers:
  `with contextlib.suppress(T, ...):` (either import spelling) is a catch of
  `T` that swallows, and `rules.exceptions.capture_managers` lists a
  project's own managers by qualified name (`with M(T, ...):` is a catch of
  the exception types passed positionally; exact when the import resolves,
  approximate by bare name when it does not; no readable type is an untyped
  catch). Findings sit on the `with` line with the kind `context manager`,
  boundaries approve them like `except` handlers, an approved `suppress` is
  not an `EXC002` swallow, and every configured manager is a reported
  deviation. New IR fact `ManagerFact` (`ModuleFacts.managers`) and catch kind
  `context manager`.
- `DEF002` covers `next(iterator, default)` and
  `collections.defaultdict(factory)` through any import spelling (new kinds
  `next_default` and `defaultdict`); `d.pop(key, default)` and
  `d.setdefault(key, default)` were already covered and now have dedicated
  tests. `DEF001` covers pydantic model fields (a class whose base resolves to
  `pydantic.BaseModel`): `x: int = v`, `Field(default=v)`, `Field(v)`,
  `Field(default_factory=f)` under `dataclass_fields`, with `pydantic field`
  messages; `Field(...)`, `Field()` and `= ...` are required fields.
- Promise rejection handlers: a handler given as a reference to a function
  defined at the top level of the same module is classified by that
  function's body; other references stay unresolved; an expression-bodied
  arrow that only logs is `logging_only`; a bare `log(...)` call counts as
  logging in JavaScript. Swallowing, rethrowing (with `transparent_rethrow`),
  `.finally(fn)` and `async` `try`/`catch` already behaved as the brief asks
  and are pinned by tests.
- `unsupported_sources` (top level; `"fail"` | `"warn"` | `"ignore"`; `warn`
  in `strict` and `recommended`, `ignore` in `minimal`): what an included file
  no adapter can parse means. `fail` makes each one an analysis failure (file
  status `unsupported_source`, language `unsupported`, exit 3); `warn` lists
  them under `coverage.unsupported_sources` with a `warning:` line; `ignore`
  only counts them (a reported deviation). `coverage.discovery` gains
  `unsupported_sources`; `coverage` gains `unsupported_sources_policy` and
  `unsupported_sources` (additive, `schema_version` stays `"1"`).

### Changed
- `CPLX005` reports one finding per import cycle instead of one per member,
  anchored on the lexically first member at its import into the cycle (stable
  fingerprint when unrelated modules are added), naming the language and the
  size, listing up to eight members and noting that Python cycles fail at
  import time while ES-module cycles are usually resolved at call time.
  `metrics.graph.cycles` is unchanged. The text report lists import cycles as
  a group after the per-file findings, Python cycles first.
- `recommended` profile: `magic_numbers.allow_unary_negative_one = true`,
  `magic_numbers.named_constant_definitions = "allow"`,
  `complexity.fan_out_warn = 30`, `complexity.fan_out_severity = "review"`
  (plus the existing `DEF004` at review). `strict` is unchanged. `minimal`
  adds `named_constant_definitions = "allow"`.
- `DEF001`: new tests pin that annotated class attributes of undecorated and
  ORM-style classes are not dataclass fields and that `dataclasses.dataclass`
  (with or without arguments) is recognized; no behaviour change.
- The text report's complexity line reads `CPLX001-CPLX004 and CPLX006 are
  warnings`; documentation and skills name `CPLX001`-`CPLX006`.

### Schema
- `schema_version` stays `"1"`: every change is additive. The report gains a
  top-level `summary` object (`schemas/report-v1.schema.json` describes it:
  `files`, `files_analyzed`, `parse_failures`, `findings`, `suppressed`,
  `by_severity`, `by_rule`, `by_directory`, `by_rule_and_directory`,
  `policy_families`, `top_files_limit`, `top_files`, `complexity`); its
  totals equal `execution_summary`. Elapsed time is printed by the text
  summary only, never in JSON, so reports stay byte-identical across runs
  (the pre-release 0.2.0 build briefly put it in JSON, which made the
  determinism tests flaky on CI). `metrics.complexity.thresholds` gains
  `max_lines_warn`. `CPLX006` appears in `coverage.rules_implemented` and in
  every file's `rules_applied`/`rules_disabled`. Boundary entries in
  `config.values` may carry `exceptions` instead of `exception`. Second batch:
  `files[].status` may be `unsupported_source` and `files[].language`
  `unsupported` (only under `unsupported_sources = "fail"`); `coverage` gains
  `unsupported_sources_policy` and `unsupported_sources`;
  `coverage.discovery` gains `unsupported_sources`.

## [0.1.0] - 2026-10-14

First stable release. Every milestone of the specification (A through G) is
implemented: the three default-on hard policies (`MAGIC001`, `EXC001`-`EXC003`,
`DEF001`-`DEF006`), inline suppressions, baselines, revision diff and gate,
SARIF, git history metrics, advisory complexity metrics and call graph
(`CPLX001`-`CPLX005`), three profiles, the `check` command, `--exit-zero`,
tag-triggered publishing, a reusable GitHub Actions workflow, consumer
examples, four agent skills with `skills install`/`update`, and the eval
corpus. From this release the CLI surface, exit codes, rule IDs and report
`schema_version` 1 are stable; changes to them are documented here first.

### Fixed
- Skills: `SKILL.md` content is normalized to LF when read from the package, so
  frontmatter checks, installs and manifest hashes are identical on checkouts
  that use CRLF (Windows runners with `core.autocrlf`). A `.gitattributes` now
  pins LF on checkout for every text file in the repository.
- History metrics: commit dates are now normalized to one ISO 8601 spelling
  (`+00:00`) regardless of the host's git version. Git 2.45+ prints UTC as `Z`,
  which made `metrics.history` differ between machines and broke two tests on
  CI runners with newer git than the development machine.
- Dependabot no longer proposes minor or major `tree-sitter` bumps; the 0.25
  pin is deliberate (0.26.0 segfaults on CPython 3.14).

### Added
- Milestone E: complexity metrics, call graph, hotspots. `CPLX001`-`CPLX005`
  are implemented as advisory warnings that never fail a plain `check`. Every
  module body, class body, function, method, lambda and arrow is a *unit*
  measured on its own (nested units are excluded from their parent) with
  versioned conventions stated in every message and in
  `metrics.complexity.conventions`: `cyclomatic/1` (boolean operators counted
  under `complexity.cyclomatic_counts_boolean_operators`, optional chaining
  never), `cognitive/1` (published-style nesting and interruption increments,
  explicitly not a SonarSource score, Python/JavaScript parity enforced by a
  table and a Hypothesis property), `nesting/1`, `npath/1` (bounded by
  `complexity.npath_cap`, reported as `>= cap` when saturated, never
  enumerated) and `size/1`. New keys `npath_cap`, `npath_warn`, `fan_out_warn`,
  `cyclomatic_counts_boolean_operators`, `abstraction_displacement`;
  `cyclomatic_counts_boolean_operators = false` is a reported deviation.
  `docs/complexity.md` defines everything.
- `metrics.graph`: a call graph whose edges are `resolved` (direct call of a
  module-level, nested or imported definition), `probable` (module alias
  attribute, `self`/`this` method the class defines, static class call,
  function passed as an argument) or `unresolved` (computed callee, unknown
  receiver, unbound name, undefined `self` attribute); counts per confidence,
  fan-in/fan-out per unit (builtins excluded, unresolved never counted),
  module import edges for Python (absolute and relative, canonical
  package-rooted names, never suffix matching) and JavaScript (`import`,
  `export ... from`, `export *`, `require`), strongly connected components
  as `cycles`, and `shared_mutable_state` notes. `CPLX005` fires per cycle
  member and on fan-out above `fan_out_warn`.
- `metrics.history.hotspots`: `log1p(churn) * normalized_complexity` per file
  (summed cognitive complexity over the repository maximum), with
  `hotspots_formula`; `null` with a reason when history or complexity is
  unavailable.
- Revision diffs list `metrics.complexity.regressions` (head units above a
  threshold whose value grew since base) and honour
  `gates.complexity_regressions` (`warn` default, `fail`, `ignore`);
  `gate.complexity_regressions` and `summary.complexity_regressions` are new
  fields. `complexity.abstraction_displacement = true` adds the experimental
  `metrics.graph.abstraction_displacement` (every entry approximate).
- The analysis pipeline now has a cross-file phase between the per-file rules
  and suppressions, so graph findings are suppressible and fingerprinted;
  `build_report` takes the metrics, `collect_history` takes the complexity
  section, `gate.evaluate` takes the regression count. Report and diff schemas
  gain the new sections (additive); SARIF carries CPLX results.
- The `refactor-complexity` skill now quotes the real rules, thresholds,
  report fields and commands.
- Milestone G: four vendor-neutral agent skills shipped as package data
  (`shockharness/skills/<name>/SKILL.md`, open Agent Skills format with
  `name`/`description` frontmatter): `write-compliant-code`,
  `fix-violations`, `refactor-complexity`, `pre-commit-review`. Each has
  compliant and non-compliant Python and JavaScript examples, exact CLI
  invocations, a corrective workflow, a checklist, and an "Adopting
  ShockHarness" section identical to the README's (enforced by a test).
  `refactor-complexity` states that `CPLX001`-`CPLX005` are not implemented.
- `shockharness skills list|show|install|update`. `install --agent
  claude|codex|generic [--project PATH] [--user] [--force]` writes the skills
  (claude: `.claude/skills`, codex: `.agents/skills`, generic: `--project DIR`
  itself plus a printed `AGENTS.md` pointer line) and a manifest
  `.shockharness-skills.json` (schema version 1: agent, package version,
  SHA-256 per file); it refuses to overwrite without `--force` (exit 2) and
  touches nothing outside the destination. `update` rewrites files whose hash
  still equals the manifest, restores missing ones, adds new skills, reports
  removed ones, leaves edited files alone and reports each as a conflict with
  the remediation (exit 1 while a conflict remains); `update --check` writes
  nothing and exits 1 on any drift. Three new declared exception boundaries in
  `skills/install.py` (`OSError`, `UnicodeDecodeError`,
  `json.JSONDecodeError`).
- Skill evaluation corpus under `evals/`: eight paired tasks (four Python,
  four JavaScript) with prompt, starting files, behavioral tests, expected
  outcome and a clean reference solution; `evals/run_evals.py` (standard
  library only, one declared `MAGIC001` override) scores candidate directories
  by unsuppressed findings per rule, test exit code and suppressions added,
  and writes a JSON scorecard. CI scores the reference solutions and
  round-trips `skills install` / `update --check` for all three agents on
  ubuntu. The sdist carries `evals/`.
- README "Adopting ShockHarness": a self-contained guide for an agent reading
  the README over HTTP (pinned `uv tool install` / `uvx` / `pip` forms,
  `init`, the four onboarding paths, direct and reusable CI steps with the
  Dependabot snippet, `skills install`, and a verification table), with
  absolute links only. `docs/skills.md` is new; `docs/integration.md` gains a
  skills section.
- `--exit-zero` on `check` (and the `scan` alias) and `gate`: an advisory
  run. The report, severities, gate verdict text and every count are
  unchanged; only the process exit code is 0 where the verdict would have
  returned 1. Exit 2 (configuration, usage) and exit 3 (tool failure, strict
  parse failure) are never masked. The run is visible as `gate.advisory`
  (JSON and diff reports, both schemas, additive), a `shockharness: advisory
  run (--exit-zero): gate verdict FAIL reported as exit 0` line in text, and
  the `advisory` SARIF run property; the SARIF invocation `exitCode` is the
  process exit code while `properties.gate.exit_code` keeps the verdict's.
  Deliberately a CLI-only flag, not a configuration key: the configuration
  form is `gates.new_hard_violations = "warn"`. `docs/configuration.md` gains
  "Adopting ShockHarness on an existing codebase" comparing the four onboarding
  paths (baseline, `gates.new_hard_violations = "warn"`, `profile =
  "minimal"`, `--exit-zero`).
- Milestone F (distribution half). `shockharness check` is the canonical
  analysis command (identical arguments and behaviour to `scan`, which stays as
  a hidden alias); `shockharness version` prints the same string as
  `--version`.
- Built-in profiles shipped as package data (`shockharness/profiles/*.toml`),
  selected with `profile = "strict" | "recommended" | "minimal"`: `strict` is
  the bundled defaults; `recommended` reports `DEF003`/`DEF004` at review;
  `minimal` caps `MAGIC001`, `EXC001`-`EXC003` and `DEF001`-`DEF006` at
  review, sets `parse_errors = "warn"` and disables complexity. Precedence:
  bundled defaults < profile < repository configuration < command-line
  overrides. Every profile below `strict` is a policy deviation in every
  report and in `config validate`; `config effective` records profile keys
  with origin `profile:<name>`.
- `rules.magic_numbers.severity`, `rules.exceptions.severity`,
  `rules.defaults.severity` (`"error"` | `"review"`): a per-section cap that
  turns error findings into review findings; each cap is a reported deviation.
- The only two command-line overrides, on every configuration-loading command:
  `--profile NAME` (replaces the profile layer; the repository's other keys
  still apply) and `--parse-errors fail|warn`. Both are recorded with origin
  `cli_override`, noted in the report, and part of the configuration digest.
- `shockharness.toml` is accepted alongside `.shockharness.toml` at the
  dedicated tier; both present in one root is a configuration error naming
  both files.
- `init --profile recommended|minimal` writes a short file selecting the profile.
- Release automation: `.github/workflows/publish.yml` (tag `v*` -> full CI
  workflow -> build wheel and sdist -> tag equals `version.py` -> PyPI trusted
  publishing with `id-token: write`, environment `pypi`, no stored token);
  `docs/releasing.md` with the one-time PyPI steps and the per-release steps.
- Reusable consumer workflow `.github/workflows/check.yml` (`workflow_call`;
  inputs `shockharness-version` (required), `config`, `base`,
  `python-version`; SARIF upload to code scanning; permissions
  `contents: read`, `security-events: write` only); `.github/dependabot.yml`
  for this repository; `docs/integration.md` (pinning to a tag and to a SHA,
  Dependabot snippet, where the pin may live).
- Consumer examples `examples/python` (dev dependency pinned to `0.1.0a1`)
  and `examples/js` (analyzer in an isolated tool environment, never an npm
  dependency), each with a policy file, a workflow and one deliberate
  suppressed finding; `scripts/consumer_upgrade_check.py` (stdlib only)
  copies each into a throwaway git repository, installs the wheel built from
  the checkout, and asserts `check` exits 0, then 1 after one injected
  violation, and `gate --base HEAD~1 --head HEAD` exits 1; run by CI on ubuntu.
- `effective_profile` is also in SARIF run properties, next to
  `config_deviations`.
- Milestone F (analysis half): stable finding fingerprints (`findings[].fingerprint`;
  rule ID, path, enclosing scope, whitespace-free evidence, occurrence index)
  that survive line moves and reformatting; `shockharness baseline create PATH...
  --output FILE` writing a reviewed, byte-stable baseline
  (`schemas/baseline-v1.schema.json`) that is never updated automatically;
  `--baseline FILE` on `scan` and `gate` with `gates.legacy` semantics
  (`baseline`: matched findings listed and counted but not gating; `ignore`:
  listed, not counted; `fail`: baseline recorded but not applied); stale
  baseline entries reported under `gate.baseline.stale`; `evaluate_gate` and
  `apply_baseline` in the library API.
- `shockharness diff --base REF --head REF` (reporting only) and
  `shockharness gate --base REF --head REF` (exit 1 only on new hard
  violations): both revisions resolved and exported with local git only, full
  trees analyzed, findings classified new / fixed / unchanged by fingerprint,
  provenance (both commits, config digest, tool version) in the report
  (`schemas/diff-v1.schema.json`).
- SARIF 2.1.0 output (`--format sarif`) for `scan`, `diff`, and `gate`: one
  run, every registered rule with full descriptions, results with level mapping
  (error, warning, review/note -> note), root-relative URIs, exclusive end
  columns, `partialFingerprints` carrying the baseline fingerprint, in-source
  suppressions, and `baselineState` when a baseline or base revision applies.
- `metrics.history` in every CLI report: per-file commit count, author count,
  first and last change, and co-change pairs with support and directional
  confidence, read from local `git log` over `history.horizon_days` anchored
  on the head commit date; `history.enabled`, `history.horizon_days`,
  `history.min_support` configuration keys; explicit `unavailable`,
  `disabled`, and `not_collected` statuses with reasons; `hotspots` is `null`
  with a reason until Milestone E provides complexity.
- Six declared exception boundaries: reading a baseline file (`OSError`,
  `UnicodeDecodeError`, `json.JSONDecodeError`) and the git subprocess
  (`subprocess.CalledProcessError`, `OSError`, `UnicodeDecodeError`).

### Changed
- **`policy_profile` is renamed to `effective_profile`** in the JSON report,
  the diff report, both JSON schemas and SARIF run properties (specification
  section 20, decision 13). `schema_version` stays `"1"`: no tagged release
  has shipped the old field (0.1.0a1 was published only to claim the name and
  predates the schema's first tagged release), so the rename is made before
  schema v1 is published rather than versioned around.
- The text report's `config:` line names the effective profile; `config
  validate` prints it.
- CI, the pre-commit hook, the README and the docs invoke `shockharness
  check`; the self-gate and Ruff also cover `scripts/`.
- Report schema (still `schema_version` 1, additive): `findings[].fingerprint`,
  `findings[].baseline`, `gate.baselined`, `gate.new_hard_violations`,
  `gate.baseline`, `execution_summary.baselined`, `metrics.history`. The gate
  verdict is driven by `new_hard_violations`; without a baseline it equals
  `hard_violations` as before.
- `--format sarif` no longer exits 2; `evaluate_gate` no longer raises
  `UnsupportedFeatureError` for a baseline (it rejects anything that is not a
  `Baseline` with a `UsageError`).

## [0.1.0a1] - 2026-10-14

First public alpha, published to PyPI to claim the `shockharness` name.
Contains Milestones A through D: MAGIC001, EXC001-EXC003, DEF001-DEF006,
SUPP001/SUPP002, configuration validation, text and JSON reports, and the
`scan`, `config`, `rules`, and `init` commands. No baselines, diff, SARIF,
complexity metrics, or skills yet; see `coverage.rules_not_implemented` in
every report.

Everything listed under "Added" below shipped in this version.

### Added
- Milestone A: package skeleton, MIT license, configuration schema with full
  shape and semantic validation, precedence (`--config` > `.shockharness.toml` >
  `pyproject.toml` > bundled defaults), rule registry with every specified rule
  ID, diagnostic and report models, `scan`, `config validate`, `config effective`,
  `rules list`, `rules explain`, `init`, exit-code contract, GitHub Actions matrix.
- Milestone B: Python (`ast`) and JavaScript (tree-sitter) adapters with
  byte-to-character column mapping, explicit parse-failure propagation,
  `MAGIC001` (value-based 0/1, folded unary sign, annotations flagged),
  `SUPP001`/`SUPP002` inline suppression checks, per-path overrides,
  configuration-file exemption, JSON report (`schema_version` 1) and text output.
- Milestone C: catch facts in the IR (exception identities with
  exact/approximate/unresolved confidence, handler body classification,
  try-body operation attribution) for Python `except`/`except*` and JavaScript
  `catch`, `.catch(handler)`, `.then(ok, handler)`; `EXC001` forbidden catch
  (boundary whitelist, fail-closed on bare/unresolved identities, JavaScript
  instanceof-guard convention), `EXC002` suppressed or converted exception,
  `EXC003` broad try scope; `rules.exceptions.transparent_rethrow` (default
  false); boundary `exception` names validated as dotted class names; every
  boundary and `transparent_rethrow` reported under `config.deviations`.
- Milestone D: default facts in the IR (`DefaultFact`: family, kind, subject,
  fallback, constant-shapedness, syntactic context, confidence) extracted by
  `ir/python_defaults.py` and `ir/javascript_defaults.py`; `DEF001` parameter
  and dataclass-field defaults, `DEF002` mapping/attribute/property fallbacks
  (plus the implicit `None` of `.get(key)` as a review finding), `DEF003`
  truthiness fallbacks (review by default; Boolean logic excluded), `DEF004`
  nullish fallbacks, `DEF005` exception-to-default (literal returns and
  one-step static traces to module constants and one-return helpers), `DEF006`
  configuration fallbacks (`os.getenv`/`os.environ`/`process.env` in every
  spelling); new `rules.defaults` keys `dataclass_fields`, `nullish_fallbacks`,
  `configuration_fallbacks` (all `forbid`); loosened modes reported under
  `config.deviations`; 13 golden fixtures and 25 unit tests; `safe_autofix` is
  false for every finding.

### Changed
- `EXC002` no longer reports the `return_fallback` classification while `DEF005`
  is active: the handler is reported once, as `DEF005`, with the EXC002
  classification named in the message. Disabling `DEF005` restores the EXC002
  finding. Golden expectations for the eleven affected handlers changed rule ID
  only.
- The tool's own code was brought under `DEF002`/`DEF004`: three `setdefault`
  accumulators became explicit membership checks, the report's
  `discovery`/`explicit_targets_excluded` fields are built with an explicit
  branch, and nineteen `x if x is not None else v` expressions on parser fields
  became either explicit branches (genuinely optional values: import aliases,
  `from . import`, source segments) or assertions of grammar invariants (fields
  tree-sitter and `ast` always populate). A Python `SyntaxError` position is now
  recorded only when the interpreter reports both a line and a column; before,
  a missing column was silently replaced by column 1.
- The arities that distinguish `getattr(o, a, v)` and `m.get(k, v)` from plain
  lookups are named in `constants.py`.
- The tool's own boundaries were narrowed to satisfy `EXC003`: config decoding
  and TOML parsing are two `try` blocks, analyzed-file decoding is bound before
  the result is returned, and comment tokenization materializes the token list
  in the one protected call. Behaviour is unchanged.

### Dependencies
- `tree-sitter` 0.25.x (MIT) and `tree-sitter-javascript` 0.25.x (MIT). Pinned
  as a tested pair; language ABI 15. `tree-sitter` 0.26.0 is excluded: with
  CPython 3.14 it segfaults when walking trees nested deeper than about 200
  levels (CPython 3.13 with 0.26.0 and CPython 3.14 with 0.25.2 are both fine).
  The 300-deep nesting test in `tests/unit/test_javascript_adapter.py` guards this.
