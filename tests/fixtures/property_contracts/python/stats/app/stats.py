from app.contracts import produces, preserves, requires


def normalize(x):
    requires(x, "numeric")
    return produces(center(x) / x.std(), "normalized", "numeric")


def center(x):
    requires(x, "numeric")
    return preserves(x - x.mean(), x)


def fit(x):
    requires(x, "normalized", "numeric")
    return train(x)


def pipeline(raw):
    requires(raw, "numeric")
    return fit(normalize(raw))


def shortcut(raw):
    requires(raw, "numeric")
    return fit(raw)


def shifted(raw):
    requires(raw, "numeric")
    x = normalize(raw) + 1
    return fit(x)


def through_registry(raw, ops):
    requires(raw, "numeric")
    x = ops["normalize"](raw)
    return fit(x)
