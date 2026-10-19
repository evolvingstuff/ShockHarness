"""G1: C# (Godot .NET) through tree-sitter-c-sharp: parsing, numeric literals and named
definitions, function facts, and the rules that run on C# (spec 21.1 decision 40)."""

from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.complexity.cognitive import cognitive
from shockharness.complexity.cyclomatic import cyclomatic
from shockharness.config import EffectiveConfig
from shockharness.discovery import discover
from shockharness.ir.csharp import (
    blank_lambda_modifiers,
    extract_csharp_facts,
    keep_first_branches,
)
from shockharness.ir.csharp_numbers import parse_csharp_number
from shockharness.ir.model import FunctionFact, ModuleFacts
from shockharness.rules import registry
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def facts_of(text: str) -> ModuleFacts:
    return extract_csharp_facts(SourceText.from_text(text), "Player.cs")


def unit(facts: ModuleFacts, name: str) -> FunctionFact:
    found = [f for f in facts.functions if f.name == name]
    assert len(found) == 1, [f.name for f in facts.functions]
    return found[0]


def run(config: EffectiveConfig, text: str, path: str = "Player.cs") -> FileResult:
    return analyze_text(path, registry.CSHARP, text, config, OPTIONS)


def rows(result: FileResult, rule: str) -> list[tuple[int, str]]:
    return [(f.span.line, f.message) for f in result.findings if f.rule_id == rule]


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    write(root, files)
    return analyze_paths([root], root, config, OPTIONS)


# -- numbers and parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("0", 0),
        ("42", 42),
        ("1_000UL", 1000),
        ("10L", 10),
        ("0x1F", 31),
        ("0xFFu", 255),
        ("0b1010", 10),
        ("300f", 300.0),
        ("0.5f", 0.5),
        (".25f", 0.25),
        ("1.5e3", 1500.0),
        ("2m", 2.0),
        ("1e3d", 1000.0),
    ],
)
def test_numeric_literal_values(raw: str, value: float) -> None:
    assert parse_csharp_number(raw) == value
    assert type(parse_csharp_number(raw)) is type(value)


