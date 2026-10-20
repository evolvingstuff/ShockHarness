"""G2: exceptions and defaults on C# (spec 21.1 decision 41): catch facts, boundaries,
EXC001-EXC003 and DEF001-DEF006."""

from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.ir.csharp import extract_csharp_facts
from shockharness.ir.model import (
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_RAISE_CHAINED,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    CATCH_CSHARP,
)
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def run(config: EffectiveConfig, text: str, path: str = "Save.cs") -> FileResult:
    return analyze_text(path, "csharp", text, config, OPTIONS)


def rows(result: FileResult, prefix: str) -> list[tuple[str, int]]:
    return [(f.rule_id, f.span.line) for f in result.findings if f.rule_id.startswith(prefix)]


CATCHES = "\n".join(
    [
        "class Save {",
        "    int Load(string path) {",
        "        try { return Parse(path); }",
        "        catch (IOException) { return 0; }",
        "        catch (System.Exception e) when (e is FormatException or OverflowException)"
        " { GD.PushError(e.Message); }",
        '        catch (InvalidOperationException e) { throw new SaveError("bad save", e); }',
        "        catch (TimeoutException e) { throw e; }",
        "        catch (ArgumentException) { throw; }",
        "        catch { }",
        "    }",
        "}",
        "",
    ]
)


def test_catch_facts_name_types_narrow_by_filter_and_classify_bodies() -> None:
    facts = extract_csharp_facts(SourceText.from_text(CATCHES), "Save.cs")
    rows_ = [
        (
            c.span.line,
            [i.source for i in c.identities],
            c.bare,
            [i.broad for i in c.identities],
            c.narrowed_from,
            c.body.classification,
        )
        for c in facts.catches
    ]
    assert rows_ == [
        (4, ["IOException"], False, [False], None, BODY_RETURN_FALLBACK),
        (
            5,
            ["FormatException", "OverflowException"],
            False,
            [False, False],
            "System.Exception",
            BODY_LOGGING_ONLY,
        ),
        (6, ["InvalidOperationException"], False, [False], None, BODY_RAISE_CHAINED),
        (7, ["TimeoutException"], False, [False], None, BODY_RAISE_OTHER),
        (8, ["ArgumentException"], False, [False], None, BODY_RERAISE),
        (9, [], True, [], None, BODY_EMPTY),
    ]
    assert {c.kind for c in facts.catches} == {CATCH_CSHARP}
    assert [s.operation for s in facts.catches[0].try_statements] == ["Parse"]
    assert facts.catches[1].bound_name == "e"


def test_broad_types_are_broad() -> None:
    text = (
        "class C { void M() { try { F(); } catch (Exception) { throw; }"
        " catch (System.SystemException) { throw; } } }\n"
    )
    facts = extract_csharp_facts(SourceText.from_text(text), "C.cs")
    assert [i.broad for c in facts.catches for i in c.identities] == [True, True]


def test_exception_rules_on_csharp(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, CATCHES)
    assert rows(result, "EXC") == [
        ("EXC001", 4),
        ("EXC001", 5),
        ("EXC002", 5),
        ("EXC001", 6),
        ("EXC001", 7),
        ("EXC002", 7),
        ("EXC001", 8),
        ("EXC001", 9),
        ("EXC002", 9),
    ]
    assert rows(result, "DEF005") == [("DEF005", 4)]
    messages = {f.span.line: f.message for f in result.findings if f.rule_id == "EXC002"}
    assert "resets the stack trace" in messages[7]
    assert "narrowed from 'System.Exception' by its when filter" in next(
        f.message for f in result.findings if f.rule_id == "EXC001" and f.span.line == 5
    )
    # `throw;` rethrows unchanged (BODY_RERAISE): no EXC002, but strict does not make it
    # transparent (rules.exceptions.transparent_rethrow), so EXC001 still applies.
    assert ("EXC002", 8) not in rows(result, "EXC")


BOUNDARY = """\
[[tool.shockharness.rules.exceptions.boundaries]]
path = "Save.cs"
language = "csharp"
exception = "System.IO.IOException"
reason = "save files are the player's disk"
"""


