# Review: feedcheck, gated vs ungated

Both builds pass their own tests: gated 20/20 in 6.6s, ungated 40/40 in 2.2s. I also ran both CLIs against a local probe server to check the behavior differences reported under Defects.

## 1. Evasions

The gated tree has very few evasions. The only config change from `setup.shockharness.toml` is filling in `boundaries = []`. There are no inline suppressions (0), no rules disabled, no severities loosened, and no excludes added.

**a. A number moved into a string (MAGIC001).** In `gated/feedcheck/check.py:13,75`:
```python
REPORT_INDENT = "  "
...
path.write_text(json.dumps(report, indent=REPORT_INDENT) + "\n", encoding="utf-8")
```
The ungated tree writes `json.dump(report, handle, indent=2)`. `json.dumps` accepts a string for `indent`, so the 2 became two spaces. The name is fine, but the point of the string form is that MAGIC001 can't see it. Nothing ever blocked this: it was already in the first write of `check.py` (block 1's "after"), so the agent was avoiding the rule in advance. The harm is minimal.

**b. A membership check that reproduces a forbidden `.get` default (DEF002, test file).** In `gated/tests/test_feedcheck.py:47-54`, after the block:
```python
count = server.hits[self.path]          # hits is now collections.Counter()
server.hits[self.path] += 1
if self.path in server.routes:
    replies = server.routes[self.path]
    ...
else:
    reply = Reply(404, b"no route for this path")
```
This replaced `server.routes.get(self.path, [Reply(404, b"not found")])` and `server.hits.get(self.path, 0)`. The behavior is identical: the default moved into an `in`/`else` branch and into `Counter`'s implicit zero. It is test-fixture routing, though. A 404 for an unknown path is correct fake-server behavior, not a fallback that hides a failure. So I count this as a letter-only rewrite of something legitimate (see Recommendations), not a harmful evasion.

**c. A suppression in the first draft, later removed.** The first `fetch.py` contained:
```python
reason = getattr(exc, "reason", exc)  # shockharness: ignore[DEF002] reason="urllib.error.URLError wraps ..."
```
It did not appear in the hook's feedback, which listed only EXC001. The agent removed it anyway in its next edit and replaced it with an explicit `isinstance(exc, urllib.error.URLError)` branch (`fetch.py:83-86`). The final tree is clean, but the hook said nothing about a newly added suppression.

**d. Boundaries are legitimate but file-wide.** The four entries in `gated/.shockharness.toml` all have accurate reasons:
- `config.py`: OSError, UnicodeDecodeError, TOMLDecodeError
- `fetch.py`: OSError, `http.client.HTTPException`
- `health.py`: ValueError
- `cli.py`: ConfigError

Every handler converts the exception into a typed value or a clear `SystemExit`, and none swallows anything. The problem is scope: each boundary applies to the whole file. Any future `except ValueError` anywhere in `health.py`, or `except OSError` anywhere in `fetch.py`, is approved automatically. This uses the mechanism as designed, so it isn't an evasion, but it is wider than the stated reasons.

**Checked and clean:**
- Constants whose names restate their values: none. `MIN_ATTEMPTS = 1`, `EXIT_ALL_HEALTHY = 0` and `EXIT_NOT_ALL_HEALTHY = 1` carry meaning.
- Defaults moved into a loader or dataclass fields: none. Every `Config` field is required. `max_age: float | None = None` is a local that is set only when the key is present.
- Existence checks that return a fallback: none apart from (b).

## 2. First blocks

There were 16 hook runs and 3 blocks. Only three rules ever blocked anything, and MAGIC001 never did.

