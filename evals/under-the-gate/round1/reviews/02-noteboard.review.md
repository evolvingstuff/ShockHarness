# Review: noteboard, gated vs ungated

I read both final trees, `mechanical.json` and `blocks.json`. I did not run either app in a browser. The DOM-event defects below come from reading the code.

## 1. Evasions

I found no serious ones. I found a few mild ones, almost all in the tests.

| File | Excerpt | Rule / comment |
|---|---|---|
| `gated/tests/core.test.js` | `const first = 1; const second = first + 1;` (twice) | MAGIC. The `2` is moved into arithmetic on a named `1`. This is the pattern you asked me to look for. |
| `gated/tests/core.test.js` | `removeNote(pinned, pinned.length + pinned.length)` | MAGIC. This builds a non-existent id out of arithmetic. |
| `gated/tests/core.test.js` | `assert.equal(two.length, two[1].id)` | The test only passes because ids are 1-based and sequential. It asserts an implementation detail without naming it. |
| `gated/tests/core.test.js` | `getItem: (key) => (data.has(key) ? data.get(key) : null)` | This is the membership-check-with-fallback pattern that the `mapping_get` detector flagged. It is defensible here, because the fake mirrors the `localStorage.getItem` contract. The detector cannot tell that apart from a hidden fallback. |
| `gated/src/edit.js` | `export const NOT_EDITING = null; export const NO_NOTE = null;` | Two names for the same `null`. They are not "name restates value" in the `TWO = 2` sense, and they do carry meaning. The test `pressOutside(first, NO_NOTE)` shows that equal values make them interchangeable, so the type system gives no protection. |
| `gated/index.html` | `<body data-toast-ms="3000">` | The magic number now lives in markup. `readToastMs` validates it and throws if it is missing or invalid, so it is not a silent default. It still shifts a core setting into a DOM attribute, and `start()` now depends on the page markup. |
| `gated/.shockharness.toml` | `[[...exceptions.boundaries]] path="src/storage.js" exception="SyntaxError"` | This is a gate-configuration change. It is the intended escape hatch. The catch it covers is narrow: `if (!(err instanceof SyntaxError)) throw err;`. It returns a `problem` string that becomes a toast, and the raw text is kept under a backup key. I consider it legitimate. Still, `check` reports 1 `EXC001` on the gated tree. The data doesn't say which catch that is, but it is most likely this `readJson` catch.
| `gated/app.js` | `const store = { notes, editing, draft }`, mutated in place | The ungated tree has `STATE001` for a module-level `let editingId`. Here the mutable state sits in a closure object instead. That is legitimate encapsulation, but the same rule would not flag it. |

There are no inline suppressions in either tree (`inline_suppressions: 0`). I found no disguised-default helpers and no `if (!exists) return null` patterns in `src/`. The `raw === null` branch in `loadNotes` is a genuine first-run case.

## 2. First blocks

`blocks.json` is `[]`, and `hook_blocks` is 0. The edit-time hook never fed anything back on this task, so there is nothing to report per rule, including what happened to `2` in `x / 2` or `range(2)`.

Two readings are possible:
- The agent wrote clean code the first time.
- The hook did not fire on `.js` edits.

I can't tell which from this data. The `+ 1` and `length + length` arithmetic in the tests suggests the agent was steering around a magic-number rule. That would mean the gate's wording was in the agent's context even if no block was logged.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Files / lines / functions | 9 / 399 / 69 | 8 / 300 / 42 |
| try blocks | 1 | 4 |
| Strict findings | 1 (`EXC001`) | 18 (`DEF001` ×5, `DEF002` ×2, `DEF003`, `DEF005` ×2, `EXC001` ×4, `EXC002`, `MAGIC001` ×2, `STATE001`) |
| Tests | 5 pass | 5 pass |

**Gated build**
- It has pure, frozen transitions (`edit.js`: `transition(editingId, saveId)`) and immutable list operations. `requireNote` and `findNote` throw `RangeError` on a bad id.
- `storage.js` is a single narrow boundary. Shape validation lives in `describeProblem`, which also checks duplicate ids. `unreadable()` backs up the raw text and returns the problem.
- It has no parameter defaults. The toast duration is passed in explicitly, and `act` throws on an unknown action.
- This is better at the spec's key requirement: unreadable data is reported once, kept, and never silently dropped.
- The cost is roughly 33% more code and a lot of ceremony (`freezeAll` re-copies on every operation).
- `start(doc, storage)` is injectable. The UI and edit logic stay out of `document`, as the spec asks.

