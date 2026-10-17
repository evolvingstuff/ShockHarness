# feedcheck

Checks whether a set of JSON feeds is healthy and writes a JSON report.

    python3 -m feedcheck --config feeds.toml --output report.json
    # or, after `pip install .`:
    feedcheck --config feeds.toml --output report.json

## Config

```toml
timeout_seconds = 10    # how long to wait for a feed (default 10)
attempts = 3            # attempts for 5xx / no answer (default 3)
backoff_seconds = 0.5   # wait before retry n is backoff * 2^(n-2) (default 0.5)

[[feeds]]
name = "news"
url = "https://example.com/news.json"
max_age_hours = 24      # optional
```

## Statuses

- `healthy`: HTTP 200 with a JSON object whose `items` is a list (and, if
  `max_age_hours` is set, the newest item's `published` is recent enough).
- `unhealthy`: any other answer, including a server still answering 5xx after
  every attempt, or (with `max_age_hours`) an item without a valid ISO 8601
  `published`. The reason is in the report.
- `unreachable`: no answer (connection failure or timeout) after every attempt.
- `stale`: `max_age_hours` is set and the newest item is older than that, or
  the feed has no items.

Timestamps without a timezone are taken as UTC.

Exit codes: 0 if every feed is healthy, 1 otherwise, 2 for a bad config file
(nothing is fetched) or an unwritable report.

## Tests

    python3 -m unittest discover -s tests -t .
