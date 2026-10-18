# Spec §11.1 and §11.2, Python, `declared`

- `pipeline`: `fit(normalize(raw))` is satisfied. `normalize`'s result set is read from its
  own `return produces(...)` (one hop).
- `shortcut`: `raw` carries only `numeric`, which its own `requires` gives it, so this is
  PROP001 (violation).
- `shifted`: `+ 1` is an undeclared operation and destroys every property, so this is
  PROP001 (violation, `{}`).
- `through_registry`: `ops["normalize"]` is a computed callee, so this is PROP001
  (unknown). Unknown findings gate only with `fail_on_unknown = true`.

`normalize` uses the nesting idiom of spec §4.2 (v0.6, decision 37):
`produces(preserves(expr, x), "normalized")`. The division is an undeclared operation
and destroys every property; `preserves` gives the result `x`'s set (`numeric`), and
`produces` then adds `normalized`. Nested calls are evaluated inside out.
