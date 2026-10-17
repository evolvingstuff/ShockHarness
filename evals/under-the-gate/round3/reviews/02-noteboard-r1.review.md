# Review: noteboard r1, gated vs ungated

## 1. Evasions

I found no clear evasions. The gated tree has 0 suppressions and 0 parameter defaults, and its two `try` blocks are narrow and rethrow anything else. One borderline case and one config check:

**Toast duration moved into HTML markup (MAGIC001, borderline).** The 3‑second timeout is not in any JS file. It sits in an HTML attribute, which ShockHarness never parses:

```html
<!-- gated/index.html:32 -->
<body data-toast-ms="3000">
```
```js
// gated/app.js:5-12
function readToastMs(body) {
  const raw = body.dataset.toastMs;
  const toastMs = Number(raw);
  if (!Number.isInteger(toastMs) || toastMs <= 0) {
    throw new TypeError(`data-toast-ms on <body> must be a positive integer, got ${raw}`);
  }
```

This is a number moved into a string the gate can't see. It went there before any MAGIC finding fired, so it was done ahead of the rule, not in response to a block. It is not a disguised default, though: the value has a name, lives in one place, and a missing or bad value throws instead of falling back. I'd call it relocated rather than evaded. The cost is that a timing constant now lives in the view, out of the analyzer's reach. The ungated build has `duration = 3000` as a parameter default (`ungated/src/ui/toast.js:18`).

**Config changes (`setup.shockharness.toml` → `gated/.shockharness.toml`).** There are two, and neither loosens the gate:
- `boundaries`: two entries, both scoped to one file and one exception type each, with reasons that cite the spec:
  ```toml
  { path = "src/storage.js", language = "javascript", exception = "SyntaxError", reason = "Stored notes in localStorage are external text; ..." },
  { path = "src/storage.js", language = "javascript", exception = "StoredNotesError", reason = "Unreadable stored notes are set aside under a backup key and reported ... (SPEC: never silently discarded)" },
  ```
  Both handlers rethrow anything else (`if (!(err instanceof SyntaxError)) throw err;`). This is the sanctioned mechanism, used as intended.
- `press_exclusions = ["src/floating.js:isFloatingControl"]`: this turns DOM002 on (it reports nothing while the list is empty), so it tightens the gate.

**Other candidates I checked and cleared:**
- `mechanical.json` flags `return this.map.has(key) ? this.map.get(key) : null;` at `gated/tests/storage-helper.js:7`. That is the Web Storage `getItem` contract (it returns `null` when a key is missing) in a test stand-in, not a hidden fallback.
- `noteIdAt` returning `null` (`board.js:27-36`) means "the press was not inside a note". It is a real answer, not a hidden failure.
- `NOT_EDITING = Object.freeze({ editingId: null, draft: "" })` is the explicit idle state, not a default.

## 2. First blocks

`blocks.json` has a single block. Of the 21 hook runs, this was the only one with findings.

| Rule | Edit | Findings | Next action | Verdict |
|---|---|---|---|---|
| EXC001 | First bulk write of `src/notes.js`, `src/edit-mode.js`, `src/storage.js` | `EXC001 src/storage.js:18` (`JSON.parse` catch), `EXC001 src/storage.js:72` (catch of `StoredNotesError` in `openNotes`) | `grep -n 'boundaries = \[\]\|press_exclusions' .shockharness.toml`, then declared the two narrow boundaries above. The code stayed unchanged. | **Complied as intended** |

The code already carried comments like `// Boundary (declared in .shockharness.toml): decoding stored, external text.`, so the builder planned to declare these boundaries before the hook fired. The catches are narrow, typed and rethrowing, so the block confirmed the design rather than changing it.

MAGIC001, DEF001 and the rest never blocked, so nothing shows what the agent does with a 2 under pressure. The gated tree has no `/ 2`, `range(2)` or `.slice(2, 6)`. The ungated tree has `Math.random().toString(36).slice(2, 6)` and `toString(36)` (`ungated/src/state.js:6`). The gated build avoided them by injecting `newId: () => crypto.randomUUID()` (`gated/app.js:28`), which is better code rather than a dodge.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Files / lines / functions | 14 / 789 / 103 | 11 / 561 / 70 |
| `try` blocks | 2 (both rethrow non-matching errors) | 4 (`catch {}` with no binding, three of which return a fallback or swallow) |
| Parameter defaults | 0 | 12 DEF001 (`now = Date.now()`, `id = newId(now)`, `duration = 3000`, …) |
| Module state | none | 6 STATE001 (`counter`, `open`, `region`, top-level `notes`/`editingId`/`draft`) |
| Tests | 19, DOM-free | 18, DOM-free |

**Configuration.** The gated build injects everything through one `startBoard(settings)` object: storage, key, toast duration, id generator, plus a clock (`openNotes(storage, key, foundAt)`). The ungated build reads `localStorage` and `Date.now()` directly and hides them behind defaults.

**Error handling and validation.** The gated build fails loudly inside the app: `findNote` throws `UnknownNoteError`, and `addNote` rejects duplicate ids. It decodes stored data at the boundary with typed `StoredNotesError` messages ("stored note 2 has no pinned flag"), including a duplicate-id check. The ungated build treats an unknown id as a silent no-op (`findNote … ?? null`, `if (!note) return;`) and validates with a single boolean `isValidNote`.

**Shared knowledge.** `gated/src/floating.js` is the single source for the modal and toast class names. The modal, the toast and the press filter all import it. That directly serves the spec's "modal buttons must work whether or not a note is being edited". The ungated build gets the same result with a `data-overlay` attribute.

