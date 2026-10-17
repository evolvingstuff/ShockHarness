from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, analyze_file, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.discovery import DiscoveredFile


def test_override_disables_rule_with_origin(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[[tool.shockharness.overrides]]\n"
        'paths = ["tests/**"]\ndisable = ["MAGIC001"]\nreason = "fixtures encode literals"\n'
    )
    inside = analyze_text(
        "tests/t.py",
        "python",
        "x = 42\n\n\ndef test_x():\n    assert x\n",
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    outside = analyze_text(
        "src/t.py", "python", "x = 42\n", config, AnalysisOptions(True, CACHE_CONFIGURED)
    )
    assert inside.findings == ()
    assert [(d.rule_id, d.reason, d.origin) for d in inside.rules_disabled] == [
        ("MAGIC001", "fixtures encode literals", "overrides[0]")
    ]
    assert len(outside.findings) == 1
    assert outside.rules_disabled == ()


def test_configuration_files_are_exempt_and_recorded(strict_config: EffectiveConfig) -> None:
    result = analyze_text(
        "web/vite.config.js",
        "javascript",
        "export default { port: 3000 };\n",
        strict_config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert result.findings == ()
    (disable,) = result.rules_disabled
    assert disable.rule_id == "MAGIC001"
    assert disable.origin == "configuration_file"
    assert "*.config.js" in disable.reason
    plain = analyze_text(
        "web/server.js",
        "javascript",
        "const port = 3000;\n",
        strict_config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert len(plain.findings) == 1


def test_configuration_file_exemption_can_be_turned_off(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nexclude_configuration_files = false\n"
    )
    result = analyze_text(
        "vite.config.js",
        "javascript",
        "export default { port: 3000 };\n",
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert len(result.findings) == 1


def test_parse_error_file_has_no_findings_and_explicit_status(
    strict_config: EffectiveConfig,
) -> None:
    result = analyze_text(
        "bad.py", "python", "def broken(:\n", strict_config, AnalysisOptions(True, CACHE_CONFIGURED)
    )
    assert result.status == "parse_error"
    assert result.failed
    assert result.findings == ()
    assert result.rules_applied == ()
    assert result.error is not None and result.error.startswith("SyntaxError")


def test_undecodable_file(tmp_path: Path, strict_config: EffectiveConfig) -> None:
    bad = tmp_path / "latin1.py"
    bad.write_bytes(b"x = 'caf\xe9'\n")
    result = analyze_file(
        DiscoveredFile(bad, "latin1.py", "python"),
        strict_config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert result.status == "decode_error"
    assert result.failed
    assert result.error is not None and "UTF-8" in result.error


def test_unreadable_file(tmp_path: Path, strict_config: EffectiveConfig) -> None:
    missing = tmp_path / "gone.py"
    result = analyze_file(
        DiscoveredFile(missing, "gone.py", "python"),
        strict_config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert result.status == "read_error"
    assert result.failed


def test_bom_is_tolerated(tmp_path: Path, strict_config: EffectiveConfig) -> None:
    path = tmp_path / "bom.py"
    path.write_bytes(b"\xef\xbb\xbfx = 7\n")
    result = analyze_file(
        DiscoveredFile(path, "bom.py", "python"),
        strict_config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert result.status == "analyzed"
    assert [(f.span.line, f.span.column) for f in result.findings] == [(1, 5)]


def test_line_count_is_recorded(strict_config: EffectiveConfig) -> None:
    result = analyze_text(
        "t.py", "python", "a = 1\nb = 1\n", strict_config, AnalysisOptions(True, CACHE_CONFIGURED)
    )
    assert result.line_count == 2


# The rules applied to a Python file under the strict profile (grows with every rule).
APPLIED_TO_PYTHON = (
    "ASSERT001",
    "ASSERT002",
    "ASYNC001",
    "ASYNC002",
    "ASYNC003",
    "BATCH001",
    "BOOL001",
    "CPLX001",
    "CPLX002",
    "CPLX003",
    "CPLX004",
    "CPLX005",
    "CPLX006",
    "DEF001",
    "DEF002",
    "DEF003",
    "DEF004",
    "DEF005",
    "DEF006",
    "EXC001",
    "EXC002",
    "EXC003",
    "EXC004",
    "GUARD001",
    "IMPORT001",
    "INPUT001",
    "INPUT002",
    "MAGIC001",
    "MAGIC002",
    "MAGIC003",
    "MAGIC004",
    "PROCESS001",
    "PROV001",
    "RESULT001",
    "RETRY001",
    "ROLE001",
    "SLEEP001",
    "STATE001",
    "STUB001",
    "STUB002",
    "STUB003",
    "SUPP001",
    "SUPP002",
    "TYPE001",
)


def test_file_result_json_shape(strict_config: EffectiveConfig) -> None:
    data = analyze_text(
        "t.py", "python", "x = 2\n", strict_config, AnalysisOptions(True, CACHE_CONFIGURED)
    ).to_json_dict()
    assert data["path"] == "t.py"
    assert data["status"] == "analyzed"
    assert data["finding_count"] == 1
    assert data["rules_applied"] == list(APPLIED_TO_PYTHON)


def test_override_and_configuration_file_patterns_honour_the_root_anchor(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    """0.3.0, item 4: ``/conftest.py`` and ``./tests/**`` apply at the root only."""
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\n"
        'configuration_files = ["/conftest.py"]\n'
        "[[tool.shockharness.overrides]]\n"
        'paths = ["./tests/**"]\ndisable = ["MAGIC001"]\nreason = "fixtures"\n'
    )

    def disabled(path: str) -> list[tuple[str, str]]:
        result = analyze_text(
            path, "python", "x = 2\n", config, AnalysisOptions(True, CACHE_CONFIGURED)
        )
        return [(d.rule_id, d.origin) for d in result.rules_disabled]

    assert disabled("conftest.py") == [("MAGIC001", "configuration_file")]
    assert disabled("pkg/conftest.py") == []
    assert disabled("tests/t.py") == [("MAGIC001", "overrides[0]")]
    assert disabled("pkg/tests/t.py") == []
    assert (
        analyze_text(
            "pkg/tests/t.py", "python", "x = 2\n", config, AnalysisOptions(True, CACHE_CONFIGURED)
        ).findings
        != ()
    )
