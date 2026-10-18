from app.contracts import preserves, preserves_except, requires


def head(x, n):
    return preserves(x[:n], x)


def considered(x, n):
    requires(x)
    return preserves(x[:n], x)


def without_normalized(x):
    return preserves_except(list(x), x, "normalized")


def ident(x):
    return x


def rebinding(x):
    x = x[:1]
    return preserves(x, x)