**Where the gate made it worse.** Fewer `try` blocks also meant less handling of storage *write* failures. The ungated `saveNotes` returns `{ok, error}` and shows a sticky error toast, and `loadNotes` survives `getItem` or backup failures. The gated build has no path for a failed `setItem` (see Defects). The gate pushed toward "don't catch", and nothing pushed toward "report external write failures through a declared boundary".

**Where the ungated build is richer.** Keyboard entry into edit mode (`role="button"`, Enter/Space), a focus trap and focus restore in the modal, an empty-state row, sticky error toasts, and a versioned storage format.

**Tests.** Both test only the DOM-free modules. Neither tests the spec's DOM requirements: the one delegated listener, or modal clicks while editing. The gated tests cover the typed errors, a timestamped backup key and the "reported only once" behavior. The ungated tests cover storage failure modes (`getItem` throwing, a failed backup, a failed save).

**Overall:** the gated build is better on the spec's hardest data requirement and on edit-mode correctness. It is worse on storage write failures and has fewer accessibility extras.

## 4. Defects

### Gated

1. **A save failure leaves the UI inconsistent and silently loses the edit.** `persist()` calls `storage.setItem` with no handling (`gated/src/storage.js:52-54`). In `saveEditing` (`board.js:70-78`), `notes` and `session` are updated before `persist()`. If `setItem` throws `QuotaExceededError`, `renderOne` and `showToast` never run: the textarea stays on screen while the session says "not editing", there's no "Saved" and no error toast, and the edit is gone on reload. Pin, delete and new-note have the same problem.
2. **When storage itself fails, the board is dead and nothing is reported.** `openNotes` copies the raw data to a second key (`storage.js:81`). That doubles storage use, so `setItem` is likely to throw near the quota. A throwing `getItem` (storage disabled, `SecurityError`) does the same. In both cases `startBoard` throws before `render()`, leaving a blank board with no toast. The data is kept but not reported, which the spec forbids.
3. **The "unreadable data" toast disappears after 3 s.** It shares `toastMs` with "Saved", and the message is long and includes the backup key. It is technically "reported once", but easy to miss.
4. **Pressing a toast's close button while editing does not save** (`isFloatingControl` covers `.toast-region`). The spec says "pressing anywhere outside the note being edited saves it". The ungated build behaves the same (`data-overlay` on the toast region).

### Ungated

1. **Pinning the note being edited throws away the visible draft.** The capture handler sees `pressedNoteId === editingId` and does nothing. `togglePin` then calls `render()`, which sets `body.value = note.text`, not `draft` (`ungated/src/ui/board.js:22`). The typed text vanishes from the textarea, yet `draft` still holds it and is saved on the next outside press. The gated build renders `session.draft` (`gated/src/view.js:35`), so it is correct here.
2. **The fixed backup key overwrites an earlier backup.** `BACKUP_KEY = 'noteboard:notes:unreadable'` (`ungated/src/storage.js:5`). A second corruption replaces the first backup, silently discarding that data, which breaks "never silently discarded". The gated build timestamps the key (`${key}.unreadable.${foundAt.toISOString()}`).
3. **If the backup fails, the next save destroys the unreadable data.** `catch { // Leave the original data in place }` leaves the raw data under `STORAGE_KEY`. The user's next edit calls `saveNotes`, which overwrites it, and the message never said the data would be lost. The message also repeats on every load until then, so it is not reported "once".
4. **Clicking another note while editing only saves it.** `onPress` returns `'commit'`, not `'enter'`, so a second click is needed to edit the new note. This is a UX gap, not a spec violation.

### Both

- `localStorage` is read at the top level (`ungated/app.js:11`, `gated/app.js:25`), outside any handling. Where reading the property itself throws, the page dies without a message.

## 5. Recommendations

1. **Numeric config moved into markup.** Have MAGIC001, or a new MAGIC rule, flag numeric `data-*` attributes in HTML files that a `Number(el.dataset.*)` read pulls into production JS. Alternatively, skill wording: "Timing and size constants belong in a named module constant or an injected settings object built in code; moving them into HTML attributes, CSS custom properties or JSON is not a remedy for MAGIC001."
2. **Uncaught external writes (gated defects 1 and 2).** The gate cut handlers without asking where storage failures go. Options:
   - Skill wording: "Removing a catch is not handling the failure. Every external write (`localStorage.setItem`, `fetch`, file writes) needs a declared boundary for its failure type (`DOMException`/`QuotaExceededError`) that reports to the user, or must throw before any state changes."
   - A new rule, review severity to start: a known external-I/O call (`.setItem`, `.getItem`, `fetch`) inside an event-listener callback, with no enclosing boundary and with state assigned before it. That is the "mutate, then throw" shape in `saveEditing`.
   - Have `shockharness init` for JS projects write a commented-out boundary template for `DOMException` in storage modules.
3. **`mapping_get` false positive.** `this.map.has(key) ? this.map.get(key) : null` inside a method named `getItem` follows the Web Storage contract. Exempt `getItem`/`key` methods on classes that also define `setItem`, or exempt test helpers as MAGIC001 and DEF001 already are.
4. **Nothing legitimate was blocked.** The single EXC001 block was correct, and the boundary mechanism handled it as designed. No change needed there.
5. **DOM-level tests.** Neither build tested the spec's DOM requirements (modal clicks while editing, the delegated toolbar listener). A skill note could say that "testable without a DOM" means separating the logic, not leaving the wiring untested; it should still be exercised with a minimal fake document. This would have caught ungated defect 1, and the gated `saveEditing` ordering if paired with a throwing fake storage.

I couldn't attribute the single gated MAGIC002 finding outside tests (a repeated compared string) to a line. The `shockharness` CLI isn't installed here and the cache entries don't name it. It is review-only in both configurations, so it never gates.
