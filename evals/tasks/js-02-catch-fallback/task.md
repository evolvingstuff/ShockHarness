# js-02-catch-fallback: a typed failure instead of null

`src/body.js` parses a response body and returns `null` on any failure, and
`loadAll` turns a rejected fetch into an empty array. Decoding external input
is a legitimate boundary; swallowing a rejection is not.

Contract (encoded in `tests/body.test.js`):

* `parseBody(text)` returns the parsed object for a JSON object body and
  throws `ParseError` (exported) for malformed JSON; the `ParseError` carries
  the original error as `cause` (`new ParseError(message, { cause: err })`). A body that is not an object throws
  `ParseError` too (a check, not a catch).
* `loadAll(loaders)` awaits every loader and rejects when any loader rejects.

Declare the one boundary in `.shockharness.toml`
(`[[tool.shockharness.rules.exceptions.boundaries]]` with `path =
"src/body.js"`, `language = "javascript"`, `exception = "SyntaxError"` and a
`reason`). The handler's first statement must be the guard
`if (!(err instanceof SyntaxError)) throw err;`, the `try` must wrap only
`JSON.parse`, and no other `catch` may remain. `shockharness check .` must
pass without suppressions.
