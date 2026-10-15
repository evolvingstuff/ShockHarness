# js-04-status-codes: protocol constants with a cited source

`src/status.js` compares HTTP status codes as bare literals. Those numbers
are protocol constants defined by RFC 9110; the right fix is a named constant
whose suppression cites the source, not a configuration value and not an
unexplained name.

Contract (encoded in `tests/status.test.js`):

* `isOk(status)` is true exactly for 200.
* `isMissing(status)` is true exactly for 404.
* `isServerError(status)` is true for 500 and above.
* Exported constants `OK`, `NOT_FOUND`, `SERVER_ERROR_FLOOR` carry the values.

Each constant's line carries an inline suppression with the exact rule ID
and a reason that cites RFC 9110 (sections 15.3.1, 15.5.5 and 15.6): at most
three suppressions, none elsewhere. `shockharness check .` must pass.
