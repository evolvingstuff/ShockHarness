def none_fallback(path):
    try:
        return read(path)
    except OSError:
        return None


def implicit_none(path):
    try:
        return read(path)
    except OSError:
        return


def false_fallback(path):
    try:
        return read(path)
    except OSError:
        return False


def zero_fallback(path):
    try:
        return read(path)
    except OSError:
        return 0


def empty_containers(path):
    try:
        return read(path)
    except OSError:
        return {"items": [], "count": 0}


def negative_fallback(path):
    try:
        return read(path)
    except OSError:
        return -1


def logged_fallback(path):
    try:
        return read(path)
    except OSError as exc:
        print(exc)
        return []


def not_a_literal(path, default):
    try:
        return read(path)
    except OSError:
        return default


def computed(path):
    try:
        return read(path)
    except OSError:
        return (None, status())
