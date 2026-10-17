# feedcheck

Checks whether a set of JSON feeds is healthy and writes a JSON report.

    python -m feedcheck --config feeds.toml --output report.json
    # or, after `pip install .`:  feedcheck --config feeds.toml --output report.json

See `examples/feeds.toml` for the config format. All keys except a feed's
`max_age_hours` are required, and unknown keys are rejected.

Each feed gets one of these statuses:

- `healthy`: HTTP 200 with a JSON object whose `items` is a list (and, if `max_age_hours` is set, the newest `published` is recent enough)
- `unhealthy`: any other answer, with a `reason`
- `unreachable`: no answer (connection refused, timeout, broken response) after every attempt
- `stale`: the newest item is older than `max_age_hours`, or there are no items

Only 5xx answers and no answer are retried.

Exit status: 0 when every feed is healthy, 1 otherwise, 2 for a missing,
unreadable or invalid config. With a bad config the tool stops before it
fetches any feed.

Tests (no network needed): `python -m unittest`
