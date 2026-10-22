"""G4 part two: C#'s suppressions (VERIFY002, TYPE001), type escapes (TYPE001), nullable
checking (TYPE002) and the .NET build settings a change can loosen (VERIFY003); spec 21.1
decision 52."""

import json
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.cli import main
from shockharness.config import EffectiveConfig
from shockharness.ir.csharp import extract_csharp_facts
from shockharness.rules.tool_configs import ToolSettings, read_tool_settings, tool_loosenings
from shockharness.source import SourceText
from tests.conftest import commit_all, init_repo

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OPT_IN = 'include = ["**/*.cs"]\n'
BASE_DATE = "2026-01-01T12:00:00+00:00"
HEAD_DATE = "2026-01-02T12:00:00+00:00"

SUPPRESSED = """\
#nullable disable
#pragma warning disable CS8602, IDE0051 // why
#pragma warning disable
using System.Diagnostics.CodeAnalysis;
[assembly: SuppressMessage("Style", "IDE0051:Remove unused", Justification = "x")]
public class Hero
{
    // ReSharper disable once InconsistentNaming
    [SuppressMessage("Usage", "CA1822")] public dynamic Load(string? s) => s!.Length;
#pragma warning restore CS8602
#pragma warning disable IDE0051
    private void Unused() { var cast = (Node)thing; var items = new List<dynamic>(); }
}
"""


def test_the_suppressions_are_collected() -> None:
    facts = extract_csharp_facts(SourceText.from_text(SUPPRESSED), "Hero.cs")
    found = [
        (d.tool, d.scope, d.codes, d.narrow, d.text, d.span.line)
        for d in facts.verification.suppressions
    ]
    assert found == [
        ("nullable-disable", "region", (), False, "#nullable disable", 1),
        (
            "pragma-warning",
            "region",
            ("CS8602", "IDE0051"),
            True,
            "#pragma warning disable CS8602,IDE0051",
            2,
        ),
        ("pragma-warning", "region", (), False, "#pragma warning disable", 3),
        ("suppress-message", "file", ("IDE0051",), True, "[SuppressMessage(IDE0051)]", 5),
        (
            "resharper-disable",
            "next-line",
            ("InconsistentNaming",),
            True,
            "ReSharper disable once InconsistentNaming",
            8,
        ),
        ("suppress-message", "region", ("CA1822",), True, "[SuppressMessage(CA1822)]", 9),
        ("pragma-warning", "region", ("IDE0051",), True, "#pragma warning disable IDE0051", 11),
    ]


def test_type001_on_csharp(make_config: Any) -> None:
    config: EffectiveConfig = make_config(OPT_IN)
    result = analyze_text("Hero.cs", "csharp", SUPPRESSED, config, OPTIONS)
    found = [(f.span.line, f.message) for f in result.findings if f.rule_id == "TYPE001"]
    assert [line for line, _message in found] == [1, 2, 3, 9, 9, 12]
    messages = dict(found)
    assert messages[1] == "#nullable disable turns the compiler's null checking off from here on"
    assert messages[2].startswith("#pragma warning disable CS8602,IDE0051 silences the compiler")
    assert messages[12] == "dynamic turns type checking off for this value: <dynamic>"
    nine = [message for line, message in found if line == 9]
    assert nine == [
        "dynamic turns type checking off for this value: dynamic Load",
        "the null-forgiving operator (!) claims the value is never null without checking it: s!",
    ]


