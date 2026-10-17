# examples/js: a JavaScript consumer of ShockHarness

A tiny ES-module project gated by ShockHarness without adopting Python as an
application dependency: the analyzer lives in an isolated tool environment, not
in `package.json`. It is exercised by `scripts/consumer_upgrade_check.py` in the
ShockHarness repository.

Install the analyzer once per machine (pick one):

```bash
uv tool install 'shockharness==0.9.0'
pipx install 'shockharness==0.9.0'
```

Then:

```bash
shockharness check .     # or: npm run policy
node --test              # or: npm test
```

* `.shockharness.toml` selects the `strict` profile, analyzes `src/` and
  `test/`, and exempts tests from `MAGIC001` with a stated reason.
* `src/http.js` names an HTTP status as a module-level constant with its RFC
  citation; a named constant needs no suppression (spec 21.1 decision 36).
* `.github/workflows/shockharness.yml` calls the reusable workflow. In CI the
  analyzer pin is the `shockharness-version` input; Dependabot's
  `github-actions` ecosystem bumps the workflow ref, not that input, so bump the
  input deliberately when upgrading (see `docs/integration.md`).
