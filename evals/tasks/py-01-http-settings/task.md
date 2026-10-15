# py-01-http-settings: explicit HTTP settings

`src/app/settings.py` reads its configuration with environment fallbacks and
gives `connect()` a default port. Make every setting required and validated
once, at load time, and make `connect()` take the settings explicitly.

Contract (encoded in `tests/test_settings.py`):

* `load_settings(raw)` takes a mapping such as `os.environ`. It requires
  `REQUEST_TIMEOUT_SECONDS` (positive float) and `PORT` (integer 1-65535).
  A missing key raises `KeyError`; an invalid value raises `ValueError` whose
  message names the variable.
* `connect(host, settings)` returns `"<host>:<port>"`.

Keep `shockharness check .` clean (`gate: PASS (exit 0)`). The port ceiling is a
protocol constant (RFC 793 section 3.1, a 16-bit field), so at most one inline
suppression, on that constant's line and citing the RFC, is acceptable; no other
suppression is. Do not read the environment anywhere except through the mapping
passed to `load_settings`.
