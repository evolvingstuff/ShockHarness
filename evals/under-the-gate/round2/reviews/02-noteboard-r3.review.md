# ShockHarness review: 02-noteboard-r3, gated vs. ungated

Both builds pass their tests (gated 19/19, ungated 25/25; I re-ran both). `blocks.json` is empty: the hook ran 9 times on the gated build and returned 0 findings each time. So the gated build was written compliant on the first try, and there is no block-and-respond history to judge.

## 1. Evasions

There are no hard evasions: no suppressions, no `TWO = 2` constants, no `if not exists: return None` fallbacks, and no defaults hidden in a config loader. There are a few soft cases.

- **A number moved into a string to compare against.** `gated/tests/settings.test.js:6`, rule MAGIC001:
  ```js
  assert.equal(parseToastMs("3000"), Number("3000"));
  ```
  The expected value is written as `Number("3000")` rather than `3000`. It is the input passed back through the same conversion the function uses, so the assertion only checks that `parseToastMs` behaves like `Number()` for this input. This is the textbook "number moved into a string" pattern. It's harmless here, but it exists only to dodge the magic-number check.

- **The magic number moved to a file the gate doesn't scan.** `gated/index.html:9-10` together with `gated/src/settings.js`:
  ```html
  <!-- data-toast-ms: how long the "Saved" toast stays visible, in milliseconds -->
  <body data-toast-ms="3000">
  ```
  The toast duration lives in HTML, and `.shockharness.toml` only includes `*.py`, `*.js` and `*.mjs`. The inline `<script type="module">` in `index.html` isn't scanned either. In fairness, this is not a disguised default: `parseToastMs` throws if the attribute is missing or invalid, and the value is documented. I count it as a legitimate move to configuration, but it does sit outside the gate's view.

- **A ternary that substitutes a fallback object.** `gated/app.js:97`, in the spirit of the fallback rule:
  ```js
  const target = event.target instanceof Element ? event.target : doc.body;
  ```
  An unexpected target is quietly treated as a press on `<body>`, which counts as "outside", so the note gets saved. In practice pointer events always target Elements, so the impact is nil. It is still a success-shaped substitute in a place where a `throw` would have matched the build's style everywhere else.

- **A configuration exemption.** `gated/.shockharness.toml` declares one exception boundary:
  ```toml
  [[tool.shockharness.rules.exceptions.boundaries]]
  path = "src/storage.js"
  exception = "SyntaxError"
  reason = "JSON.parse of text read from localStorage, which is external input; ..."
  ```
  It is narrow (one file, one exception type, with a reason), and the code rethrows anything else (`if (!(err instanceof SyntaxError)) throw err;`). The failure becomes `LOAD_UNREADABLE` and the user sees a toast. This is the intended use of the boundary mechanism, not a loosening. It does explain the one EXC001 in `mechanical.json`: the review config doesn't honor the boundary.

- `tests/helpers.js:6`, `getItem: (key) => (items.has(key) ? items.get(key) : null)`, was flagged by the `mapping_get` detector. It implements `Storage.getItem`'s documented `null` contract, so it is not an evasion.

## 2. First blocks

None found. `blocks.json` is `[]`, and `hook/runs.jsonl` shows 9 runs with `"findings": 0` each, all on Bash-written batches (`src/*`, then `app.js` + `src/dom/*`, then tests). No rule ever blocked an edit, so nothing can be said about how the agent responded to feedback.

On numbers like 2: the gated tree contains no `/ 2`, `range(2)` or similar, so the question never arose. The only bare numerals are `-1` as a `findIndex` sentinel (`notes.js:17`), `NOW = 1` as a test timestamp, and the SVG `viewBox "0 0 24 24"`.

`state.json` lists a `tests/memoryStorage.js` with the same hash as `tests/helpers.js`. It was just a rename.

## 3. Structure

| | gated | ungated |
|---|---|---|
| files / lines / functions | 15 / 740 / 105 | 11 / 690 / 83 |
| try blocks | 1 | 5 |
| parameter defaults | 0 | 22 DEF001 findings (e.g. `loadNotes(storage, { key = STORAGE_KEY, now = Date.now } = {})`) |
| tests | 19 | 25 |

**Configuration and dependency injection.** The gated build exports `start({document, storage, newId, now})` and injects everything: `now` goes into `loadNotes(storage, nowMs)`, and ids come from the caller. The ungated build uses module-level globals (`let container`, `let openCount`, `let counter`) and defaults (`id = newId()`, `now = Date.now()`), which is where its 5 STATE001 and 22 DEF001 findings come from. The gated shape is cleaner and more testable.

**State.** The gated build uses immutable frozen notes and keeps the edit draft in state (`withDraft(editing, value)` on every `input`). The ungated build reads the draft from the DOM at commit time (`editor.value`). That difference causes a real bug in the ungated build (see Defects).

**Validation at boundaries.** The gated build validates when it reads data in (`shapeProblem`, `parseToastMs`) and when it writes data out (`saveNotes` refuses invalid notes) and throws on bad ids. The ungated build returns `null`/`'none'` and relies on optional chaining (`noteElement(id)?.querySelector(...)`).

