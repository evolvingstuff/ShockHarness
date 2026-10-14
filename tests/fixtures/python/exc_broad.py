import logging

logger = logging.getLogger(__name__)


def load(raw):
    try:
        return parse(raw)
    except Exception:
        logger.error("failed to parse")


def load_base(raw):
    try:
        return parse(raw)
    except BaseException as exc:
        raise RuntimeError("wrapped") from exc


def load_builtins_alias(raw):
    import builtins

    try:
        return parse(raw)
    except builtins.Exception as exc:
        raise
