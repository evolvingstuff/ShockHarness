# feedcheck

Checks whether a set of JSON feeds is healthy and writes a JSON report.

    python -m feedcheck --config feeds.toml --output report.json
    # or, after `pip install .`:
    feedcheck --config feeds.toml --output report.json

See `feeds.example.toml` for the config format. Settings:

- `timeout_seconds` (default 10): how long one attempt may wait for the server.
- `attempts` (default 3): total tries for a feed that answers 5xx or doesn't answer.
- `backoff_seconds` (default 1): delay before the first retry; each later retry waits twice as long.
- `[[feeds]]`: `name`, `url` (http/https), optional `max_age_hours`.

Statuses:

- `healthy`: HTTP 200, a JSON object whose `items` is a list, and (if
  `max_age_hours` is set) a newest `published` item no older than that.
- `unhealthy`: any other answer (non-200, bad JSON, no `items` list, 5xx on
  every attempt, an unparseable `published`, or `max_age_hours` set but no
  item carries a `published` timestamp). `reason` explains.
- `unreachable`: no answer on any attempt (refused, timed out, dropped).
- `stale`: `max_age_hours` is set and the newest item is older, or there are no items.

Naive `published` timestamps are read as UTC. Feeds are checked concurrently.

Exit codes: `0` every feed healthy, `1` at least one is not, `2` bad config,
unwritable output, or bad arguments (nothing is fetched in that case).

Run the tests (no network needed): `python -m unittest`
