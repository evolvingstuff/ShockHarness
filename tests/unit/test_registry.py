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


def test_implemented_rules_are_exactly_the_h2_part_1_set() -> None:
    assert {r.rule_id for r in registry.implemented_rules()} == {
        "MAGIC001",
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
        "CPLX006",
        "SUPP001",
        "SUPP002",
        "VERIFY001",
        "VERIFY002",
        "VERIFY004",
    }
    assert {r.rule_id for r in registry.RULES if not r.implemented} == {"MAGIC002", "VERIFY003"}


def test_verification_rules_need_a_base_revision_and_are_policy_integrity() -> None:
    assert [r.rule_id for r in registry.base_revision_rules()] == [
        "VERIFY001",
        "VERIFY002",
        "VERIFY004",
    ]
    for rule in registry.RULES:
        assert rule.family in registry.FAMILY_CATEGORIES, rule.rule_id
        expected = (
            registry.CATEGORY_POLICY
            if rule.family == registry.VERIFICATION_FAMILY
            else registry.FAMILY_CATEGORIES[rule.family]
        )
        assert registry.category_of(rule.rule_id) == expected
        if rule.family == registry.VERIFICATION_FAMILY:
            assert rule.config_section == registry.VERIFICATION_SECTION
            # Spec 21.1 decision 9: new rules ship at warning until precision is measured.
            assert rule.default_severity == registry.SEVERITY_WARNING
            assert registry.needs_base_revision(rule)
        else:
            assert not registry.needs_base_revision(rule)


def test_complexity_rules_are_warnings_with_the_complexity_section() -> None:
    for rule in registry.RULES:
        if rule.family == "complexity":
            assert rule.default_severity == registry.SEVERITY_WARNING, rule.rule_id
            assert rule.config_section == "complexity", rule.rule_id
            assert "never fails" in rule.limitations.lower(), rule.rule_id


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
