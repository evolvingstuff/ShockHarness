# The innerHTML sink (spec §5.2a, §5.2b, §13.1), JavaScript, P1b

The catalog has two properties. `escaped_html` is produced by `escapeHtml`.
`sanitized_html` is produced by `sanitize` and marked `literal_satisfies`. Template
literals and `+` chains compose escaped parts into sanitized markup. A second concat rule
lets sanitized markup join sanitized markup. The assignment target `innerHTML` requires
`sanitized_html`. Both producers live in other files, read one hop. The runtime module
is a vendored path excluded from analysis.

- `clear`: `''` carries `sanitized_html` by `literal_satisfies`.
- `escaped`: every interpolation is escaped, so the template literal composes.
- `sanitized`: the cross-file producer.
- `interpolated`: PROP001, naming the interpolation `tag` that lacks `escaped_html`.
- `mixed`: PROP001. The template part is unestablished, so the whole carries nothing.
- `joined`: `.map(...).join("")` is not a composition in this release, so the finding is
  unknown.
- `concatenated`: `"<p>" + sanitize(raw) + "</p>"` is satisfied by the second concat rule.

Without that rule it would be PROP001: the typical one-rule catalog of §5.2a accepts
only escaped parts.
- `noLiteral`: `sanitize(a) + sanitize(b)` has no string literal, so it is not a
  composition (decision 42) and is PROP001.