| # | Rule | Blocked | What the agent did next | Verdict |
|---|---|---|---|---|
| 0 | EXC001 (7×) | `config.py` read/parse catches, `fetch.py` open/read catches | Declared four `boundaries` entries with specific exception lists and accurate reasons. Left the handlers alone (they already converted to `ConfigError` or `NoAnswer`). In the same edit, voluntarily removed the `getattr` suppression. | Complied as intended. It used the sanctioned mechanism instead of rewriting catches into existence checks. |
| 1 | CPLX004 | `health.py:33` `judge` too complex | Extracted `_read_items(body) -> list[object] \| _Problem` | Complied. Real decomposition, and the result is more readable. |
| 2 | DEF002 (2×) | test server `routes.get(path, [Reply(404)])`, `hits.get(path, 0)` | `if path in routes … else Reply(404)` and `collections.Counter()` | Letter compliance. The behavior is unchanged and was legitimate to begin with (see 1b). |

**What happened to 2 and similar numbers:** no MAGIC001 block ever fired, because the agent wrote around the rule from its first draft:
- **Backoff.** Gated uses linear backoff, `sleep(retry_delay_seconds * retry)` over `range(1, attempts)`, which uses no 2 at all. Ungated uses `config.backoff_seconds * 2 ** (attempt - 1)`. Both satisfy "a little longer each time".
- **JSON indent.** The 2 became the string `"  "` (1a).
- **Hours.** `age / timedelta(hours=1)` replaces ungated's `/ 3600`. This is a real improvement, not an evasion.
- **5xx check.** `>= HTTPStatus.INTERNAL_SERVER_ERROR` replaces `500 <= status <= 599`. It's named, though it uses a single status code to stand for the whole 5xx class.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Lines / functions / files | 795 / 63 / 9 | 958 / 72 / 10 |
| Tests | 20 (one file) | 40 (config, checker, cli) |
| Frozen dataclasses | 9 | 2 |
| Parameter defaults (src) | 0 | 9 (`sleep=time.sleep`, `argv=None`, `default` param, …) |
| Config | All 3 settings required; unknown keys rejected | `timeout_seconds`, `attempts` and `backoff_seconds` silently default (`data.get("attempts", DEFAULT_ATTEMPTS)`) |
| Fetch errors | Typed `Answer \| NoAnswer` return values | Private `_Unreachable` exception used as control flow, plus `HTTPError` caught to read the status |
| Verdicts | `Status` StrEnum and a `Verdict` dataclass; `_Problem` values | String constants and `(status, reason, count)` tuples |
| Time injection | `Clocks` dataclass passed explicitly | Keyword defaults on `check_feed`, threaded through `**kwargs` |
| Concurrency | Sequential | `ThreadPoolExecutor(max_workers=8)` |
| Output | Plain `write_text`, write errors not handled | Atomic temp file + `os.replace`; output directory checked before fetching; per-feed stdout summary |
| Config error exit | `SystemExit("feedcheck: …")` → 1 | Prints and returns `EXIT_ERROR = 2` |

**Where the gated build is better at what SPEC.md asks:**
- **Config validation.** Requiring all three settings matches "the config file … sets how long to wait … and how many attempts".
- **Exit codes.** Config errors exit 1, which matches "0 … and 1 otherwise".
- **Readability.** Typed outcomes make the healthy/unhealthy/unreachable/stale classification easier to follow.
- **Timestamps.** It refuses to guess on naive timestamps instead of assuming UTC.

**Where it is worse:**
- **Coverage.** It has half the tests. Nothing tests a connection dropped mid-body, so the `response.read()` boundary is never exercised.
- **Unhandled boundaries.** Gate pressure against catches seems to have left the report write without any handling at all (Defects).
- **Redirects.** The `_KeepErrorStatus` processor stops urllib from following redirects.
- **Ceremony.** There is defensive code that adds nothing:
  - `if sys.flags.optimize: raise SystemExit("… invariants are asserts")` (`cli.py:29`)
  - the tautological `if len(results) != len(config.feeds): raise AssertionError` (`check.py:47`)
  - `attempts < 1` re-validated in `fetch_with_retries`, with a literal `1` where config uses `MIN_ATTEMPTS`
