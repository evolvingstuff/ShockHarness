from shockharness.schema import validate_shape


def issues_for(raw: object) -> list[str]:
    return [issue.render() for issue in validate_shape(raw)]


def test_empty_table_is_valid() -> None:
    assert issues_for({}) == []


def test_unknown_top_level_key_names_known_keys() -> None:
    messages = issues_for({"inlcude": ["*.py"]})
    assert len(messages) == 1
    assert messages[0].startswith("inlcude: unknown key")
    assert "include" in messages[0]


def test_nested_unknown_key_has_full_path() -> None:
    messages = issues_for({"rules": {"magic_numbers": {"allow_values": [0]}}})
    assert messages == [
        "rules.magic_numbers.allow_values: unknown key (known keys: allow_unary_negative_one, "
        "allowed_values, configuration_files, enabled, exclude_configuration_files, "
        "fail_on_unknown, named_constant_definitions, severity)"
    ]


def test_type_errors_name_the_actual_type() -> None:
    messages = issues_for({"include": "src/**", "parse_errors": True, "follow_symlinks": "yes"})
    assert "include: expected a list, got string" in messages
    assert "parse_errors: must be one of 'fail', 'warn', got True" in messages
    assert "follow_symlinks: expected true or false, got string" in messages


def test_list_items_are_indexed() -> None:
    messages = issues_for({"include": ["ok.py", 3, ""]})
    assert "include[1]: expected a string, got integer" in messages
    assert "include[2]: must not be empty" in messages


def test_booleans_are_not_numbers() -> None:
    messages = issues_for({"rules": {"magic_numbers": {"allowed_values": [0, True]}}})
    assert messages == ["rules.magic_numbers.allowed_values[1]: expected a number, got boolean"]


def test_override_requires_all_keys() -> None:
    messages = issues_for({"overrides": [{"paths": ["tests/**"]}]})
    assert "overrides[0].disable: required key is missing" in messages
    assert "overrides[0].reason: required key is missing" in messages


def test_boundary_language_enum() -> None:
    raw = {
        "rules": {
            "exceptions": {
                "boundaries": [
                    {"path": "x/**", "language": "rust", "exception": "E", "reason": "r"},
                ]
            }
        }
    }
    messages = issues_for(raw)
    assert messages == [
        "rules.exceptions.boundaries[0].language: must be one of 'python', 'javascript', "
        "'typescript', got 'rust'"
    ]


def test_integer_minimums() -> None:
    messages = issues_for({"complexity": {"cognitive_warn": 0, "cyclomatic_warn": 2.5}})
    assert "complexity.cognitive_warn: must be at least 1, got 0" in messages
    assert "complexity.cyclomatic_warn: expected an integer, got float" in messages


def test_unknown_profile() -> None:
    assert issues_for({"profile": "lenient"}) == [
        "profile: must be one of 'strict', 'recommended', 'minimal', got 'lenient'"
    ]


def test_section_severity_enum() -> None:
    assert issues_for({"rules": {"defaults": {"severity": "warn"}}}) == [
        "rules.defaults.severity: must be one of 'error', 'review', got 'warn'"
    ]
