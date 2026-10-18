# `complete_paths` and PROP008 in Python (spec §9, P3)

`complete` applies to `app/secure/**` only. `app/other.py` stays at `declared`, so
`undeclared` there is not reported.

In `app/secure/files.py`:
- `load_notes`: its parameter has no `requires` and its return no `produces` or
  `preserves`, so each is PROP008. This is §7.1's example.
- `validate` and `checked` declare everything; `requires(path)` with no property records
  that a parameter needs nothing.
- `nothing` has no return value, so it has no result contract.
- `returns_none`: `return None` declares no result.
- `Store.__init__`: `self` is not a contract parameter. `Store.fetch`: `*rest` has no
  `requires` (PROP008), and `return read(path)` has none (PROP008).
- `Store.build`, a staticmethod: `root` is a parameter (PROP008), and so is the return
  (PROP008).
- `outer`: the nested `inner` is not a contract unit.
