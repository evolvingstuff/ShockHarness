"""feedcheck: check whether a set of JSON feeds is healthy and write a report."""

from feedcheck.checker import check_feed, check_feeds, FeedResult
from feedcheck.config import Config, ConfigError, FeedConfig, load_config

__all__ = [
    "Config",
    "ConfigError",
    "FeedConfig",
    "FeedResult",
    "check_feed",
    "check_feeds",
    "load_config",
]
