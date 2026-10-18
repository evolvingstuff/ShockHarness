# f-strings, concatenation and format into Python sinks (spec §5.2a, §13.1), P1b

The same catalog shape as the JavaScript `innerHTML` fixture, with these sinks: a project
callee sink, `app.page.send_html:0`, and an assignment target, `body`.

- `empty`: `""` carries `sanitized_html` by `literal_satisfies`.
- `escaped`: an f-string of escaped parts composes.
- `sanitized`: the producer in another file.
- `interpolated`: PROP001, naming the part `tag`.
- `mixed`: PROP001. The concat rule accepts sanitized parts, and the f-string part
  carries nothing.
- `joined`: `"".join(...)` is unknown.
- `formatted`: `"...".format(escape(tag))` composes by the format rule. `"..." % raw` is
  PROP001.
- `respond`: the target `response.body`, satisfied for the escaped f-string and PROP001
  for the raw one.
