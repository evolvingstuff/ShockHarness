# Parametric summaries (decision 48, P3)

A generic wrapper passes on what its caller passed without naming the property:
`preserves(result, x)`, with `x` a parameter that requires nothing and that the body
never rebinds, makes the wrapper's result parametric in `x`. Each call site substitutes
its argument's set.

- `through_head`: `head(clean, 3)` carries `redacted`, and `head(other, 3)` is PROP001 (`other` carries nothing; `raw` itself carries `redacted` once `produces(raw, ...)` has run, §4.2).
- `through_considered`: a no-property `requires(x)` (a parameter considered, needing
  nothing) is still parametric.
- `keyword`: the argument is matched by keyword (`x=`).
- `except_one`: `preserves_except(..., x, "normalized")` passes on `redacted` and drops
  `normalized`, so `fit(...)` is PROP001.
- `not_parametric`: `ident` returns `x` with no `preserves`, so it carries nothing
  (decision 45). `rebinding` rebinds `x` before the `preserves`, so it is not the
  caller's value. Both are PROP001.
