# §11.3 after the fix: zero findings

The intended fix the spec names, made with the `property-contracts` skill:

- `summarize` declares `requires(note, "decrypted")` and returns
  `preserves(redacted, redacted)`, a result that carries what `redact` gave it.
- `sendToModel` no longer returns the provider's response. A result with no property
  has no declaration form, so a function with no return has no result contract (§16
  item 1).
- `redact` is unchanged; its `requires` was never the problem.
