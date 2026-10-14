"""example-service: a tiny consumer of ShockHarness.

Every value is required and validated once, at load time; nothing falls back
silently and no literal other than 0 or 1 appears in executable code.
"""

from example_service.http import NOT_FOUND, is_missing
from example_service.pages import paginate
from example_service.settings import Settings, load_settings

__all__ = ["NOT_FOUND", "Settings", "is_missing", "load_settings", "paginate"]
