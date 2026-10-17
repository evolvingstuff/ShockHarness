# Review: feedcheck, gated vs ungated

Both builds pass their own tests: 9 tests for gated, 10 for ungated. I read both trees in full. `blocks.json` is `[]`, and `mechanical.json` reports `hook_blocks: 0` for the gated build. So the edit-time hook never fed anything back, and section 2 has no data.

## 1. Evasions

I found no systematic evasion. There is one suppression, one routing of numbers through the standard library, and a few smaller cases.

- **Suppression.** `gated/feedcheck.py`, rule MAGIC001:
  ```python
  EXIT_CONFIG = 2  # shockharness: ignore[MAGIC001] reason="2 is the conventional usage/configuration error exit status..."
  ```
  This is a bare literal with a justification. It is the build's only suppression. It sits next to `EXIT_OK = 0` and `EXIT_UNHEALTHY = 1`, which are not suppressed because small values apparently pass the rule.
- **Constant restating its value** (MAGIC001, mild). `EXIT_OK = 0` and `EXIT_UNHEALTHY = 1` do carry meaning, so they are acceptable. `URL_SCHEMES` and the `STATUS_*` strings are genuine names.
- **Number moved into the standard library.**
  ```python
  HTTPStatus.INTERNAL_SERVER_ERROR <= status <= HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED
  ```
  This is clearer than `500 <= s <= 599`, but it is incorrect. 511 is the last enum member, so statuses 512–599 are not treated as 5xx. A correct upper bound would need a literal or a `status // 100` computation. The rule was satisfied and the intent, "all 5xx", was lost.
- **Algorithm changed to avoid a 2** (MAGIC001). Backoff is `settings.backoff_seconds * attempt`, which is linear. The ungated build used `2 ** (attempt - 2)`. The spec says only "a little longer each time", so linear is valid. It still shows the pressure: the design moved to avoid a literal 2. Because `attempt == 0` is skipped by the `if attempt > 0` guard, the sleep is never zero, so there is no bug.
- **Default hidden as a sentinel** (DEF rules, mild). In `_parse_feed`, `max_age: float | None = None` followed by `if "max_age_hours" in table:` is a legitimate optional field, not a disguised fallback. `Feed.max_age_hours` has no dataclass default, and `FeedResult.reason` and `items` carry `None` explicitly. This is acceptable.
- **Assert-as-validation** (EXC/DEF family, not a rule evasion but a smell).
  - `assert isinstance(attempts, int)` is repeated after every `_require`.
  - `assert failure is not None` appears in `_fetch_with_retries`.
  - `main` has `if sys.flags.optimize: raise SystemExit("do not run with python -O: invariants are asserts")`.
  - The asserts replace typing, and the `-O` guard exists only to keep them valid. A typed `_require_*` helper per kind would avoid this.
- **Catch-and-translate** (EXC001). There are 12 `except` clauses, and the tool flags them all. Each one re-raises a typed error (`ConfigError`, `Unreachable`, `Unhealthy`) with `from exc`, or converts to a status in `check_feed`. None swallows the error or returns a success-shaped value. The catch-in-`check_feed` converts to `unreachable` or `unhealthy` with the reason preserved, which is the spec's requirement. These are false positives of the rule, not evasions.
- **Existence check returning a fallback where a catch was forbidden.** None found. `_items_of` and `_newest` raise `Unhealthy` on missing keys rather than returning a default.
- **Configuration loosening.** None found. No gate config changes appear in the tree.

## 2. First blocks

None. `blocks.json` is empty, so there is nothing about how the agent handled `x / 2` or `range(2)`. Any compliance in the final tree was done before the hook fired, or the hook did not fire. The `attempt` and `range(settings.attempts)` code shows no literal-2 problem.

## 3. Structure

| | gated | ungated |
|---|---|---|
| lines | 474 | 345 |
| functions | 44 | 29 |
| frozen dataclasses | 4 (`Settings`, `Feed`, `Config`, `FeedResult`) | 0 |
| parameter defaults | 0 | 7 |
| module constants | 10 | 4 |
| strict-config findings | 12 EXC001, 1 SLEEP001 | 66 (32 MAGIC001, 7 DEF001, 6 DEF002, …) |

- **Config.**
  - Gated requires an explicit `[settings]` table with `timeout_seconds`, `attempts` and `backoff_seconds`, and rejects anything else with a specific message. This is strict, but SPEC.md says the config "sets" these, so it is defensible.
  - Ungated silently defaults them (`DEFAULT_TIMEOUT = 10.0`, `DEFAULT_ATTEMPTS = 3`, `DEFAULT_BACKOFF = 0.5`). That is a usability gain and a DEF violation. The ungated code also puts them in the module and uses `table.get(key, default)`.
