"""G3: the C# call graph (type index, receivers, partial classes, CPLX005) and DEAD001/
DEAD002 with Godot roots (spec 21.1 decision 46)."""

from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OPT_IN = 'include = ["**/*.cs"]\n'
DEAD = OPT_IN + "\n[tool.shockharness.rules.dead_code]\nenabled = true\n"


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def project(root: Path, make_config: Any, config: str, files: dict[str, str]) -> Any:
    write(root, files)
    return analyze_paths([root], root, make_config(config), OPTIONS)


GRAPH = {
    "Player.cs": """\
public partial class Player : CharacterBody2D
{
    private Hud _hud;
    public override void _Ready()
    {
        Heal();
        this.Heal();
        _hud.Show(1);
        var enemy = GetNode<Enemy>("Enemy");
        enemy.Hit();
        Score.Add(1);
        var gun = new Gun();
        int Twice(int x) => x * 2;
        Twice(2);
    }
}
""",
    "Player.Moves.cs": """\
public partial class Player
{
    private void Heal() { Jump(); }
    private void Jump() { }
}
""",
    "Hud.cs": "public class Hud { public void Show(int n) { } }\n",
    "Enemy.cs": """\
public class Creature { public virtual void Hit() { } }
public class Enemy : Creature { public void Flee() { base.Hit(); } }
""",
    "Score.cs": "public static class Score { public static void Add(int n) { } }\n",
    "Gun.cs": "public class Gun { public Gun() { } }\n",
}


def test_csharp_calls_resolve_through_the_type_index(empty_root: Path, make_config: Any) -> None:
    report = project(empty_root, make_config, OPT_IN, GRAPH)
    edges = {
        (e["from"].split("::")[1], e["to"]["id"].split("::")[-1], e["confidence"])
        for e in report.metrics["graph"]["edges"]
        if e["to"]["kind"] == "unit"
    }
    assert {
        ("Player._Ready", "Player.Heal", "resolved"),
        ("Player._Ready", "Hud.Show", "resolved"),
        ("Player._Ready", "Creature.Hit", "resolved"),
        ("Player._Ready", "Score.Add", "resolved"),
        ("Player._Ready", "Gun.Gun", "resolved"),
        ("Player._Ready", "Player._Ready.Twice", "resolved"),
        ("Player.Heal", "Player.Jump", "resolved"),
        ("Enemy.Flee", "Creature.Hit", "probable"),
    } <= edges
    types = {
        (m["from"], m["to"]) for m in report.metrics["graph"]["module_edges"] if m["kind"] == "type"
    }
    assert ("Player.cs", "Hud.cs") in types and ("Player.cs", "Score.cs") in types
    assert ("Player.cs", "Player.Moves.cs") not in types  # one class's partial files


def test_a_csharp_file_cycle_is_cplx005(empty_root: Path, make_config: Any) -> None:
    files = {
        "A.cs": "public class A { public void Go() { B.Back(); } public static void Back() { } }\n",
        "B.cs": "public class B { public static void Back() { A.Back(); } }\n",
    }
    report = project(empty_root, make_config, OPT_IN, files)
    (cycle,) = [f for f in report.findings if f.rule_id == "CPLX005"]
    assert "module import cycle of 2 C# module(s)" in cycle.message
    assert "whose call into" in cycle.message


GODOT = {
    "project.godot": (
        'config_version=5\n\n[application]\nrun/main_scene="res://Main.tscn"\n\n'
        '[autoload]\nGlobal="*res://Global.cs"\n'
    ),
    "Main.tscn": """\
[gd_scene format=3]

[ext_resource type="Script" path="res://Main.cs" id="1"]
[ext_resource type="PackedScene" path="res://Mob.tscn" id="2"]

[node name="Main" type="Node"]
script = ExtResource("1")

[node name="Mob" parent="." instance=ExtResource("2")]

[connection signal="pressed" from="Button" to="." method="OnButtonPressed"]
[connection signal="died" from="Mob" to="Mob" method="OnDied"]
""",
    "Mob.tscn": """\
[gd_scene format=3]

[ext_resource type="Script" path="res://Mob.cs" id="1"]

[sub_resource type="Animation" id="A"]
tracks/0/keys = {
"values": [{"args": [], "method": &"Vanish"}]
}

[node name="Mob" type="Node2D"]
script = ExtResource("1")
""",
    "Main.cs": """\
public partial class Main : Node
{
    public override void _Ready() { Call("Shout"); var cb = MethodName.Jump; }
    private void OnButtonPressed() { }
    private void Shout() { }
    private void Jump() { }
    private void Forgotten() { }
    [Rpc] private void Sync() { }
}
""",
    "Mob.cs": """\
public partial class Mob : Node2D
{
    public override void _Process(double delta) { }
    private void OnDied() { }
    private void Vanish() { }
}
""",
    "Global.cs": "public partial class Global : Node { public override void _Ready() { } }\n",
    "Unused.cs": """\
public partial class Unused : Node2D
{
    public override void _Ready() { Helper(); }
    private void Helper() { }
}
""",
    "Tools.cs": "public static class Tools { public static int Only() => 1; }\n",
    "tests/ToolsTests.cs": "public class ToolsTests { public void Check() { Tools.Only(); } }\n",
}


def test_dead_code_with_godot_roots_and_dead_scripts(empty_root: Path, make_config: Any) -> None:
    report = project(empty_root, make_config, DEAD, GODOT)
    found = sorted(
        (f.rule_id, f.path, f.scope) for f in report.findings if f.rule_id.startswith("DEAD")
    )
    assert found == [
        ("DEAD001", "Main.cs", "Main.Forgotten"),
        ("DEAD001", "Unused.cs", "Unused"),
        ("DEAD002", "Tools.cs", "Tools.Only"),
    ]
    (script,) = [f for f in report.findings if f.scope == "Unused"]
    assert "no scene attaches its script" in script.message
    assert "Unused._Ready" in script.message and "Unused.Helper" in script.message


def test_an_unreadable_scene_leaves_csharp_unjudged(empty_root: Path, make_config: Any) -> None:
    files = dict(GODOT)
    write(empty_root, files)
    (empty_root / "Broken.tscn").write_bytes(b"[gd_scene format=3]\n\xff\n")
    report = analyze_paths([empty_root], empty_root, make_config(DEAD), OPTIONS)
    assert [f for f in report.findings if f.rule_id.startswith("DEAD")] == []
