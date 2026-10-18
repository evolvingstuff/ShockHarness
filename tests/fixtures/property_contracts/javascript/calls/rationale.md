# Call-site contracts in JavaScript (§11.1 in JavaScript, P1b)

The same pipeline as the Python `stats` fixture, with `path:export` references.
- `pipeline` and `use.js`'s `remote` are satisfied. `normalize` declares its result with
  the nesting idiom `produces(preserves(expr, x), "normalized")`, read one hop, the
  second time from another file.
- `shortcut` and `remoteBad` are PROP001: `raw` carries only `numeric`.
- `shifted` (an arrow function) is PROP001: `+ 1` destroys every property.
- `throughRegistry` is unknown: a method on a parameter is not resolved.
- `awaited` is unknown: an await.
- `upload`: a global callee sink, `fetch:1`, satisfied for `normalize(raw)` and PROP001
  for `raw`.
- In `use.js`:
  - `typo` is PROP003 (error);
  - `computed` is PROP006 (a property that is not a string literal);
  - `late` and `branch` are PROP007.
- `tests/setup.js` is a test bootstrap. `enable("check", ["numeric"])` matches the
  catalog's static set. `[]` is PROP005 (missing `numeric`). A list that is not a literal
  array is PROP006.
- `stream.js` (P2, spec §5.2c):
  - `awaitedCall` (`await` of a project async function) is satisfied.
  - `generated` (`for...of` over a generator, and over one that `yield*`s it) is satisfied.
  - `streamedItems` (`for await` over an async generator) is satisfied; over a parameter,
    it is unknown.
  - `notAwaited` passes a Promise without awaiting it, so it is PROP001.
  - `shortcut` is PROP002: it produces `normalized` outside its producer, `normalize`.

