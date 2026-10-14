import pytest

from shockharness.rules import registry

SPEC_RULE_IDS = {
    "MAGIC001",
    "MAGIC002",
    "EXC001",
    "EXC002",
    "EXC003",
    "DEF001",
    "DEF002",
    "DEF003",
    "DEF004",
    "DEF005",
    "DEF006",
    "CPLX001",
    "CPLX002",
    "CPLX003",
    "CPLX004",
    "CPLX005",
}


def test_every_specified_rule_is_registered() -> None:
    assert set(registry.rule_ids()) >= SPEC_RULE_IDS


def test_rule_ids_are_unique() -> None:
    ids = registry.rule_ids()
    assert len(ids) == len(set(ids))


def test_severities_are_valid() -> None:
    for rule in registry.RULES:
        assert rule.default_severity in registry.SEVERITIES, rule.rule_id


def test_implemented_rules_are_exactly_the_milestone_c_set() -> None:
    assert {r.rule_id for r in registry.implemented_rules()} == {
        "MAGIC001",
        "EXC001",
        "EXC002",
        "EXC003",
        "SUPP001",
        "SUPP002",
    }


def test_implemented_rules_have_full_metadata() -> None:
    for rule in registry.implemented_rules():
        assert rule.version != "0"
        assert rule.rationale
        assert rule.guarantees
        assert rule.limitations
        assert rule.remediation
        assert rule.compliant_example


def test_unknown_rule_lookup_is_loud() -> None:
    assert not registry.is_known_rule("NOPE")
    with pytest.raises(KeyError):
        registry.get_rule("NOPE")
