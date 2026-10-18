# Spec §11.1 and §11.2, Python, `declared`

- `pipeline`: `fit(normalize(raw))` is satisfied. `normalize`'s result set is read from its
  own `return produces(...)` (one hop).
- `shortcut`: `raw` carries only `numeric`, which its own `requires` gives it, so this is
  PROP001 (violation).
- `shifted`: `+ 1` is an undeclared operation and destroys every property, so this is
  PROP001 (violation, `{}`).
- `through_registry`: `ops["normalize"]` is a computed callee, so this is PROP001
  (unknown). Unknown findings gate only with `fail_on_unknown = true`.

One deviation from the spec's text. In §11.1, `normalize` returns `produces(..., "normalized")`
and `fit` requires both `normalized` and `numeric`. By §5.2's own rules, the division
destroys `numeric`, so `pipeline` would be a violation there, not "satisfied". Here
`normalize` produces both properties, so the fixture matches the expectation the spec
states.
