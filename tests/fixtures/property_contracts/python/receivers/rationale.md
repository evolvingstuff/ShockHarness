# Methods through their receivers (docs/proposal-receivers.md, R1)

A method call resolves when its receiver's class is exact, and the call's arguments start
after the parameter the receiver supplies (`self` through an instance, `cls` always).

- `through_singleton`: `store = Store()` is bound once at module level, so `store.save(raw)`
  is `Store.save` and `raw` meets `text`: PROP001. `store.clean(raw)` produces `redacted`.
  `save_here` is the same call in the singleton's own module.
- `through_constructed`: `local = Store()` is bound once in the function.
- `through_the_class`: a static method takes every argument; a class method's `cls` is
  supplied; `Store.save(store, raw)` passes `self` explicitly, so `raw` is `text`.
- `through_a_new_instance`: `Store().save(raw)`.
- `not_resolved`: `size` is a property, and `cache` is bound twice, so neither resolves and
  both results are unknown.
- `Pipeline`: `self.clean(...)` and `self.tidy(...)` are the class's own methods (no
  analyzed subclass overrides them): `run` passes, `leak` is PROP001.
- `Base.run`: `Loud` overrides `clean`, so `self` may be a `Loud` and the result is
  unknown. `Quiet.relay` inherits `Base.clean`, and nothing derived from `Quiet`
  overrides it: it resolves and passes.