- **Error handling.**
  - Gated has a clear exception hierarchy where `Unreachable` means retry and `Unhealthy` means don't.
  - Ungated returns `(status, reason, count)` tuples and has fallbacks such as `status, reason, count = "unreachable", "no attempts made", None`, and `e.read()` failure → `b""`.
  - Ungated also has a lazy-import helper `http_errors()`, which is odd.
- **Validation at boundaries.** Gated validates and types the config once, so the rest of the code uses typed fields. Ungated passes loose dicts everywhere.
- **Tests.** Gated tests use real sleeps: `backoff_seconds = 0` in the config, but the suite takes 4.5s versus 1.0s. Ungated injects `sleep=` and tests that backoff grows (`test_backoff_grows`). Gated has no backoff test. This is the SLEEP001 hit.

Overall the gated build is better structured and more honest about failure, but it has more code and more ceremony (the asserts and the `-O` guard).

## 4. Defects

Gated:
- **Uncaught write error.** `_write_report` raises `ConfigError` on `OSError`, but `main` catches `ConfigError` only inside `_load_or_exit`. An unwritable `--output` therefore produces a traceback rather than a clear message. The ungated build handles this correctly.
- **5xx range.** Statuses 512–599 are classed as `Unhealthy` rather than retried, because of the `NETWORK_AUTHENTICATION_REQUIRED` upper bound (see above).
- **Empty `items` with `max_age_hours`.** It is `unhealthy` ("feed has no items, so its age is unknown"). The spec doesn't say, and ungated returns `stale`. Either is defensible.
- **Report fields.** The report omits `url` and the attempt count. The spec doesn't require them.
- **Required config keys.** A config without `[settings]` fails. A user who only lists feeds, as in the spec's first sentence, is rejected.

Ungated:
- **5xx exhausted is reported as `unhealthy` ("HTTP 503"), not `unreachable`.** SPEC.md groups "answers 5xx or does not answer at all" for retries, and `unreachable` is the status for non-answering. The spec is ambiguous here, but the gated reading, where `unreachable` covers both, is closer.
- **Unreadable output** is handled (exit 2). Missing config is handled.
- **`except ... ValueError` inside the fetch.** This also catches a `ValueError` raised by `resp.read()`, and the `ValueError` is silently turned into `unreachable`.
- **Timeout minimum `0.001`, hard-coded.** `if now - newest > timedelta(...)` is correct.
- **Empty feeds list** is rejected, which is a reasonable validation.
- **`ResourceWarning` for unclosed `HTTPError`** appears in the test output. Production code does not close the error on all paths.

## 5. Recommendations

1. **Narrow EXC001.** Do not flag `except X as exc: raise Y(...) from exc`, which is a translate-and-rethrow. It produced 12 false positives in the gated build, with no genuine swallow. Keep the rule for handlers that return, `pass` or `continue` without re-raising. Handlers in `check_feed` that record a status should be allowed when the reason is kept.
2. **Add a rule against enum-bounded numeric ranges.** Flag `X <= status <= Y` when both bounds are named members of a stdlib enum used as a range. Skill wording: "a class of statuses (5xx) is `status // 100`, not two enum members."
3. **Treat `assert isinstance` after a typed helper as a smell.** Flag three or more asserts of this kind in one module, or any runtime check of `sys.flags.optimize`. Skill wording: "do not use assert for validation; return a typed value from the helper."
4. **Make the suppression path visible.** The `ignore[MAGIC001]` for `EXIT_CONFIG = 2` is legitimate, but a rule that allows 0 and 1 and not 2 invites it. Either add exit codes 2 to the allowed set when assigned to a name beginning `EXIT_`, or permit a named constant at module level with a documented meaning. A suppression budget (say one per file) should be reported in review.
5. **Add a check that every handler path in `main` covers all raised project exceptions.** The uncaught `ConfigError` from `_write_report` is a boundary gap. A rule or skill note: "an exception class that only some call sites catch must be caught at the entry point."
6. **SLEEP001 on tests.** Fine as it stands, but the skill should say "inject the sleep function; don't just set the delay to 0." The gated build did neither.
7. **No hook evidence.** The hook was either not installed or never triggered, so none of these recommendations is confirmed against the hook's feedback loop. Check the hook wiring before drawing conclusions about its effect on the agent.
