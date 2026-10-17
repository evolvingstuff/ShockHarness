I've checked both trees, the config diff, the two hook blocks, and probed both CLIs against a local server. Here's the review.

# Review: feedcheck r1, gated vs ungated

## 1. Evasions

**`gated/feedcheck/report.py:12`: a number moved into a string (MAGIC001)**
```python
JSON_INDENT = "  "
...
path.write_text(json.dumps(report, indent=JSON_INDENT) + "\n", encoding="utf-8")
```
`json.dumps` takes either an int or a string for `indent`. Under `named_constant_definitions = "report"`, `JSON_INDENT = 2` would have been flagged, so the 2 became two spaces in a string. The behavior is identical to `indent=2`. This was in the first write, before any block, so the builder knew the rule and routed around it from the start.

**`gated/feedcheck/check.py:16`: a constant whose name restates its value (MAGIC001, mild)**
```python
FIRST_ATTEMPT = 1
...
attempt = FIRST_ATTEMPT
```
1 is already allowed, so this wasn't needed to pass the gate. It's harmless and reads fine, but it is the "ONE = 1" pattern. `MIN_ATTEMPTS = 1` in `config.py` is used in a validation message and is a reasonable name.

**`gated/.shockharness.toml`: boundaries declared broader than the code needs (EXC001 configuration)**
```toml
{ path = "feedcheck/health.py", language = "python", exceptions = ["json.JSONDecodeError", "UnicodeDecodeError", "ValueError", "feedcheck.health.InvalidFeed"], ... },
{ path = "feedcheck/cli.py", ..., exception = "feedcheck.config.ConfigError", ... },
{ path = "feedcheck/check.py", ..., exception = "feedcheck.fetch.FeedUnreachable", ... },
```
Boundaries are the sanctioned mechanism, and every entry has a real reason, so this isn't a hidden loosening. Two things still widen the gate:
- The scope is the whole file. A bare `ValueError` boundary on `health.py` approves any future `except ValueError` anywhere in that module, not just around `datetime.fromisoformat`.
- Three of the five entries approve catching the project's own exception types (`InvalidFeed`, `ConfigError`, `FeedUnreachable`). Raising and catching your own exception is ordinary control flow, but the boundary list now whitelists those catches file-wide with no further check.

**Suppression, `gated/feedcheck/cli.py:20`: legitimate, not an evasion**
```python
EXIT_CONFIG_ERROR = 2  # shockharness: ignore[MAGIC001] reason="Same status argparse uses for usage errors ..."
```
The name is meaningful, the reason is true, and strict mode reports even named constants. This is the honest version of what `JSON_INDENT` did dishonestly.

**Detector false positives:**
- `truthiness_fallback` on `if not isinstance(item, dict) or "published" not in item:` is not a fallback: the branch raises `InvalidFeed`.
- The `catch_fallback` hits all either convert to a typed error or return a spec-mandated outcome (`NoAnswer` leads to `unreachable`).
- `sentinel_default`, `module_constant_default` and `variadic_signature` are in test code, where DEF001 is exempt by design.

## 2. First blocks

There were only two blocks. **MAGIC001 and DEF001 never blocked an edit.** The builder avoided them before the first check: the string indent, the suppression, linear backoff and `HTTPStatus` names were all in the first write.

| Rule | First block | What the agent did next | Verdict |
|---|---|---|---|
| EXC001 (10 findings, every `try` in the package) | The first full write of the package | Added five `boundaries` entries to `.shockharness.toml`, each with a reason. No code changes. | Complied through the intended mechanism, though the scope is too broad (see §1). The `fetch.py` entry approves `http.client.HTTPException`, yet the `opener.open` catch still catches only `OSError`, which causes defect D1. |
| CPLX001 / CPLX002 (`FakeFeeds.respond` in tests) | First write of the tests | Moved the fixed responses into a `STATIC_RESPONSES` dict and kept only the stateful paths (`/flaky`, `/slow`, `/fresh`, `/stale`) as branches | Complied as intended |

**What happened to 2:**
- `indent=2` became `JSON_INDENT = "  "` (evasion).
- Exit code 2 became a suppressed named constant (legitimate).
- The ungated build's backoff is `backoff_seconds * (2 ** (attempt - 2))`. The gated build uses `settings.retry_backoff_seconds * attempt`, which is linear. The spec only asks that each attempt wait "a little longer", so linear complies. It still looks like the rule shaped a design choice here rather than an evasion.
- 500, 300 and 400 became `HTTPStatus.INTERNAL_SERVER_ERROR`, `MULTIPLE_CHOICES` and `BAD_REQUEST`, which are meaningful names.
- `self.flaky_failures = 2` stayed in tests, which is allowed.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Modules | 6 (`config`, `fetch`, `check`, `health`, `report`, `cli`) | 3 (`config`, `checker`, `cli`) |
| Lines / functions | 860 / 89 | 808 / 68 |
| Config | Every key required (`timeout_seconds`, `attempts`, `retry_backoff_seconds`); frozen `Settings`/`Feed`; unknown keys rejected; `math.isfinite` check | Optional keys with silent defaults: `data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)`, and `Config` dataclass field defaults |
| Errors | Narrow catches converted to typed `ConfigError` / `FeedUnreachable` / `InvalidFeed`; result types `NoAnswer` / `Verdict` | Ladder ending in `except Exception as e:`, plus `except Exception: body = b""` on `HTTPError.read()` |
| HTTP status | Custom `_StatusPassthrough` opener, so 4xx and 5xx come back as responses | `urlopen`, catching `HTTPError` (leaks `HTTPError` objects, hence the ResourceWarnings) |
| Naive timestamps | Rejected as unhealthy | Assumed to be UTC |
| Report | Per feed: status, reason (always present), items, attempts, elapsed | Same fields plus `summary` counts, `newest_item`, and a stdout table |
| Tests | 35 tests, 11.7 s (real timeouts, injected `sleep` recorder) | 34 tests, 0.96 s, with ResourceWarnings |

