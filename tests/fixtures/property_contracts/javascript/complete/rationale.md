# Spec §11.3: JavaScript, `complete`

`enforcement = "complete"`: every parameter of every module-level function needs a
`requires`, and every return a `produces` or `preserves` (PROP008).

- `summarize`: its parameter `note` has no `requires` (PROP008), and its return has no
  `produces` or `preserves` (PROP008). `redact(note)` is PROP001, because `note` carries
  nothing and `redact` requires `decrypted`.
- `sendToModel`: `return post(note)` has no `produces` or `preserves`, so it is PROP008.

**One difference from the spec.** §11.3 expects two PROP008 and one PROP001. The rule as
§9 states it ("every return must carry a produces or preserves") also reports
`sendToModel`'s return, so this fixture has three PROP008. The fix in `complete-fixed`
drops that return, because a result that carries nothing has no declaration form (see
STATUS.md, P3).
