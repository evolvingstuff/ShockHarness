"""feedcheck: check the health of a set of JSON feeds and write a report."""
import argparse
import json
import socket
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_TIMEOUT = 10.0
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 0.5


class ConfigError(Exception):
    pass


def _number(table, key, default, kind, minimum):
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or (kind is int and not isinstance(value, int)) or value < minimum:
        raise ConfigError(f"'{key}' must be a number >= {minimum}, got {value!r}")
    return value


def load_config(path):
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e.strerror or e}")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"invalid config file {path}: {e}")

    cfg = {
        "timeout": _number(data, "timeout", DEFAULT_TIMEOUT, float, 0.001),
        "attempts": _number(data, "attempts", DEFAULT_ATTEMPTS, int, 1),
        "backoff": _number(data, "backoff", DEFAULT_BACKOFF, float, 0),
    }
    feeds = data.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        raise ConfigError("config must define at least one [[feeds]] entry")
    seen = set()
    cfg["feeds"] = []
    for i, feed in enumerate(feeds, 1):
        if not isinstance(feed, dict):
            raise ConfigError(f"feed #{i} must be a table")
        for key in ("name", "url"):
            if not isinstance(feed.get(key), str) or not feed[key].strip():
                raise ConfigError(f"feed #{i} needs a non-empty string '{key}'")
        if not feed["url"].startswith(("http://", "https://")):
            raise ConfigError(f"feed '{feed['name']}': url must be http(s)")
        if feed["name"] in seen:
            raise ConfigError(f"duplicate feed name '{feed['name']}'")
        seen.add(feed["name"])
        entry = {"name": feed["name"], "url": feed["url"], "max_age_hours": None}
        if "max_age_hours" in feed:
            entry["max_age_hours"] = _number(feed, "max_age_hours", None, float, 0)
        cfg["feeds"].append(entry)
    return cfg


def _fetch(url, timeout):
    """Return (status, body) or raise OSError-like on no answer."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except OSError:
            body = b""
        return e.code, body


def _parse_time(text):
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _evaluate(body, max_age_hours, now):
    """Return (status, reason, item_count) for a 200 response body."""
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return "unhealthy", "response is not valid JSON", None
    if not isinstance(doc, dict):
        return "unhealthy", "JSON document is not an object", None
    items = doc.get("items")
    if not isinstance(items, list):
        return "unhealthy", "'items' is missing or not a list", None
    count = len(items)
    if max_age_hours is None:
        return "healthy", None, count
    newest = None
    for item in items:
        pub = item.get("published") if isinstance(item, dict) else None
        if not isinstance(pub, str):
            return "unhealthy", "item without a 'published' string", count
        try:
            t = _parse_time(pub)
        except ValueError:
            return "unhealthy", f"unparseable 'published': {pub!r}", count
        if newest is None or t > newest:
            newest = t
    if newest is None:
        return "stale", "feed has no items", count
    if now - newest > timedelta(hours=max_age_hours):
        return "stale", f"newest item {newest.isoformat()} is older than {max_age_hours:g}h", count
    return "healthy", None, count


def check_feed(feed, cfg, sleep=time.sleep, now=None):
    start = time.monotonic()
    status, reason, count = "unreachable", "no attempts made", None
    for attempt in range(1, cfg["attempts"] + 1):
        if attempt > 1:
            sleep(cfg["backoff"] * 2 ** (attempt - 2))
        try:
            code, body = _fetch(feed["url"], cfg["timeout"])
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError,
                ValueError, http_errors()) as e:
            err = getattr(e, "reason", e)
            status, reason, count = "unreachable", f"{type(err).__name__}: {err}", None
            continue
        if code >= 500:
            status, reason, count = "unhealthy", f"HTTP {code}", None
            continue
        if code != 200:
            status, reason, count = "unhealthy", f"HTTP {code}", None
        else:
            status, reason, count = _evaluate(
                body, feed["max_age_hours"], now or datetime.now(timezone.utc))
        break
    result = {
        "name": feed["name"], "url": feed["url"], "status": status,
        "items": count, "attempts": attempt,
        "duration_seconds": round(time.monotonic() - start, 3),
    }
    if reason:
        result["reason"] = reason
    return result


def http_errors():
    import http.client
    return http.client.HTTPException


def run(cfg, sleep=time.sleep):
    results = [check_feed(f, cfg, sleep) for f in cfg["feeds"]]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "healthy": all(r["status"] == "healthy" for r in results),
        "feeds": results,
    }


def main(argv=None):
    p = argparse.ArgumentParser(prog="feedcheck", description="Check JSON feed health.")
    p.add_argument("--config", required=True, help="TOML config file")
    p.add_argument("--output", required=True, help="JSON report file to write")
    args = p.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"feedcheck: {e}", file=sys.stderr)
        return 2
    report = run(cfg)
    try:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"feedcheck: cannot write report {args.output}: {e.strerror or e}", file=sys.stderr)
        return 2
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
