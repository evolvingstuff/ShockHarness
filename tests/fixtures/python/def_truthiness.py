"""DEF003: 'x or v' outside Boolean tests. Boolean logic with 'or' is not a fallback."""


def constant_fallbacks(items, name, count):
    items = items or []
    label = name or "anonymous"
    total = count or 0
    return render(items or (), label, total)


def alternatives(primary, secondary, tertiary):
    chosen = primary or secondary
    return primary or secondary or tertiary


def chains(a, b):
    value = a or b or "z"
    return value


def boolean_logic(a, b, flag):
    if a or b:
        return True
    while a or flag:
        a = step(a)
    assert a or b, "one is needed"
    ok = a == b or flag
    done = not (a or b)
    found = a in b or b in a
    both = a and b
    return ok, done, found, both


def ternary_truthiness(x, y):
    first = x if x else "empty"
    second = "empty" if not y else y
    return first, second


def expression_position(a, b):
    call(a or b)
    return [a or 0 for a in b]
