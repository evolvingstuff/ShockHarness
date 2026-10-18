import json

from app import cloud
from app.cloud import send_messages
from app.privacy import evaluate


def cleared(raw):
    return send_messages(evaluate(raw), "small")


def uncleared(raw):
    return cloud.send_messages(raw, "small")


def by_keyword(raw):
    return send_messages(model="small", messages=raw)


def by_keyword_cleared(raw):
    return send_messages(model="small", messages=evaluate(raw))


def library(raw):
    json.dumps(evaluate(raw))
    json.dumps(raw)
    return json.dumps(obj=raw)


def method_on_value(raw):
    return send_messages(raw.copy(), "small")
