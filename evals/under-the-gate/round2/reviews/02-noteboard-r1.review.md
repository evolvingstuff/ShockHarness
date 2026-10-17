# Review: noteboard, gated vs. ungated

**Summary:** the gated build's hook ran 12 times and never blocked an edit, so `blocks.json` is empty. The gated build ends with one finding under the strict configuration: a declared, narrow exception boundary. It has two small evasions: a test number hidden in a string, and the toast delay moved into HTML. Its defects are in storage failures it lets crash. The ungated build has two real data-loss bugs.

## 1. Evasions

1. **A test number hidden in a string (MAGIC001).** `gated/test/config.test.js:7`:
   ```js
   assert.equal(parseToastDuration("3000"), Number("3000"));
   ```
   `Number("3000")` is the literal `3000` written as a string so the magic-number rule can't see it. It is a test's expected value, which should simply be a literal. This is the clearest evasion in the tree.

2. **The toast delay moved into an unscanned HTML attribute (MAGIC001 / DEF001).** `gated/index.html:9` has `<body data-toast-ms="3000">`. `src/config.js` then parses it, and `app.js:65` calls `parseToastDuration(doc.body.dataset.toastMs)`. The ungated build says the same thing as `const DEFAULT_MS = 3000;`.
   - The include list scans `**/*.js` but not `.html`, so the number now lives where the gate doesn't look.
   - This is the mild version of the pattern. `parseToastDuration` throws on a missing, non-integer or non-positive value instead of falling back, and a test checks that `index.html` carries the attribute.
   - Still, a config parser, a config test and a `checks.js` helper exist mainly to move one constant out of JS. It satisfies the letter of the rule; whether it meets the intent is debatable.

3. **A configuration change (EXC001 boundary).** `gated/.shockharness.toml` adds:
   ```toml
   [[tool.shockharness.rules.exceptions.boundaries]]
   path = "src/storage.js"
   exception = "SyntaxError"
   reason = "Decoding localStorage text, which is external input; ..."
   ```
   This is the sanctioned way to declare a boundary, and it is narrow. The code honors it: `catch (err) { if (!(err instanceof SyntaxError)) throw err; return Object.freeze({ ok: false, reason: ... }) }`, and the "unreadable" result is shown to the user. I judge it legitimate, not loosening. It is why the hook saw 0 findings while `mechanical.json` shows `EXC001: 1`: the reviewer's strict run doesn't apply the project's boundaries.

Nothing else turned up: no suppressions, no restated constants like `TWO = 2`, no `if (!exists) return null` fallbacks, and no parameter defaults. The `mapping_get` hits are all `Map.get` followed by an explicit `undefined` check or a fail-loud use, except `elementFor: (noteId) => elements.get(noteId)` (`board.js:101`). That one returns `undefined`, but its only caller dereferences it at once, so a missing note crashes rather than silently doing nothing.

## 2. First blocks

None found. `blocks.json` is `[]`. `hook/runs.jsonl` records 12 runs, all from Bash, all with `"findings": 0`. The agent wrote whole files in batches through Bash, e.g. `["src/checks.js","src/config.js","src/editMode.js","src/state.js","src/storage.js"]`, and every batch came back clean on first write.

So there is no block-and-response sequence to judge. On numbers like 2: the gated source contains no `/ 2`, `range(2)` or similar. The only numeric literals are `-1` (the `findIndex` sentinel) and `0` comparisons. Neither build needed any.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Files / lines / functions | 16 / 804 / 111 | 11 / 595 / 79 |
| `try` blocks | 1 (narrow SyntaxError boundary) | 4 (three bare `catch {}` that return messages) |
| Tests | 19, pass | 20, pass |

**State and validation.**
- The gated build freezes everything, and `state.js` throws on unknown ids (`indexOfId` raises `RangeError`).
- The ungated `findNote` returns `?? null`, and `updateText`/`togglePin` silently do nothing for unknown ids.
- The gated `writeNotes` refuses invalid notes at the storage boundary, and `describeShapeProblems` gives the user a specific reason ("note 3 has no boolean pinned flag"). The ungated build only says "could not be read".

