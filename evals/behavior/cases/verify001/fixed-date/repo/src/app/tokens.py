"""Token expiry."""

import time


def is_expired(expires_at: float) -> bool:
    return time.time() >= expires_at
