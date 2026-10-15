# js-01-config-env: configuration is read once and validated

`src/config.js` reads `PORT`, `RETRIES` and `TIMEOUT_MS` with `||`, `??` and
destructuring defaults, and takes `process.env` as a parameter default.
Make the configuration explicit.

Contract (encoded in `tests/config.test.js`):

* `loadConfig(env)` takes the environment mapping as a required argument and
  returns a frozen `{ port, retries, timeoutMs }` of numbers.
* `PORT` must be a positive integer, `RETRIES` a non-negative integer,
  `TIMEOUT_MS` a positive number; a missing or invalid value throws
  `TypeError` whose message names the variable.

No `||`/`??` fallback, no destructuring default, no parameter default, no
numeric literal other than 0 or 1, no suppression. `shockharness check .`
must pass.