def test_a_csharp_boundary_approves_a_catch_and_exc003_checks_its_scope(make_config: Any) -> None:
    config = make_config(BOUNDARY)
    one = (
        "class Save { string Read(string p) {\n"
        "    try { return File.ReadAllText(p); }\n"
        "    catch (IOException e) { throw new SaveError(p, e); } } }\n"
    )
    assert rows(run(config, one), "EXC") == []
    two = (
        "class Save { string Read(string p) {\n"
        "    try { var t = File.ReadAllText(p); Check(t); return t; }\n"
        "    catch (IOException e) { throw new SaveError(p, e); } } }\n"
    )
    assert rows(run(config, two), "EXC") == [("EXC003", 2)]
    assert rows(run(config, one, "Other.cs"), "EXC") == [("EXC001", 3)]


DEFAULTS = """\
using System.Runtime.CompilerServices;
class Settings {
    int Load(string path, int slot = 0, [CallerMemberName] string caller = "") => slot;
    string Name(string? s, Dictionary<string, int> d, Node n) {
        var a = s ?? "anon";
        var b = s ?? throw new ArgumentNullException(nameof(s));
        var c = s == null ? "x" : s;
        var e = string.IsNullOrEmpty(s) ? "y" : s;
        var f = d.GetValueOrDefault("k", 3);
        var g = d.TryGetValue("k", out var v) ? v : 4;
        var h = System.Environment.GetEnvironmentVariable("HOME") ?? "/";
        var i = OS.GetEnvironment("PATH");
        var j = (int)ProjectSettings.GetSetting("display/w", 640);
        var k = n.GetChildren().FirstOrDefault();
        var l = n.GetMeta("hp", 10);
        var m = config.GetValue("audio", "volume", 1.0);
        if (s == null) { return "none"; }
        s ??= "z";
        return a;
    }
}
"""


def test_default_shapes_on_csharp(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, DEFAULTS, "Settings.cs")
    found = [
        (f.rule_id, f.span.line, f.severity) for f in result.findings if f.rule_id.startswith("DEF")
    ]
    assert found == [
        ("DEF001", 3, "error"),
        ("DEF004", 5, "error"),
        ("DEF004", 7, "error"),
        ("DEF003", 8, "review"),
        ("DEF002", 9, "error"),
        ("DEF002", 10, "error"),
        ("DEF006", 11, "error"),
        ("DEF006", 12, "review"),
        ("DEF006", 13, "error"),
        ("DEF002", 14, "review"),
        ("DEF002", 15, "error"),
        ("DEF006", 16, "error"),
        ("DEF004", 18, "error"),
    ]
    messages = {(f.rule_id, f.span.line): f.message for f in result.findings}
    assert messages[("DEF004", 5)].startswith('s falls back to "anon" when null;')
    assert messages[("DEF003", 8)].startswith('s falls back to "y" when null or empty;')
    assert messages[("DEF006", 13)].startswith("setting display/w falls back to 640;")
    assert "audio/volume" in messages[("DEF006", 16)]


GUARDRAILS = "\n".join(
    [
        "public partial class Player : CharacterBody2D {",
        "    public override void _PhysicsProcess(double delta) {",
        "        Velocity.Normalized();",
        "        name.Trim();",
        "        _ = name.Trim();",
        "        Mathf.Clamp(hp, 0, max);",
        "        AddChild(node, true);",
        "        Configure(enabled: true, 2);",
        "        SetProcess(false);",
        "        items.Where(i => i.Alive);",
        "        try { other.Trim(); } catch (System.Exception) { throw; }",
        "        list.Reverse();",
        "    }",
        "    public int Damage() => throw new NotImplementedException();",
        '    void Later() { throw new System.NotImplementedException("later"); }',
        "    public override void _Ready() { }",
        "}",
        "",
    ]
)


def test_results_booleans_and_placeholders_on_csharp(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, GUARDRAILS, "Player.cs")
    found = [
        (f.rule_id, f.span.line)
        for f in result.findings
        if f.rule_id in ("RESULT001", "BOOL001", "STUB001")
    ]
    assert found == [
        ("RESULT001", 3),
        ("RESULT001", 4),
        ("RESULT001", 6),
        ("BOOL001", 7),
        ("RESULT001", 10),
        ("STUB001", 14),
        ("STUB001", 15),
    ]
    confidence = {(f.rule_id, f.span.line): f.confidence for f in result.findings}
    assert confidence[("RESULT001", 6)] == "exact"  # Mathf.Clamp, by its qualified name
    assert confidence[("RESULT001", 4)] == "approximate"  # .Trim on an untyped receiver
