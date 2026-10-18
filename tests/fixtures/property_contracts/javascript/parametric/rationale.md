# Parametric summaries in JavaScript (decision 48, P3)

- `head(clean, 3)` and `first(clean)` (an arrow with an expression body) carry
  `redacted`.
- `head(other, 3)` is PROP001 (`other` carries nothing; `raw` itself carries `redacted` once `produces(raw, ...)` has run, §4.2).
- `ident(clean)` carries nothing (decision 45), so it is PROP001.
