"""DEF002/DEF004 leave lazy initialization alone: a field filled on first use with a value
built for it is not a fallback for missing data."""

from collections.abc import Callable

import pytest

from shockharness.analysis import FileResult

Analyze = Callable[[str, str], FileResult]
DEFAULTS = ("DEF002", "DEF004")


def defaults(result: FileResult) -> list[tuple[str, int]]:
    return sorted((f.rule_id, f.span.line) for f in result.findings if f.rule_id in DEFAULTS)


JAVASCRIPT_LAZY = """class Channel {}
let channel;
export function getChannel() {
  return channel ??= new Channel();
}
export class Holder {
  #channels;
  channels() {
    return this.#channels ??= new Map();
  }
  pending() {
    this.queue ??= [];
    return this.queue;
  }
  registry() {
    return this.byName ??= {};
  }
  later() {
    return this.timer ??= setTimeout(() => {}, 0);
  }
}
"""

JAVASCRIPT_FALLBACKS = """class Channel {}
let channel;
export function shadowed() {
  let channel;
  return channel ??= new Channel();
}
export function parameter(cache) {
  cache ??= new Map();
  return cache;
}
export class Settings {
  read(options) {
    this.timeout ??= 30;
    options.tags ??= [];
    this.limits ??= { pages: 2 };
    return options;
  }
}
"""


@pytest.mark.parametrize("language", ["javascript", "typescript"])
def test_javascript_fields_and_module_variables_filled_on_first_use(
    analyze: Analyze, language: str
) -> None:
    assert defaults(analyze(JAVASCRIPT_LAZY, language)) == []


def test_javascript_fallbacks_stay_reported(analyze: Analyze) -> None:
    # A local shadowing the module variable, a parameter, a constant into a field, a
    # parameter's property, and a non-empty object are all still fallbacks.
    assert defaults(analyze(JAVASCRIPT_FALLBACKS, "javascript")) == [
        ("DEF002", 13),
        ("DEF002", 14),
        ("DEF002", 15),
        ("DEF004", 5),
        ("DEF004", 8),
    ]


CSHARP = """public class Channel {}
public class Holder
{
    private Channel _channel;
    private Channel _other;
    private int? _count;
    public Channel Get() => _channel ??= new Channel();
    public Channel This() => this._other ??= new();
    public Channel Shadowed(Channel _channel) => _channel ??= new Channel();
    public int Count() => _count ??= 0;
    public Channel Local()
    {
        Channel made = null;
        return made ??= new Channel();
    }
}
"""


def test_csharp_fields_filled_on_first_use_and_the_fallbacks(analyze: Analyze) -> None:
    # Lines 7 and 8 fill fields; 9 is a parameter, 10 a constant and 14 a local.
    assert defaults(analyze(CSHARP, "csharp")) == [("DEF004", 9), ("DEF004", 10), ("DEF004", 14)]


PYTHON = """class Channel:
    pass


class Holder:
    def __init__(self, timeout=None):
        self._channel = None
        self._peers = None
        self.timeout = timeout

    def channel(self):
        self._channel = self._channel if self._channel is not None else Channel()
        return self._channel

    def peers(self):
        self._peers = {} if self._peers is None else self._peers
        return self._peers

    def fallbacks(self, limit):
        self.timeout = self.timeout if self.timeout is not None else 30
        limit = limit if limit is not None else Channel()
        self._peers = self._channel if self._channel is not None else Channel()
        return limit
"""


def test_python_attributes_filled_on_first_use_and_the_fallbacks(analyze: Analyze) -> None:
    # Lines 12 and 16 fill attributes; 20 is a constant, 21 a local, 22 another attribute.
    assert defaults(analyze(PYTHON, "python")) == [("DEF004", 20), ("DEF004", 21), ("DEF004", 22)]
