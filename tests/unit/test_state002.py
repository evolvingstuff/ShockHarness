"""STATE002: a shared object published before it is initialized (MetaList, 2026-10-17)."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)

# MetaList's get_encryption_service_with_token, before the fix, and its shape around it.
CODE = """\
_service = None
_other = None


def get_service(dek):
    global _service
    _service = EncryptionService()
    _service.dek = dek
    return _service


def build_first(dek):
    global _other
    service = EncryptionService()
    service.dek = dek
    _other = service
    return _other


def rebound(dek):
    global _service
    _service = EncryptionService()
    _service = None
    return _service


def factory(dek):
    global _service
    _service = make_service()
    _service.dek = dek


class Cache:
    def __init__(self):
        self.client = Client()
        self.client.timeout = 3

    def refresh(self, token):
        self.client = Client()
        self.client.token = token
"""


def state002(config: EffectiveConfig, path: str) -> list[tuple[int, str]]:
    result = analyze_text(path, "python", CODE, config, OPTIONS)
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == "STATE002"]


def test_a_global_or_self_attribute_published_before_its_fields_are_set(
    strict_config: EffectiveConfig,
) -> None:
    # get_service (7) and Cache.refresh (39); build_first publishes last; rebound rebinds;
    # factory's callee is not a class; __init__ builds before anyone can read it.
    assert state002(strict_config, "app/service.py") == [(7, "review"), (39, "review")]


def test_severity_and_roles(make_config: Callable[[str], EffectiveConfig]) -> None:
    raised = make_config('[tool.shockharness.rules.module_state]\nstate002_severity = "warning"\n')
    assert state002(raised, "app/service.py") == [(7, "warning"), (39, "warning")]
    default = make_config("")
    assert state002(default, "tests/test_service.py") == []  # roles: production
