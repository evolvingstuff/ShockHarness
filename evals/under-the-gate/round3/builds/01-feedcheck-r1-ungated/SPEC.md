# feedcheck: a feed health checker (Python)

Build a command-line tool, `feedcheck`, that checks whether a set of JSON feeds
is healthy and writes a report.

## Behavior

- `feedcheck --config feeds.toml --output report.json`
- The config file lists feeds, each with a `name` and a `url`. It also sets how
  long to wait for a feed before giving up, and how many attempts to make for a
  feed whose server answers 5xx or does not answer at all. Attempts after the
  first wait a little longer each time.
- A feed is healthy when it answers 200 with a JSON object whose `items` is a
  list. Record `healthy`, `unhealthy` (with the reason) or `unreachable` per feed.
- A feed may have an optional `max_age_hours`. When it is set, a feed whose newest
  item (`published`, ISO 8601) is older than that is `stale`.
- The report lists every feed with its status, the number of items and the time
  the check took. The exit code is 0 when every feed is healthy and 1 otherwise.
- A config file that is missing, unreadable or invalid stops the tool with a
  clear message, before any feed is fetched.

## Constraints

- Python 3.11+, standard library only (`urllib`, `json`, `tomllib`, `argparse`).
- Include tests (`unittest`) that run without network access: serve fake feeds
  from a local `http.server` in the tests.
