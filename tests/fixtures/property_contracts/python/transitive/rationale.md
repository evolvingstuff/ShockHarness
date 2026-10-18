# Transitive results, max_depth, PROP002 and PROP004 (spec §5.3, P2)

`max_depth = 2`: a result is followed through two calls, and a third is unknown.

- `one`: `wrapped` returns `redact(...)` without redeclaring it. One crossing reaches
  `wrapped` and a second reaches `redact`, so this is satisfied.
- `two`: `twice -> wrapped -> redact` is three crossings, so this is unknown ("more than
  max_depth = 2 calls away").
- `three`: deeper still, unknown.
- `recursive`: `looping` calls itself. Recursion is not followed, so this is unknown.
- `careless` (in text.py) produces `redacted` outside the catalog's producers
  (`app.text.redact`), so it is PROP002.
- `maybe` returns `redact(text)` on one path and `text` on the other. This is PROP004 at
  the return without the property; the function's result carries only the intersection.
