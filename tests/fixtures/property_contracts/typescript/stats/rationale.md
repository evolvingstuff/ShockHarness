# TypeScript (spec §11.4, P2)

TypeScript is the JavaScript form, and type annotations are ignored. `as`, `!` and
`satisfies` are transparent, and typed and `readonly` parameters are ordinary
parameters. `./stats` resolves to `stats.ts`.

- `pipeline` and `asserted` (through `!` and `satisfies`) are satisfied. So is
  `viaImport`, across files.
- `shortcut` is PROP001.
- `later`: `Promise.resolve(...)` is a library call. It carries nothing, and an await of
  it is transparent, so this is PROP001. Write `normalize(raw)` directly, or an async
  function that returns it.
