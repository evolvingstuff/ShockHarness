from app.contracts import produces, requires
from app.generic import considered, head, ident, rebinding, without_normalized


def deliver(text):
    requires(text, "redacted")
    return text


def fit(series):
    requires(series, "normalized")
    return series


def through_head(raw, other):
    clean = produces(raw, "redacted")
    deliver(head(clean, 3))
    deliver(head(other, 3))


def through_considered(raw):
    deliver(considered(produces(raw, "redacted"), 3))


def keyword(raw):
    deliver(head(n=3, x=produces(raw, "redacted")))


def except_one(raw):
    both = produces(raw, "redacted", "normalized")
    deliver(without_normalized(both))
    fit(without_normalized(both))


def not_parametric(raw):
    clean = produces(raw, "redacted")
    deliver(ident(clean))
    deliver(rebinding(clean))
