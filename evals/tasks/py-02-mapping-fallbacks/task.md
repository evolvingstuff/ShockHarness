# py-02-mapping-fallbacks: optional means explicit

`src/app/profile.py` builds a one-line summary of a user record and papers
over missing data with `.get(key, default)`, `or` and `x if x is not None
else y`. Replace every fallback with an explicit contract.

Contract (encoded in `tests/test_profile.py`):

* `summarize(user)` returns `"<name> (<title>)"` when the record has a
  `title` key, and `"<name>"` when it does not. The `name` key is required: a
  record without it raises `KeyError`.
* `years_active(user, current_year)` returns `current_year - user["since"]`;
  `since` is required and must not be in the future (`ValueError`).

No `.get`, no `or` fallback, no `is not None` fallback, no numeric literal
other than 0 or 1, no suppression. `shockharness check .` must pass.
