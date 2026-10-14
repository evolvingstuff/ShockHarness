"""DEF006: environment-variable fallbacks, however os is imported."""

import os
import os as operating_system
from os import environ, getenv

PORT = os.getenv("PORT", "8080")
HOST = os.environ.get("HOST", "localhost")
MODE = os.getenv("MODE", default="dev")
DEBUG = os.environ.get("DEBUG") or "0"
REGION = os.environ["REGION"] if "REGION" in os.environ else "eu"
TOKEN = os.getenv("TOKEN")
SECRET = os.environ.get("SECRET")
SEEDED = os.environ.setdefault("SEED", "1")
ALIASED = operating_system.getenv("ALIASED", "x")
FROM_IMPORT = environ.get("FROM_IMPORT", "y")
GETENV = getenv("GETENV", "z")
TERNARY = getenv("TERNARY") if getenv("TERNARY") is not None else "t"

REQUIRED = os.environ["REQUIRED"]
checked = os.getenv("CHECKED")
if checked is None:
    raise RuntimeError("CHECKED is required")