def project(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


CSPROJ = """\
<Project Sdk="Godot.NET.Sdk/4.6.1">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <!-- <Nullable>enable</Nullable> -->
  </PropertyGroup>
</Project>
"""
NULLABLE = CSPROJ.replace("<!-- <Nullable>enable</Nullable> -->", "<Nullable>enable</Nullable>")


def type002(root: Path, make_config: Any, files: dict[str, str]) -> list[tuple[str, str]]:
    project(root, files)
    report = analyze_paths([root], root, make_config(OPT_IN), OPTIONS)
    return [(f.path, f.message) for f in report.findings if f.rule_id == "TYPE002"]


def test_type002_a_project_without_nullable(empty_root: Path, make_config: Any) -> None:
    files = {
        "game/Game.csproj": CSPROJ,
        "game/b/Hero.cs": "public class Hero { }\n",
        "game/a/Mob.cs": "public class Mob { }\n",
        "tools/Tool.csproj": NULLABLE,
        "tools/Tool.cs": "public class Tool { }\n",
        "Loose.cs": "public class Loose { }\n",
    }
    assert type002(empty_root, make_config, files) == [
        (
            "game/a/Mob.cs",
            "game/Game.csproj does not turn nullable reference types on "
            "(<Nullable>enable</Nullable>): the compiler checks no null in its 2 C# file(s)",
        )
    ]


@pytest.mark.parametrize(
    "props",
    [
        {"game/Game.csproj": NULLABLE},
        {
            "Directory.Build.props": "<Project><PropertyGroup><Nullable>warnings</Nullable>"
            "</PropertyGroup></Project>\n"
        },
    ],
)
def test_type002_nullable_turned_on(
    empty_root: Path, make_config: Any, props: dict[str, str]
) -> None:
    files = {"game/Game.csproj": CSPROJ, "game/Hero.cs": "public class Hero { }\n", **props}
    assert type002(empty_root, make_config, files) == []


def settings(name: str, text: str) -> ToolSettings:
    parsed, error = read_tool_settings(name, text)
    assert error is None and parsed is not None
    return parsed


def changes(name: str, before: str, after: str) -> list[tuple[str, str]]:
    found = tool_loosenings(settings(name, before), settings(name, after))
    return [(item.category, item.item) for item in found]


STRICT = """\
<Project Sdk="Godot.NET.Sdk/4.6.1">
  <PropertyGroup>
    <Nullable>enable</Nullable>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <WarningsAsErrors>nullable;CS0168</WarningsAsErrors>
    <NoWarn>$(NoWarn);CS0414</NoWarn>
    <AnalysisMode>All</AnalysisMode>
    <AnalysisLevel>latest-recommended</AnalysisLevel>
  </PropertyGroup>
</Project>
"""
LOOSE = """\
<Project Sdk="Godot.NET.Sdk/4.6.1">
  <PropertyGroup>
    <Nullable>disable</Nullable>
    <WarningsAsErrors>CS0168</WarningsAsErrors>
    <NoWarn>$(NoWarn);CS0414;CS8602</NoWarn>
    <AnalysisMode>Recommended</AnalysisMode>
    <AnalysisLevel>latest-none</AnalysisLevel>
  </PropertyGroup>
</Project>
"""


def test_msbuild_settings_turned_down() -> None:
    assert changes("game/Game.csproj", STRICT, LOOSE) == [
        ("dotnet.NoWarn", "CS8602"),
        ("dotnet.checks", "Nullable=enable"),
        ("dotnet.checks", "TreatWarningsAsErrors=true"),
        ("dotnet.WarningsAsErrors", "nullable"),
        ("dotnet.levels", "AnalysisLevel"),
        ("dotnet.levels", "AnalysisMode"),
    ]
    assert changes("game/Game.csproj", LOOSE, STRICT) == []
    assert changes("Directory.Build.props", STRICT, "<Project/>\n")[0] == (
        "dotnet.checks",
        "Nullable=enable",
    )


EDITORCONFIG = """\
root = true

[*.cs]
dotnet_diagnostic.CA1822.severity = error
dotnet_diagnostic.IDE0051.severity = warning
dotnet_analyzer_diagnostic.category-Style.severity = suggestion ; comment
dotnet_diagnostic.CA2000.severity = none
"""


def test_editorconfig_severities_turned_down() -> None:
    after = (
        EDITORCONFIG.replace("CA1822.severity = error", "CA1822.severity = suggestion")
        .replace("dotnet_diagnostic.IDE0051.severity = warning\n", "")
        .replace("CA2000.severity = none", "CA2000.severity = error")
    )
    assert changes(".editorconfig", EDITORCONFIG, after) == [
        ("dotnet.levels", "[*.cs] dotnet_diagnostic.CA1822.severity"),
        ("dotnet.levels", "[*.cs] dotnet_diagnostic.IDE0051.severity"),
    ]
    assert changes("game/.editorconfig", after, EDITORCONFIG) == [
        ("dotnet.levels", "[*.cs] dotnet_diagnostic.CA2000.severity")
    ]


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_verify002_and_verify003_on_a_csharp_change(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\n" + OPT_IN)
    write(empty_root, "game/Game.csproj", STRICT)
    write(empty_root, "game/.editorconfig", EDITORCONFIG)
    write(empty_root, "game/Hero.cs", "public class Hero\n{\n    public int Hp;\n}\n")
    base = commit_all(empty_root, "base", BASE_DATE, "one@example.invalid")
    write(empty_root, "game/Game.csproj", LOOSE)
    write(
        empty_root,
        "game/Hero.cs",
        "#pragma warning disable\npublic class Hero\n{\n    public int Hp;\n}\n",
    )
    commit_all(empty_root, "loosen", HEAD_DATE, "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root)]
    main(["diff", *revision, "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    found = sorted(
        (f["rule_id"], f["path"], f["span"]["line"])
        for f in data["findings"]
        if f["rule_id"] in ("VERIFY002", "VERIFY003")
    )
    assert ("VERIFY002", "game/Hero.cs", 1) in found
    assert ("VERIFY003", "game/Game.csproj", 3) in found  # Nullable=enable
    messages = [f["message"] for f in data["findings"] if f["rule_id"] == "VERIFY003"]
    assert any("dotnet.checks no longer includes 'Nullable=enable'" in m for m in messages)
    assert any("dotnet.NoWarn now includes 'CS8602'" in m for m in messages)


def test_late_initialization_is_not_an_escape(make_config: Any) -> None:
    text = (
        "public partial class Hud : Control\n{\n"
        "    private Label _score = null!;\n"
        "    private Label _lives = default!;\n"
        "    public override void _Ready() { var data = Load()!; }\n}\n"
    )
    result = analyze_text("Hud.cs", "csharp", text, make_config(OPT_IN), OPTIONS)
    assert [f.span.line for f in result.findings if f.rule_id == "TYPE001"] == [5]