**Ungated build**
- It is smaller and simpler, and it mostly works.
- It silently swallows two failures:
  - `saveNotes` catches storage errors and returns `false`, and the caller ignores the result. A quota error loses data with no message.
  - The backup write is `catch (_) { /* ignore */ }`. If the backup fails, the unreadable data is discarded, which the spec says must not happen.
- It uses default parameters (`initial = []`, `text = ''`, `{ duration = 3000 } = {}`) and a bare `8000`.
- It has module-level mutable state (`let editingId`) in `app.js`.
- The `.get`-style null-safe chains (`list.querySelector('textarea')?.focus()`, `el?.closest?.()`) hide absences.

Overall the gated build is safer for the stated spec, and its extra size mostly buys real behavior: validation, a backup, and fail-loud errors.

## 4. Defects

**Gated**
1. **A click inside the textarea being edited re-renders the whole list.** The list click handler runs `apply(beginEdit(store.editing, id))`, and `beginEdit` returns the same note id, so `apply()` still calls `render()`. `render()` rebuilds the `<textarea>`, and focus is only restored when the editing id changes. Clicking to place the caret destroys the focused textarea, the caret and selection are lost, and typing stops until the user clicks again, which re-renders again. The draft survives through the `input` listener. This is a significant usability bug. It is in `app.js`, in `apply` and the list click listener.
2. A toast that reports unreadable data uses the same 3 s timeout as "Saved". A long message vanishes quickly, though it is still shown once.
3. `saveNotes` and the backup `setItem` can throw (quota). That fails loudly rather than silently, but there is no user-facing handling, and `loadNotes` doesn't guard `getItem` throwing (it fails loudly too).
4. An empty note renders as an empty `<p>` with no placeholder. It is clickable only through the toolbar row.
5. Toast and modal clicks are excluded from outside-press saving. This is reasonable but is an unspecified extra.

**Ungated**
1. **Outside press is on `mousedown` and re-renders immediately.** The target element is detached before `click` fires. Clicking another note's body, or its pin or delete button, while editing may drop the `click`, because the mousedown target was removed (browser-dependent). The user may need a second click to switch notes or delete. I did not run it, so treat this as probable, not confirmed.
2. Cancelling the delete modal while editing triggers a `mousedown` outside the note. That saves and exits edit mode, and shows "Saved". This is an odd side effect of a Cancel click.
3. `saveNotes` swallows storage errors and the backup swallows its error (see §3). This is a silent-discard path that the spec forbids.
4. Escape does not close the modal. Pressing Escape while the modal is open and a note is being edited discards the edit.
5. The unreadable-data toast uses a magic 8 s, and `showToast` defaults to 3000.
6. `loaded.error` covers the getItem failure, but its message loses the actual cause.

Both builds pass their own tests. Neither tests the DOM glue, which is where the main bugs are.

## 5. Recommendations

1. **Make the magic-number rule resolve constant arithmetic in tests.** Fold `first + 1`, `x.length + x.length` and `a * 0 + 2`, and flag the folded values in test files too. Rule wording: "a literal rebuilt through arithmetic from other literals counts as the literal".
2. **Flag aliases that only restate a value** (`NOT_EDITING = null; NO_NOTE = null`). This is low priority, since the names carry meaning. A cheaper alternative is to require a one-line comment explaining each sentinel.
3. **Treat `data-*` attributes read as numbers in module code** as an extension point for magic numbers. If the HTML attribute is the only definition of a numeric setting, the rule should ask for it to be documented where it is declared.
4. **Narrow the `mapping_get` detector for test doubles.** Don't flag `has ? get : null` inside an object literal named like a fake or stub, or whose method name is `getItem`. Otherwise it blocks a faithful `localStorage` fake.
5. **Add a rule against ignoring a boolean success return** (`saveNotes` returning `false`, with the caller discarding it). It would have caught the ungated path.
6. **Report on the edit hook, not only on the gate.** Log when the hook runs on a file. `hook_blocks: 0` with an empty `blocks.json` can't tell "clean" from "never ran", and this run's data can't distinguish them.
7. **Add a skill hint about re-rendering on a click that doesn't change state.** The gated bug (a no-op transition still calling `render()`) is not something a static rule would catch. A line in the skill ("skip rendering when the next state equals the current one") would address it. The ungated mousedown/detached-target hazard deserves the same note.
8. **Document the `exceptions.boundaries` mechanism as the required way to catch** in `.shockharness.toml`, with an expectation that the catch narrows to the named exception and rethrows others, as `readJson` does. That use was correct here and should be the model.