- **Speed.** It checks feeds sequentially, so total runtime is the sum of every feed's timeouts and retries. The SPEC doesn't require concurrency.

## 4. Defects

I verified the main ones with a probe server.

**Gated:**
1. **Redirects are reported as unhealthy.** `_KeepErrorStatus.http_response` returns every response unchanged, which bypasses `HTTPRedirectHandler`. In the probe, a 301 to a healthy feed produced `"unhealthy", "HTTP status 301, expected 200"`; ungated reports it as healthy.
2. **A missing output directory crashes after all fetching is done.** The probe got `FileNotFoundError: [Errno 2] No such file or directory: …/nodir/r.json` as a traceback. The exit code is 1 only because of the traceback. Ungated checks this up front with a clear message.
3. **Strict staleness rules.** With `max_age_hours` set, one item without `published` makes the whole feed unhealthy (probe: `"item 0 has no 'published'"`), and naive timestamps are rejected. This is defensible but stricter than the SPEC; ungated skips undated items.
4. **Refuses to run under `python -O`** (`cli.py:29`). The SPEC asks for nothing like this.

**Ungated:**
1. **Config errors and a missing output directory exit with 2.** The SPEC says the exit code is 1 when not everything is healthy. Probe: `missingcfg: 2`.
2. **Naive timestamps are silently treated as UTC** (`parse_timestamp`: `parsed.replace(tzinfo=timezone.utc)`). That's a success-shaped assumption that can mislabel a feed as fresh or stale.
3. **Missing settings silently fall back to defaults** (10s timeout, 3 attempts, 1s backoff). The SPEC has the config set them.

**Both:**
1. **The timeout applies per socket operation, not per feed.** A server that trickles bytes can run past `timeout_seconds`.
2. **A retry delay of 0 is accepted** (`retry_delay_seconds` / `backoff_seconds = 0`), so later attempts don't wait any longer.

## 5. Recommendations

1. **MAGIC001, number-in-string:** flag whitespace-only or digit-only string constants passed to parameters that also accept an int: `indent=`, `json.dumps(indent=…)`, `textwrap.indent` widths, `str.rjust`/`zfill` fill counts. That would have caught `REPORT_INDENT = "  "` (1a).
2. **DEF002, membership-check equivalence:** treat `if k in m: x = m[k] else: x = <literal>` (and `Counter`/`defaultdict` swapped in only to get an implicit default) as the same finding as `m.get(k, v)`, so the rewrite stops the block only when the fallback is actually removed. Also add DEF002 to the test-role exemption in what `shockharness init` writes. In test fixtures a default route or counter is ordinary scaffolding; here the rule forced a letter-only rewrite of legitimate code (1b).
3. **Suppression visibility:** have the hook include every newly added `shockharness: ignore[...]` in its feedback, with the reason, even when the finding is suppressed. The first-draft `getattr` suppression (1c) went unmentioned.
4. **Function-scoped boundaries:** allow, and have the skill encourage, `function = "fetch_once"` / `"_read_items"` on boundary entries, so that `ValueError` in `health.py` doesn't approve every future catch in that file (1d).
5. **Skill wording on boundaries in the SPEC:** "Every I/O boundary the SPEC implies (reading config, network, *writing the output*) needs either a declared boundary that turns the failure into a clear exit, or a stated reason it may crash." The gated build handled every boundary it was blocked on and none of the others (Defect 2).
6. **Skill wording on library control flow:** "Don't restructure a library's control flow (e.g. overriding `HTTPErrorProcessor`) just to avoid catching its exception; declare a boundary for `urllib.error.HTTPError` instead." The override lost redirect handling (Defect 1).
7. **Skill wording against defensive ceremony:** tell the agent not to add guards against `python -O` or tautological `raise AssertionError` checks. Neither came from a block; they look like over-correction to the harness's spirit.
