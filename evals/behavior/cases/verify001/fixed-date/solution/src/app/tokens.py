"""Token expiry."""


def is_expired(expires_at: float, now: float) -> bool:
    """Whether a token expiring at ``expires_at`` has expired at ``now`` (seconds since the
    epoch); the caller reads the clock, so the rule can be tested at any instant."""
    return now >= expires_at
