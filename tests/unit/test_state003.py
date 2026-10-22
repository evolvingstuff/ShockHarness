"""STATE003: state read outside the lock that guards its writes (MetaList, 2026-10-17)."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)

# MetaList's EncryptedTextStream before its fix, and the shapes around it.
CODE = """\
import threading

_state_lock = threading.Lock()
_token = None


def set_token(token):
    global _token
    with _state_lock:
        _token = token


def current(token):
    if _token == token:
        return True
    with _state_lock:
        return _token == token


class Stream:
    def __init__(self, sink):
        self._sink = sink
        self._lock = threading.Lock()
        self._closed = False
        self._key = b"k"
        if self._closed:
            raise RuntimeError("never")

    def write(self, message):
        if self._closed:
            raise RuntimeError("closed")
        data = encrypt(message, self._key)
        with self._lock:
            self._sink.write(data)

    def write_safely(self, message):
        with self._lock:
            if self._closed:
                raise RuntimeError("closed")
            self._sink.write(encrypt(message, self._key))

    def close(self):
        with self._lock:
            self._closed = True
            self._key = b""

    def _flush_locked(self):
        if self._closed:
            return

    def flush(self):
        with self._lock:
            self._helper()

    def _helper(self):
        if self._closed:
            return

    def describe(self):
        logger.info("state", closed=self._closed)

    def sink(self):
        return encrypt("x", self._sink)


def encrypt(message, key):
    return message
"""


def state003(config: EffectiveConfig, path: str, code: str = CODE) -> list[tuple[int, str]]:
    result = analyze_text(path, "python", code, config, OPTIONS)
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == "STATE003"]


def test_a_check_and_a_value_taken_before_the_lock(strict_config: EffectiveConfig) -> None:
    # current() checks _token before taking _state_lock (14); Stream.write checks _closed
    # (30) and passes _key on (32) before taking _lock. write_safely holds it; __init__
    # builds; _flush_locked is named for a held lock and _helper is only called under it;
    # describe only logs; _sink is never written under the lock.
    assert state003(strict_config, "app/stream.py") == [
        (14, "review"),
        (30, "review"),
        (32, "review"),
    ]


def test_the_message_names_the_lock_and_the_writer(strict_config: EffectiveConfig) -> None:
    result = analyze_text("app/stream.py", "python", CODE, strict_config, OPTIONS)
    messages = [f.message for f in result.findings if f.rule_id == "STATE003" and f.span.line == 30]
    assert messages == [
        "self._closed is read outside self._lock in Stream.write, while close (line 44) writes "
        "it holding the lock: it can change between this read and what follows"
    ]


def test_a_lock_free_fast_path_takes_a_reasoned_suppression(strict_config: EffectiveConfig) -> None:
    code = CODE.replace(
        "    if _token == token:\n",
        "    if _token == token:  # shockharness: ignore[STATE003]"
        ' reason="re-checked under the lock below"\n',
    )
    result = analyze_text("app/stream.py", "python", code, strict_config, OPTIONS)
    found = [
        (f.span.line, f.suppression is not None) for f in result.findings if f.rule_id == "STATE003"
    ]
    assert found == [(14, True), (30, False), (32, False)]


def test_severity_roles_and_languages(make_config: Callable[[str], EffectiveConfig]) -> None:
    raised = make_config('[tool.shockharness.rules.module_state]\nstate003_severity = "warning"\n')
    assert [s for _line, s in state003(raised, "app/stream.py")] == ["warning"] * 3
    default = make_config("")
    assert state003(default, "tests/test_stream.py") == []  # roles: production
    result = analyze_text("app/stream.js", "javascript", "export const x = 0;\n", default, OPTIONS)
    assert "STATE003" not in result.rules_applied
