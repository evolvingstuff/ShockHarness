# Declarations the analysis cannot use (PROP003, PROP006, PROP007)

- `typo`: `redcated` is not in the catalog, so this is PROP003 at `error`
  (`allow_undeclared = false`). The misspelled property is not counted, so it is never
  silently checked.
- `computed`: a property that is not a string literal is PROP006, and so is a `produces`
  with no property. Each call is the identity and contributes nothing.
- `keyword`: a keyword argument in a declaration is PROP006.
- `late`: a `requires` on a parameter after the parameter was used is PROP007, and it is
  not part of the contract.
- `branch`: a `requires` on a parameter inside an `if` is PROP007.
- `rebound`: the body rebinds the parameter, so the `requires` after that is a mid-body
  check on a local. `+ "!"` destroyed the property, so this is PROP001 (not PROP007).
- `foreign`: a function named `requires` from a module that is not the runtime module is
  an ordinary call. It is not PROP003, and `caller` has nothing to satisfy.
