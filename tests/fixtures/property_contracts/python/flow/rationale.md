# Transfer rules (spec §5.2, §13.1), one file plus a producer imported from another

- `preserved`: `preserves(result, source)` gives the result the source's set, so this is
  satisfied. `cleaned.strip()` alone would be a method on a value (unknown).
- `preserved_except`: `preserves_except` removes `redacted`, so this is PROP001.
- `one_branch`: only one path produces, and branches meet in the intersection, so this is
  PROP001.
- `both_branches`: every path produces, so this is satisfied.
- `every_iteration`: the property holds before the loop and after every iteration, so it
  holds at the fixed point and this is satisfied.
- `not_before_loop`: zero iterations leave `raw`, so this is PROP001.
- `mid_body`: a `requires` on a local is a check at that point. The first is satisfied.
  The second fails, because `+ "!"` destroys the property.
- `handler`: the except handler starts from the set at the start of the try, so the
  `redact` inside the try does not count there. That is PROP001; the call inside the try
  is satisfied.
- `method_call`: a method on a parameter is not resolved, so this is PROP001 (unknown).
