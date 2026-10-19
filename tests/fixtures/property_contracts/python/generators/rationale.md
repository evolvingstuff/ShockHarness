# Await, generators and async generators (spec §5.2c, P2)

The runtime module is named by a package name (`contracts_runtime`), not a path.

- `awaited`: `await fetch_redacted(raw)`, where `fetch_redacted` is a project async
  function. The await gives that function's result, so this is satisfied.
- `generated`: `for chunk in chunks([raw])`. The loop variable takes the generator's
  item set, the intersection over its yields, so this is satisfied.
- `consumed`, `list(...)` of a generator, is unknown: only a for loop binds a
  generator's items in this release.
- `expression`, `sorted(...)` of a generator expression, is unknown.
- `asynchronous_for`: an `async for` over a parameter, not a resolved async generator,
  is unknown.
- `joined`: the catalog has no `join` rule, so the join carries nothing (an
  undeclared operation destroys every property) and this is PROP001.
- `destroyed`: `html.escape` is a library call and carries nothing, so this is PROP001.
- `forward`, the redaction sink (the P2 "done when"): `async for` over
  `redacted_stream` passes, and over `raw_stream`, whose items are not redacted, is
  PROP001.
- `forward_delegated`: `yield from chunks(...)` gives the delegating generator the
  delegated item set, so this is satisfied.
- `forward_without_await`: a coroutine passed without `await` carries nothing of its
  own, so this is PROP001.
