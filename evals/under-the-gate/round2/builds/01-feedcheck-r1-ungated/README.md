# feedcheck

Checks whether a set of JSON feeds is healthy and writes a JSON report.
Python 3.11+, standard library only.

```sh
python -m feedcheck --config feeds.toml --output report.json
# or, after `pip install .`:
feedcheck --config feeds.toml --output report.json
```

See `feeds.example.toml` for the config format. Unknown keys are rejected so typos fail loudly.

## Statuses

| status        | meaning |
|---------------|---------|
| `healthy`     | 200 with a JSON object whose `items` is a list (and fresh enough, if `max_age_hours` is set) |
| `unhealthy`   | the server answered, but not like that: non-200 (including 5xx after all attempts), invalid JSON, missing/non-list `items`, or an item whose `published` is not ISO 8601 |
| `stale`       | `max_age_hours` is set and the newest `published` is older than that, or no item has a `published` date |
| `unreachable` | no answer after all attempts (connection refused, timeout, connection dropped) |

Timestamps without a timezone are treated as UTC. Only 5xx responses and no-answer
failures are retried; other responses are final.

## Exit codes

- `0`: every feed is healthy
- `1`: at least one feed is not healthy
- `2`: the config is missing, unreadable or invalid (nothing is fetched), or the report can't be written

## Report

```json
{
  "checked_at": "2026-10-17T10:00:00+00:00",
  "all_healthy": false,
  "summary": {"total": 2, "healthy": 1, "unhealthy": 0, "stale": 1, "unreachable": 0},
  "feeds": [
    {"name": "news", "url": "...", "status": "stale",
     "reason": "newest item is 30.2h old (max 24h)", "items": 12,
     "http_status": 200, "attempts": 1, "duration_seconds": 0.143}
  ]
}
```

`items` is `null` when the response didn't contain an items list. `duration_seconds`
includes retries and backoff waits.

## Tests

```sh
python -m unittest discover -s tests -t .
```

The tests serve fake feeds from a local `http.server` and need no network access.
