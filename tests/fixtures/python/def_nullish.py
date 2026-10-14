"""DEF004: 'x if x is not None else v' and the inverted form; propagation is not flagged."""


def clear_substitutions(limit, rows, name):
    limit = limit if limit is not None else 100
    rows = [] if rows is None else rows
    label = name if name != None else "anon"  # noqa: E711
    return limit, rows, label


def computed_fallback(value, other):
    return value if value is not None else other


def propagation(node, maybe):
    text = None if node is None else node.strip()
    upper = maybe.upper() if maybe is not None else None
    return text, upper


def a_choice_not_a_fallback(flag):
    return "on" if flag is not None else "off"


def spelled_as_statements(value):
    if value is None:
        value = 0
    return value
