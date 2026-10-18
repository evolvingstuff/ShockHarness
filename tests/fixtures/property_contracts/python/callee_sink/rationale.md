# Callee sinks with the producer in another file (spec §5.2b, P1a)

The catalog declares two sinks. One is a project callee
(`app.cloud.send_messages:0`), whose function has no `requires` of its own. The other is
a library callee (`json.dumps:0`). The producer `app.privacy.evaluate` lives in another
file, and its result set is read from its own `return produces(...)` (one hop). The
runtime module is a vendored path excluded from analysis.

- `cleared`: satisfied through the cross-file producer.
- `uncleared`: the same sink reached through `cloud.send_messages`, a module attribute
  call. This is PROP001 and names the sink, its reason and its producer.
- `by_keyword`: `messages=` maps to position 0 through the project callee's parameter
  list. This is PROP001.
- `by_keyword_cleared`: satisfied.
- `library`: `json.dumps(evaluate(raw))` is satisfied. `json.dumps(raw)` is PROP001. A
  keyword argument to a library callee cannot be mapped to a position, so
  `json.dumps(obj=raw)` is PROP001 (unknown).
- `method_on_value`: `raw.copy()` is a method on a value,
  so this is PROP001 (unknown).
