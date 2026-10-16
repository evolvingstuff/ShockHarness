# examples/python: a Python consumer of ShockHarness

A tiny package that pins ShockHarness as a development dependency and runs it
as a CI gate. It is exercised by `scripts/consumer_upgrade_check.py` in the
ShockHarness repository, which copies it into a throwaway git repository,
installs the wheel under test, and checks that the gate passes here and fails
after one injected violation.

* `pyproject.toml` pins `shockharness==0.5.0` under `[project.optional-dependencies] dev`.
  Dependabot (`.github/dependabot.yml`) opens a PR when a new version is released.
* `.shockharness.toml` selects the `strict` profile, analyzes `src/` and
  `tests/`, and exempts tests from `MAGIC001`/`DEF001` with a stated reason.
* `src/example_service/http.py` carries the one deliberate, suppressed finding:
  an HTTP status literal with an RFC citation.
* `.github/workflows/shockharness.yml` calls the reusable workflow; its
  `shockharness-version` input must equal the pin in `pyproject.toml`.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/shockharness check .
.venv/bin/pytest -q
```
