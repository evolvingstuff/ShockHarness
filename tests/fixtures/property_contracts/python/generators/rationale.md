# Await, generators and .join are unknown in P1a (spec §5.2c, §5.2a)

P1 does not define these semantics, so every such construct yields `unknown`, which is
reported, never silent:

- `awaited`: an `await`.
- `generated`: items of a call to a generator function.
- `consumed`: `list(...)` of a generator.
- `expression`: `sorted(...)` of a generator expression.
- `asynchronous_for`: an `async for` item.
- `joined`: a `.join` build is not a composition in this release.

`destroyed` is the control: `html.escape` is a library call, which carries nothing, so it
is a violation, not unknown. The runtime module is named by a package name
(`contracts_runtime`), not a path.
