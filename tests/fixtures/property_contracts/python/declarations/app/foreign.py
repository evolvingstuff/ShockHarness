from app.other import requires


def foreign(text):
    requires(text, "not_in_the_catalog")
    return text


def caller(raw):
    return foreign(raw)
