# f-strings, concatenation and format into Python sinks (spec §5.2a, §13.1), P1b

The same catalog shape as the JavaScript `innerHTML` fixture, with these sinks: a project
callee sink, `app.page.send_html:0`, and an assignment target, `body`.

- `empty`: `""` carries `sanitized_html` by `literal_satisfies`.
- `escaped`: an f-string of escaped parts composes.
- `sanitized`: the producer in another file.
- `interpolated`: PROP001, naming the part `tag`.
- `mixed`: PROP001. The concat rule accepts sanitized parts, and the f-string part
  carries nothing.
- `joined`: `"".join(...)` of a generator whose element is an f-string of escaped parts
  composes by the join rule.
- `formatted`: `"...".format(escape(tag))` composes by the format rule. `"..." % raw` is
  PROP001.
- `respond`: the target `response.body`, satisfied for the escaped f-string and PROP001
  for the raw one.
- `headers_out`: the target `headers[]` matches `response.headers[name]` by the
  receiver's final identifier (decision 43). `header_value(raw)` passes. `= raw` and
  `+= raw` are PROP001.
- `joined_raw`: PROP001, naming the element `f'<li>{i}</li>'`, which does not carry
  `sanitized_html`.
- `indented`: PROP001. Prefixing each line of sanitized markup builds new strings from
  `splitlines()` items, which carry nothing; the note names the part `PREFIX + line`.
- `listed`: a list display of sanitized parts composes by the join rule.