def test_first_branch_of_each_conditional_is_kept_and_positions_are_unchanged() -> None:
    text = "a\n#if TOOLS\nb\n#elif DEBUG\nc\n#else\nd\n#endif\ne\n"
    kept = keep_first_branches(text)
    assert [line.strip() for line in kept.split("\n")] == [
        "a",
        "",
        "b",
        "",
        "",
        "",
        "",
        "",
        "e",
        "",
    ]
    assert len(kept) == len(text)
    nested = "#if A\n#if B\nx\n#else\ny\n#endif\n#else\nz\n#endif\n"
    assert [line.strip() for line in keep_first_branches(nested).split("\n")] == [
        "",
        "",
        "x",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def test_lambda_parameter_modifiers_are_blanked_in_place() -> None:
    text = "Bind().On((in State.Output output) => Play(output));"
    blanked = blank_lambda_modifiers(text)
    assert blanked == "Bind().On((   State.Output output) => Play(output));"
    assert blank_lambda_modifiers("F(in x, out var y);") == "F(in x, out var y);"
    two = "On((in A a, ref B b) => G(a, b));"
    assert blank_lambda_modifiers(two) == "On((   A a,     B b) => G(a, b));"


def test_godot_script_parses_with_conditional_attributes_and_in_lambdas() -> None:
    text = (
        "using Godot;\n"
        "#if TOOLS\n"
        "[Tool]\n"
        "#endif\n"
        "public partial class Player : CharacterBody2D\n"
        "{\n"
        "    public override void _Ready()\n"
        "    {\n"
        "        Binding.OnOutput((in Output.Animate o) => Play(o));\n"
        "    }\n"
        "}\n"
    )
    facts = facts_of(text)
    assert facts.parse_failure is None
    assert facts.language == "csharp"
    assert facts.parser.startswith("tree-sitter-c-sharp ")


def test_a_syntax_error_is_a_parse_failure() -> None:
    facts = facts_of("public class P { void M( { }\n")
    assert facts.parse_failure is not None
    assert facts.functions == ()


# -- literals and named definitions ------------------------------------------------------


GODOT_NUMBERS = """\
using Godot;

public partial class Player : CharacterBody2D
{
    public const float Speed = 300.0f;
    private const int ChunkBytes = 64 * 1024;
    private static readonly Vector2 Spawn = new Vector2(64, 32);
    private static readonly Color Ink = new(0.2f, 0.18f, 0.14f);
    private static readonly int Retries = 3;
    [Export] public float JumpVelocity { get; set; } = -400.0f;
    [Export] private Vector2 _start = new(10, 20);
    private Vector2 _torch = new(120, -110);
    private static readonly Vector2 Offset = new Vector2(Speed, 2);

    public override void _PhysicsProcess(double delta)
    {
        const int Local = 7;
        Velocity += new Vector2(0, 980f) * (float)delta;
        var unit = new Vector2(1, -1) * 0.0f;
    }
}

[System.Flags]
public enum Layer { None = 0, World = 1 << 0, Mobs = 1 << 3, Items = 16 }
"""


def test_named_definitions_are_marked() -> None:
    facts = facts_of(GODOT_NUMBERS)
    marked = sorted(
        (lit.raw, lit.span.line) for lit in facts.numeric_literals if lit.constant_definition
    )
    assert marked == [
        ("-400.0f", 10),
        ("0", 24),
        ("0", 24),
        ("0.14f", 8),
        ("0.18f", 8),
        ("0.2f", 8),
        ("1", 24),
        ("1", 24),
        ("10", 11),
        ("1024", 6),
        ("16", 24),
        ("20", 11),
        ("3", 9),
        ("3", 24),
        ("300.0f", 5),
        ("32", 7),
        ("64", 6),
        ("64", 7),
    ]
    assert [c.name for c in facts.constants] == [
        "Speed",
        "ChunkBytes",
        "Spawn",
        "Ink",
        "Retries",
        "JumpVelocity",
        "_start",
        "None",
        "World",
        "Mobs",
        "Items",
    ]


def test_magic001_reports_numbers_outside_named_definitions(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, GODOT_NUMBERS)
    assert result.status != "parse_error"
    assert [line for line, _message in rows(result, "MAGIC001")] == [12, 12, 13, 17, 18]
    values = [f.message for f in result.findings if f.rule_id == "MAGIC001"]
    assert any("120" in m for m in values) and any("980f" in m for m in values)


def test_named_definitions_can_be_reported(make_config: Any) -> None:
    config = make_config(
        '[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "report"\n'
    )
    result = run(config, "class C { const int Size = 8; }\n")
    assert [line for line, _message in rows(result, "MAGIC001")] == [1]


def test_zero_one_and_minus_one_pass_in_every_spelling(strict_config: EffectiveConfig) -> None:
    text = "class C { void M() { F(0, 1, -1, 1f, 0.0f, 1L, 0x1, 1.0d); } }\n"
    assert rows(run(strict_config, text), "MAGIC001") == []


def test_suppression_comment_works_in_csharp(strict_config: EffectiveConfig) -> None:
    text = (
        "class C {\n"
        '    void M() { F(30); } // shockharness: ignore[MAGIC001] reason="spec value"\n'
        '    void N() { G(40); } // shockharness: ignore[MAGIC009] reason="typo"\n'
        "}\n"
    )
    result = run(strict_config, text)
    magic = [
        (f.span.line, f.suppression is not None) for f in result.findings if f.rule_id == "MAGIC001"
    ]
    assert magic == [(2, True), (3, False)]
    assert [line for line, _ in rows(result, "SUPP001")] == [3]


# -- function facts ----------------------------------------------------------------------


UNITS = """\
namespace Game.Actors;

public partial class Mob : Node2D
{
    [Signal] public delegate void HitEventHandler(int damage);
    public int Health { get => _health; set { _health = value; } }
    public bool Alive => _health > 0;
    private int _health;

    public Mob(int health) { _health = health; }

    public override async void _Ready()
    {
        Hit += OnHit;
        await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
        Func<int, int> twice = n => n * 2;
        int Local(int q) => q + 1;
        this.OnHit(Local(twice(1)));
    }

    private void OnHit(int damage) { if (damage > 0) { OnHit(damage - 1); } }

    public IEnumerable<int> Steps() { yield return 1; }
}
"""


def test_units_are_named_within_the_file() -> None:
    facts = facts_of(UNITS)
    assert [(f.name, f.kind, f.class_name) for f in facts.functions] == [
        ("<module>", "module", None),
        ("Mob", "class", None),
        ("Mob.Health.get", "method", "Mob"),
        ("Mob.Health.set", "method", "Mob"),
        ("Mob.Alive", "method", "Mob"),
        ("Mob.Mob", "method", "Mob"),
        ("Mob._Ready", "method", "Mob"),
        ("Mob._Ready.twice", "arrow", None),
        ("Mob._Ready.Local", "function", None),
        ("Mob.OnHit", "method", "Mob"),
        ("Mob.Steps", "method", "Mob"),
    ]


def test_function_facts_record_parameters_async_generators_calls_and_locals() -> None:
    facts = facts_of(UNITS)
    ready = unit(facts, "Mob._Ready")
    assert ready.is_async and not ready.is_generator
    assert unit(facts, "Mob.Steps").is_generator
    assert unit(facts, "Mob.Mob").parameters == 1
    assert unit(facts, "Mob._Ready.twice").parameters == 1
    assert {"twice", "Local"} <= ready.locals
    assert "value" in unit(facts, "Mob.Health.set").locals
    callees = [(c.callee, c.shape, c.receiver_self) for c in ready.calls]
    assert ("ToSignal", "name", False) in callees
    assert ("this.OnHit", "attribute", True) in callees
    assert ("Local", "name", False) in callees
    on_hit = unit(facts, "Mob.OnHit")
    assert cognitive(on_hit.control) == 1 + 1  # the if, the recursive call
    assert unit(facts, "Mob.Health.set").writes == (("_health", "assign"),)


BRANCHES = """\
class C
{
    int M(int a, string? s, object o)
    {
        if (a > 1 && s != null || a < 0) { a++; }
        else if (o is > 0 and < 10 or 20) { a--; }
        else { a = 0; }
        switch (a)
        {
            case 1:
            case 2 when a > 0:
                break;
            default:
                goto case 1;
        }
        var r = a switch { 1 => 2, int n when n > 3 => 4, _ => 0 };
        s ??= "x";
        try { a = int.Parse(s); }
        catch (FormatException) { a = 0; }
        catch (OverflowException e) when (e.Message != null) { throw; }
        finally { a += 1; }
        foreach (var (i, j) in Pairs()) { a += i ? j : 0; }
        return a ?? r;
    }
}
"""


def test_control_tree_of_branches_patterns_switches_and_catches() -> None:
    method = unit(facts_of(BRANCHES), "C.M")
    # 1 + if, its 2 operators, else if, its 2 pattern combinators, 2 non-default switch
    # sections, 2 non-default switch-expression arms, ??=, 2 catches, foreach, ternary, ??
    assert cyclomatic(method.control, count_boolean_operators=True) == 17
    # if 1 + 2 runs, else if 1 + 2 runs, else 1, switch 1, goto 1, switch expression 1,
    # ??= 1, two catches 2, foreach 1, ternary nested in it 2, ?? 1
    assert cognitive(method.control) == 17
    assert {"r", "n", "e", "i", "j"} <= method.locals


# -- the pipeline ------------------------------------------------------------------------


def test_csharp_files_are_discovered_and_godot_output_excluded(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(
        empty_root,
        {
            "Player.cs": "",
            ".godot/mono/temp/obj/Gen.cs": "",
            "obj/Debug/net8.0/GlobalUsings.g.cs": "",
            "bin/Debug/x.cs": "",
            "addons/plugin/Tool.cs": "",
            "tools/geometry.py": "",
        },
    )
    result = discover(empty_root, [empty_root], strict_config)
    assert [(f.relative, f.language) for f in result.files] == [
        ("Player.cs", "csharp"),
        ("addons/plugin/Tool.cs", "csharp"),
        ("tools/geometry.py", "python"),
    ]
    assert registry.CSHARP not in registry.ALL_LANGUAGES


def test_complexity_rules_run_on_csharp(make_config: Any) -> None:
    config = make_config("[tool.shockharness.complexity]\ncognitive_warn = 5\n")
    result = run(config, BRANCHES)
    assert [rule for rule in ("CPLX002",) if rows(result, rule)] == ["CPLX002"]


def test_rules_without_csharp_facts_do_not_run_and_are_listed(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    outcome = project(
        empty_root,
        strict_config,
        {
            "Player.cs": "class P { void M() { try { F(); } catch (Exception) { } } }\n",
            "tools/geometry.py": "def area(w, h):\n    return w * h\n",
        },
    )
    by_path = {f.path: f for f in outcome.files}
    assert by_path["Player.cs"].findings == ()
    applied = set(by_path["Player.cs"].rules_applied)
    assert {"MAGIC001", "CPLX001", "SUPP001"} <= applied
    assert "EXC001" not in applied
    assert outcome.coverage["languages"]["csharp"]["files"] == 1
    not_applicable = outcome.coverage["rules_not_applicable"]
    assert "EXC001" in not_applicable["csharp"]
    assert "MAGIC001" not in not_applicable["csharp"]
    assert "DOM001" in not_applicable["python"] and "EXC001" not in not_applicable["python"]
    assert sorted(not_applicable) == ["csharp", "python"]
