# JavaScript methods through their receivers (docs/proposal-receivers.md, R2)

A method call resolves when its receiver is exact. JavaScript methods take no implicit
parameter, so the call's arguments are the method's parameters.

- `throughSingleton`: `export const store = new Store()` is a module-level singleton,
  imported by name. `store.save(raw)` is PROP001, and `store.clean(raw)` produces
  `redacted`. `saveHere` is the same call in the singleton's own module.
- `throughObject`: `Redactor` is an exported object literal. Its method definition
  (`save`) and its arrow property (`clean`) are methods.
- `throughConstructed`: `const local = new Store()` in the function.
- `throughNew`: `new Store().save(raw)`.
- `objectThis`: inside `Redactor.echo`, `this` depends on how `echo` is called, so
  `this.clean(text)` is unknown.
- `Pipeline`: `this.clean(...)` and `this.tidy(...)` are the class's own methods: `run`
  passes, `leak` is PROP001.
- `Base.run`: `Loud` overrides `clean`, so `this` may be a `Loud` and the result is
  unknown. `Quiet.relay` inherits `Base.clean`, and nothing derived from `Quiet`
  overrides it: it resolves and passes.