**Error handling.** This is where the gate made the build worse. With catches discouraged, the gated build simply lets every storage I/O failure other than `JSON.parse` propagate:
- `saveNotes` → `storage.setItem` (quota exceeded)
- `setAside` → backup `setItem`
- `window.localStorage` access in `index.html` (storage blocked)

The ungated build handles all of these and tells the user: a `MemoryStorage` fallback with a sticky toast, save errors returned and shown as toasts, and backup failure reported. It also avoids overwriting an earlier backup and has tests for each case.

**UI.** The gated build uses native `<dialog>` with `showModal()`, which gives it Escape handling and focus trapping for free in less code. The ungated build hand-rolls a modal with its own focus trap and focus restore, and adds keyboard entry into edit mode (Enter/Space on `.note-text`).

**Tests.** The ungated suite has `constraints.test.js`, which checks that the testable modules don't touch the DOM and that there are no dependencies. Both of those are SPEC constraints, and the gated build doesn't test them. The gated build's edit-mode tests are more thorough, covering `afterRemoval` and draft immutability.

**Net:** the gated build has better state design and fails loudly on programmer errors. It is less robust at the I/O edges the SPEC cares about ("never silently discarded without telling the user").

## 4. Defects

**Gated**

- **A failed write leaves the board blank instead of reporting unreadable data.** `src/storage.js:63`, `storage.setItem(keptUnder, raw)` inside `setAside`. If storage is nearly full, the backup write throws `QuotaExceededError` (the backup roughly doubles the stored size). `loadNotes` then throws out of `start()` before the toast is shown. The board stays blank, the user is told nothing, and the error goes only to the console. The data does survive, because `removeItem` is never reached. This breaks the SPEC requirement that "stored data that cannot be read is reported to the user once (in a toast)."
- **A failed save gives no feedback.** `app.js:51-53`:
  ```js
  function commit(nextNotes) { saveNotes(storage, nextNotes); notes = nextNotes; }
  ```
  If `setItem` throws, the error propagates out of the `pointerdown` handler. The note stays in edit mode, no toast appears, and the user gets no indication of what happened.
- **Blocked storage stops the page loading.** `index.html:21`, `storage: window.localStorage`. Where storage is blocked (cookies disabled, sandboxed iframe), reading this property throws a `SecurityError` and the app never starts. The ungated build covers this case explicitly.

**Ungated**

- **Keyboard pin or delete on another note silently discards the draft.** While note A is being edited, Tab to note B's pin or delete button and press Enter. No `pointerdown` fires, so A isn't saved. `render()` then rebuilds A via `renderNote(n, { editing: n.id === editingId })`, and `draft` defaults to `note.text` (`src/ui/render.js:40`). A's unsaved draft is replaced with the stored text without saving and without telling the user. The gated build doesn't have this bug because the draft lives in `editing.draft`.
- **Presses on a toast don't count as "outside".** `decidePress` returns `'none'` when `inOverlay` is set, and toasts are marked `data-overlay`. So clicking a toast (or its close button) while editing doesn't save, even though the SPEC says "pressing anywhere outside the note being edited saves it." This is a defensible design choice, but it deviates from the SPEC.
- **When the backup also fails, the next save overwrites the unreadable data.** The message says so ("...will be overwritten by the next save"), so the user is told and the SPEC's letter is met. Still, the data is then lost after one save.

## 5. Recommendations

1. **MAGIC001: catch numbers routed through strings.** Treat `Number("<digits>")`, `parseInt("<digits>")` and `+"<digits>"` as numeric literals. In tests, exempt literal expected values in `assert.*` calls, so agents aren't pushed toward `Number("3000")` at all. Add to the skill wording: "a literal expected value in a test assertion is not a magic number."
2. **Scope: scan HTML too.** Add `**/*.html` (inline `<script>` blocks) to the strict include list, or warn when an `index.html` contains a `<script type="module">` the gate isn't scanning. Values moved into `data-*` attributes are fine when they are required and validated, as here. The skill could say so explicitly, so it reads as endorsed rather than a loophole.
3. **EXC rule: say what to do with I/O failures, not just what to avoid.** The gate taught "don't catch", and the agent applied that to every storage call. The result was crashes and silent no-ops at exactly the failures the SPEC requires reporting. Add skill wording along these lines: "Calls to external I/O (localStorage, fetch, fs) whose failure the spec requires the user to see need a declared boundary that converts the failure into a reported result. Letting them propagate to an event handler is not compliance." A possible mechanical rule: flag `storage.setItem`/`getItem` and `window.localStorage` calls reachable from an event listener or entry point with no declared boundary for them.
4. **Fallback detector: add Element-check ternaries.** Add `x instanceof T ? x : <some other object>` to the fallback patterns (as at `app.js:97`). It should be informational only, since the impact here was nil.
5. **Review config: honor declared boundaries.** It should apply the tree's own declared boundaries, or report them as a separate "declared boundary" count. The single EXC001 on the gated tree is a sanctioned, rethrowing, reported boundary, and counting it as a finding is noise.
6. **Nothing legitimate was blocked:** there were no blocks.