**Edit-mode logic.**
- The gated build uses named action and place constants. `decidePress` rejects unknown places, and `afterDelete` is a pure, tested function.
- The ungated build passes string literals (`'commit'`, `'ignore'`).
- Both keep this logic out of the DOM, as SPEC asks.

**Rendering.** The gated `board.js` keeps one element per note and rebuilds a note's body only when `[isEditing, text]` changes. Pinning the edited note therefore keeps the unsaved text. The ungated build rebuilds the whole `<li>` whenever `[text, pinned, editing]` changes, which causes defect U2 below.

**Error handling.** This is where the gate cost something.
- The ungated build catches a `getItem` SecurityError, a failed backup and a `setItem` QuotaExceededError, and turns each into a toast.
- The gated build catches only `JSON.parse`. Storage I/O failures propagate as uncaught exceptions with no report to the user (defects G1 and G2).
- SPEC's core rule is "never silently discard without telling the user". On that rule the gated build is stronger when data is corrupt, but weaker when the storage device fails.

**Overall:** the gated build is the more correct one against SPEC. It avoids both ungated data-loss bugs and gives better diagnostics, at about 35% more code.

## 4. Defects

**Ungated**
- **U1, data loss.** `storage.js:5` uses one fixed `BACKUP_KEY = 'noteboard.notes.unreadable'`. A second corruption event overwrites the first backup, and that data is gone without any report, which breaks "never silently discarded". The gated build uses timestamped keys and refuses to overwrite (`setAsideUnreadable` throws).
- **U2, lost draft.** Pinning the note being edited loses the unsaved text. The click on pin changes `pinned`, so `signature` changes and `buildNote` replaces the `<li>`, setting `ta.value = n.text` from the stored text.
- **U3, repeated reports.** If the backup `setItem` fails, the original is left in place and reported again on every load, not once. (This is a deliberate trade-off, and it is tested.)
- **U4, silent no-ops.** `addButton?.addEventListener` and `const changed = ta && note && ...` do nothing quietly if an element is missing.

**Gated**
- **G1, failed save is silent.** A failed `setItem` (quota) throws out of the event handler. In `saveEdited`, `setNotes` throws before the "Saved" toast, so the edit stays open and the user is told nothing; the error only reaches the console.
- **G2, board never starts.** If `localStorage` access or `getItem` throws (storage disabled, SecurityError), or `setAsideUnreadable`'s `setItem` throws, `start()` aborts. No board renders and no toast appears, though SPEC requires unreadable data to be reported.
- **G3, Escape can do nothing.** The modal is a plain `div`, not `<dialog>`, so focus isn't trapped. If focus tabs out of the backdrop, Escape does nothing: the backdrop's handler doesn't see it, and `decideKey` returns keep because the modal is open.

**Both builds**
- Toasts are treated as overlays, so pressing a toast while editing doesn't save. That is a mild departure from "pressing anywhere outside the note being edited saves it".
- "New note" followed by Escape leaves an empty note saved, because the note is persisted before editing starts.

## 5. Recommendations

1. **Catch numbers written as strings.** Extend MAGIC001 to flag numeric string literals passed to `Number(...)`, `parseInt`, `parseFloat` or unary `+`. That would have caught `Number("3000")`.
2. **Don't push tests into evasion.** If MAGIC001 applies to tests, it is blocking something legitimate: literal expected values in assertions are the clearest way to write a test. Exempt the arguments of `assert.*` and `expect(...)` in test files, so agents don't need the string trick.
3. **Follow numbers into HTML.** Either add `*.html` to the scan for `data-*` numeric attributes and inline `<script>`, or add skill wording: "Moving a constant into markup or a config file does not satisfy MAGIC001 unless the value really is deployment configuration. Otherwise give it a meaningful name in code." The validated parser here was honest, but most of it exists only to work around the rule.
4. **Make the skill cover storage failures.** Add: "Failures of external I/O that the spec says must reach the user (storage quota, storage unavailable) should be declared as boundaries and turned into user-visible results, not left uncaught." The gate's pressure toward letting things crash produced G1 and G2, where SPEC wanted a report.
5. **Report boundaries in reviews.** Make the review run honor the project's declared `exceptions.boundaries`, or list them separately as "declared boundaries" rather than as unexplained `EXC001` findings. Otherwise a correct boundary looks the same as a swallowed exception.