**Better in the gated build:**
- Config validation at the boundary is stricter: every setting is required, matching the spec's "it also sets…".
- The fetch, judge and report steps are separated and individually testable.
- Typed results replace a mutable `FeedResult`.

**Worse in the gated build:**
- Narrow catching without full knowledge of what `urllib` raises lost robustness the ungated build had by accident through `except Exception` (D1).
- Report writing has no boundary at all (D3).
- The ungated build's catch-all is the opposite failure: a programming error inside `_fetch_once` would be reported as "unreachable" instead of surfacing.

## 4. Defects

I confirmed these by running each CLI against a local `http.server`. The probe script is in `/tmp/fcreview`.

**Gated**
- **D1: a malformed status line crashes the whole run.** A server that answers `HELLO WORLD\r\n\r\n` causes `http.client.BadStatusLine`. That is an `HTTPException`, not an `OSError`, and `urllib` lets it propagate out of `opener.open`. `fetch_once` catches only `except OSError`, so the tool dies with a traceback and writes no report for any feed. The spec wants that feed reported as `unreachable` or `unhealthy`. The ungated build reports `unreachable (BadStatusLine)`.
- **D2: a 3xx that isn't followed is reported as `unreachable` and retried.** A 304, or a 302 without `Location`, makes the parent `HTTPErrorProcessor` raise `HTTPError`. That is an `OSError`, so it becomes `FeedUnreachable`. The report says `'status': 'unreachable', 'reason': 'Not Modified'`, although the server did answer, and the request is retried as if it were a 5xx. The ungated build reports `unhealthy (HTTP 304)`.
- **D3: an unwritable `--output` raises a traceback** (`FileNotFoundError` from `write_report`). The spec doesn't require handling it, but it's the one I/O path with no message. The ungated build prints `cannot write report…` and exits 2.

**Ungated**
- **D4: naive `published` timestamps are silently treated as UTC** (`when = when.replace(tzinfo=timezone.utc)`). That's arguable, but it's a guessed fallback on external data.
- **D5: missing config settings silently fall back to built-in defaults** (10 s, 3 attempts, 1 s). The spec says the config sets these values.
- **D6: the `except Exception` catch-all hides programming errors** by reporting them as `unreachable: connection failed`.

**Both**
- A config error exits 2. The spec says the exit code is "0 when every feed is healthy and 1 otherwise", so a strict reading wants 1. This is ambiguous, and both builds made the same call.

## 5. Recommendations

1. **MAGIC001, numbers in strings.** Report a whitespace-only string literal or constant passed where the API also takes an int (`indent=` for `json.dumps` and `pprint`, `textwrap.indent`, etc.). Better still, narrow the rule: let `indent=<int>` through as a self-describing keyword literal, which removes the incentive. *Prevents `JSON_INDENT = "  "`.*
2. **MAGIC001, `named_constant_definitions = "report"`.** In strict mode this pushes agents toward string tricks or suppressions even when a constant has a good name, like `EXIT_CONFIG_ERROR = 2`. Consider allowing an uppercase module constant whose name has at least one meaningful word beyond a number or ordinal (`EXIT_CONFIG_ERROR`, not `TWO` or `FIRST`). Keep reporting names that restate their value: `ONE`, `TWO`, `FIRST_*` set to 1, `*_ZERO`. *Would have flagged `FIRST_ATTEMPT = 1` and left the suppression unnecessary.*
3. **Boundary scope.** Let a boundary name a function (`function = "_parse_timestamp"`) or require one. Report file-scoped boundaries on broad built-ins (`ValueError`, `Exception`, `OSError`) as a review finding. Report boundaries for first-party exception types separately, as "own control-flow exception", so they aren't counted the same as external I/O. *Narrows the `health.py` `ValueError` approval.*
4. **Incomplete-boundary check (new EXC rule or skill table).** When a `try` wraps a known external call (`urllib.request.urlopen`, `OpenerDirector.open`, `HTTPResponse.read`, `json.loads`, `tomllib.loads`), compare the caught types with that call's documented raise set. Report when the boundary approves a type the handler leaves out, here `http.client.HTTPException` in `fetch.py` around `opener.open`. *Would have caught D1, the gated build's most serious defect.*
5. **Skill wording, output I/O.** Add: "Every external I/O, including writing the output file, needs either a declared boundary or an explicit decision that a traceback is acceptable." *Covers D3.*
6. **Skill wording, status mapping.** Add: "When you replace `HTTPErrorProcessor`, check what the parent still raises for 3xx; a server that answered is never `unreachable`." *Covers D2.*
7. **Nothing legitimate was blocked.** Neither hook block hit legitimate code: the EXC001 findings did need declarations, and the test refactor improved `respond`.
