"""SARIF 2.1.0 output: structural check against the required keys, level mapping,
fingerprints, suppressions, and baseline states."""

import json
from pathlib import Path

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths, apply_baseline
from shockharness.config import EffectiveConfig
from shockharness.gating.baseline import FINGERPRINT_KEY, build_baseline
from shockharness.output import sarif
from shockharness.rules import registry

OPTIONS = AnalysisOptions(inline_suppressions=True)

# The parts of the SARIF 2.1.0 schema a code-scanning consumer requires. Same tiny
# checker style as the report schema test: type, enum, required, properties, items.
SARIF_SHAPE = {
    "type": "object",
    "required": ["$schema", "version", "runs"],
    "properties": {
        "version": {"type": "string", "enum": ["2.1.0"]},
        "runs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool", "results"],
                "properties": {
                    "tool": {
                        "type": "object",
                        "required": ["driver"],
                        "properties": {
                            "driver": {
                                "type": "object",
                                "required": ["name", "version", "informationUri", "rules"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "informationUri": {"type": "string"},
                                    "rules": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": [
                                                "id",
                                                "name",
                                                "shortDescription",
                                                "fullDescription",
                                                "help",
                                                "defaultConfiguration",
                                            ],
                                            "properties": {
                                                "shortDescription": {
                                                    "type": "object",
                                                    "required": ["text"],
                                                },
                                                "fullDescription": {
                                                    "type": "object",
                                                    "required": ["text"],
                                                },
                                                "defaultConfiguration": {
                                                    "type": "object",
                                                    "required": ["level"],
                                                    "properties": {
                                                        "level": {
                                                            "enum": ["error", "warning", "note"]
                                                        }
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            }
                        },
                    },
                    "invocations": {
                        "type": "array",
                        "items": {"type": "object", "required": ["executionSuccessful"]},
                    },
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "ruleId",
                                "ruleIndex",
                                "level",
                                "message",
                                "locations",
                                "partialFingerprints",
                                "suppressions",
                            ],
                            "properties": {
                                "level": {"enum": ["error", "warning", "note"]},
                                "message": {"type": "object", "required": ["text"]},
                                "baselineState": {
                                    "enum": ["new", "unchanged", "updated", "absent"]
                                },
                                "locations": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["physicalLocation"],
                                        "properties": {
                                            "physicalLocation": {
                                                "type": "object",
                                                "required": ["artifactLocation", "region"],
                                                "properties": {
                                                    "artifactLocation": {
                                                        "type": "object",
                                                        "required": ["uri"],
                                                    },
                                                    "region": {
                                                        "type": "object",
                                                        "required": [
                                                            "startLine",
                                                            "startColumn",
                                                            "endLine",
                                                            "endColumn",
                                                        ],
                                                        "properties": {
                                                            "startLine": {"type": "integer"},
                                                            "startColumn": {"type": "integer"},
                                                            "endLine": {"type": "integer"},
                                                            "endColumn": {"type": "integer"},
                                                        },
                                                    },
                                                },
                                            }
                                        },
                                    },
                                },
                                "suppressions": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["kind"],
                                        "properties": {"kind": {"enum": ["inSource", "external"]}},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_sarif_scan_output_is_structurally_valid(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    from tests.unit.test_gate_and_report import _check

    write(
        empty_root,
        "src/a.py",
        'x = 2  # shockharness: ignore[MAGIC001] reason="r"\n'
        'y = 1  # shockharness: ignore[MAGIC001] reason="unused"\n'
        "def f(a):\n    return a or {}\n",
    )
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = json.loads(sarif.render(report))
    assert _check(SARIF_SHAPE, data, "$") == []
    assert len(data["runs"]) == 1
    run = data["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "ShockHarness"
    assert driver["informationUri"] == "https://github.com/evolvingstuff/ShockHarness"
    assert [r["id"] for r in driver["rules"]] == [r.rule_id for r in registry.RULES]
    assert all(r["fullDescription"]["text"] != "" for r in driver["rules"])

    by_rule = {r["ruleId"]: r for r in run["results"]}
    assert set(by_rule) == {"MAGIC001", "SUPP002", "DEF003"}
    assert by_rule["MAGIC001"]["level"] == "error"
    assert by_rule["SUPP002"]["level"] == "warning"
    assert by_rule["DEF003"]["level"] == "note"  # review -> note
    assert by_rule["MAGIC001"]["suppressions"] == [{"kind": "inSource", "justification": "r"}]
    assert by_rule["DEF003"]["suppressions"] == []
    for result in run["results"]:
        assert driver["rules"][result["ruleIndex"]]["id"] == result["ruleId"]
        assert "baselineState" not in result  # no baseline was applied
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "src/a.py"
        assert "\\" not in location["artifactLocation"]["uri"]
        fingerprint = result["partialFingerprints"][FINGERPRINT_KEY]
        assert len(fingerprint) == 64
    matching = [f for f in report.findings if f.rule_id == "DEF003"]
    assert by_rule["DEF003"]["partialFingerprints"][FINGERPRINT_KEY] == matching[0].fingerprint
    assert by_rule["DEF003"]["locations"][0]["logicalLocations"] == [{"name": "f"}]
    assert run["invocations"][0]["executionSuccessful"] is True
    assert run["invocations"][0]["exitCode"] == 0


def test_sarif_reports_baseline_states_after_a_baseline(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, strict_config.digest)
    write(empty_root, "src/a.py", "x = 2\ny = 3\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = json.loads(sarif.render(apply_baseline(report, baseline, strict_config)))
    states = [r["baselineState"] for r in data["runs"][0]["results"]]
    assert states == ["unchanged", "new"]


def test_sarif_failed_analysis_is_not_successful(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/bad.js", "function (\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = json.loads(sarif.render(report))
    invocation = data["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    assert invocation["exitCode"] == 3
    assert data["runs"][0]["properties"]["files_failed"][0]["path"] == "src/bad.js"


def test_sarif_output_is_deterministic(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    first = sarif.render(analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS))
    second = sarif.render(analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS))
    assert first == second
