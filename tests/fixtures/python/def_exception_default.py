"""DEF005: handlers that return a default. Literal returns are exact; traces are approximate."""

DEFAULT_ROWS = []
LIMIT: int = 100
computed = compute()


def empty_rows():
    return []


def documented():
    """Return the fallback."""
    return None


def literal(path):
    try:
        return read(path)
    except OSError:
        return []


def module_constant(path):
    try:
        return read(path)
    except OSError:
        return DEFAULT_ROWS


def annotated_constant(path):
    try:
        return read(path)
    except OSError:
        return LIMIT


def helper(path):
    try:
        return read(path)
    except OSError as exc:
        print(exc)
        return empty_rows()


def helper_with_docstring(path):
    try:
        return read(path)
    except OSError:
        return documented()


def fabricated(path):
    try:
        return read(path)
    except OSError:
        return dict()


def not_traced(path, default):
    try:
        return read(path)
    except OSError:
        return default


def not_a_constant(path):
    try:
        return read(path)
    except OSError:
        return computed


def imported_constant(path):
    try:
        return read(path)
    except OSError:
        return EXIT_FAILURE
