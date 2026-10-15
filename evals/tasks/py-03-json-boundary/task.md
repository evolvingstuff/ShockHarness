# py-03-json-boundary: one declared boundary, typed failures

`src/app/store.py` loads a JSON store and hides every failure: malformed JSON
becomes `{}`, anything else becomes `None`, and one `try` wraps three
operations. Decoding external input is a legitimate exception boundary;
everything else is not.

Contract (encoded in `tests/test_store.py`):

* `load_store(text)` returns the decoded object when `text` is a JSON object
  whose values are strings.
* Malformed JSON raises `StoreError` whose message contains `malformed`.
* A JSON value that is not an object, or an object with a non-string value,
  raises `StoreError` (no `try` needed: these are checks, not catches).

Declare the one boundary in `.shockharness.toml`
(`[[tool.shockharness.rules.exceptions.boundaries]]` with `path`, `language`,
`exception = "json.JSONDecodeError"` and a `reason`), keep exactly one
operation inside the `try`, re-raise with `from exc`, and add no other
`except`. `shockharness check .` must pass without suppressions.
