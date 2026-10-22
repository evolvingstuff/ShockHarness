"""G4 part one: GODOT001-GODOT005, Godot names the project does not define (spec 21.1
decision 51)."""

from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.ir.csharp import extract_csharp_facts
from shockharness.ir.model import (
    GODOT_ACTION,
    GODOT_GROUP_READ,
    GODOT_NODE_PATH,
    GODOT_SIGNAL_DECLARED,
    GODOT_SIGNAL_USE,
)
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OPT_IN = 'include = ["**/*.cs"]\n'

PROJECT = {
    "project.godot": """\
config_version=5

[application]
run/main_scene="res://Main.tscn"

[autoload]
Global="*res://Global.cs"

[global_group]
pickups=""

[input]
jump={
"deadzone": 0.5,
"events": []
}
move_left={
"deadzone": 0.5,
"events": []
}
""",
    "Main.tscn": """\
[gd_scene format=3]

[ext_resource type="Script" path="res://Player.cs" id="1"]
[ext_resource type="PackedScene" path="res://Hud.tscn" id="2"]

[node name="Player" type="CharacterBody2D" groups=["players"]]
script = ExtResource("1")

[node name="Sprite" type="Sprite2D" parent="."]

[node name="Hitbox" type="Area2D" parent="Sprite"]
unique_name_in_owner = true

[node name="Hud" parent="." instance=ExtResource("2")]

[connection signal="body_entered" from="Sprite/Hitbox" to="." method="OnHitboxEntered"]
[connection signal="body_exited" from="Sprite/Hitbox" to="." method="OnHitboxLeft"]
[connection signal="ready" from="." to="." method="queue_free"]
""",
    "Hud.tscn": """\
[gd_scene format=3]

[node name="Hud" type="CanvasLayer"]

[node name="Score" type="Label" parent="."]
""",
    "Actor.cs": """\
public partial class Actor : CharacterBody2D
{
    [Signal] public delegate void HitEventHandler(int damage);
    protected void OnHitboxLeft(Node2D body) { }
}
""",
    "Player.cs": """\
public partial class Player : Actor
{
    [Signal] public delegate void DiedEventHandler();

    public override void _PhysicsProcess(double delta)
    {
        if (Input.IsActionPressed("jump")) { }
        if (Input.IsActionPressed("jupm")) { }
        var x = Input.GetAxis("move_left", "move_right");
        if (Input.IsActionJustPressed("ui_accept")) { }
        if (Input.IsActionJustPressed("dash")) { }
        GetNode<Sprite2D>("Sprite");
        GetNode("Sprite/Hitbox");
        GetNode("%Hitbox");
        GetNode("Hud/Score");
        GetNode("/root/Global");
        GetNode("Sprit");
        GetNode("Hud/Lives");
        GetNode("/root/Missing");
        other.GetNode("Elsewhere");
        GetTree().GetNodesInGroup("players");
        GetTree().GetNodesInGroup("pickups");
        GetTree().GetNodesInGroup("enemies");
        GetTree().CallGroup("allies", "Heal");
        IsInGroup("spawned");
        EmitSignal("Hit", 3);
        EmitSignal("Died");
        EmitSignal(SignalName.Died);
        EmitSignal("Dead");
        Connect("body_entered", callable);
        other.EmitSignal("Whatever");
    }

    public override void _Ready()
    {
        InputMap.AddAction("dash");
        AddToGroup("spawned");
    }
}
""",
    "Global.cs": "public partial class Global : Node { }\n",
}


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def godot(root: Path, make_config: Any, files: dict[str, str]) -> list[tuple[str, str, int]]:
    write(root, files)
    report = analyze_paths([root], root, make_config(OPT_IN), OPTIONS)
    return sorted(
        (f.rule_id, f.path, f.span.line) for f in report.findings if f.rule_id.startswith("GODOT")
    )


def test_the_names_a_script_writes_are_collected() -> None:
    text = PROJECT["Player.cs"]
    facts = extract_csharp_facts(SourceText.from_text(text), "Player.cs")
    by_kind: dict[str, list[str]] = {}
    for use in facts.godot:
        by_kind.setdefault(use.kind, []).append(use.name)
    assert by_kind[GODOT_SIGNAL_DECLARED] == ["Died"]
    assert by_kind[GODOT_ACTION] == ["jump", "jupm", "move_left", "move_right", "ui_accept", "dash"]
    assert "Elsewhere" not in by_kind[GODOT_NODE_PATH]  # another node's path
    assert by_kind[GODOT_GROUP_READ] == ["players", "pickups", "enemies", "allies", "spawned"]
    assert by_kind[GODOT_SIGNAL_USE] == ["Hit", "Died", "Dead", "body_entered"]
    assert all(use.owner == "Player" for use in facts.godot)


def test_names_the_project_does_not_define(empty_root: Path, make_config: Any) -> None:
    assert godot(empty_root, make_config, PROJECT) == [
        ("GODOT001", "Player.cs", 8),  # jupm
        ("GODOT001", "Player.cs", 9),  # move_right
        ("GODOT002", "Player.cs", 17),  # Sprit
        ("GODOT002", "Player.cs", 18),  # Hud/Lives, inside the instanced scene
        ("GODOT002", "Player.cs", 19),  # /root/Missing, not an autoload
        ("GODOT003", "Player.cs", 1),  # OnHitboxEntered
        ("GODOT004", "Player.cs", 23),  # enemies
        ("GODOT004", "Player.cs", 24),  # allies
        ("GODOT005", "Player.cs", 29),  # Dead
    ]


def test_the_messages_say_where(empty_root: Path, make_config: Any) -> None:
    write(empty_root, PROJECT)
    report = analyze_paths([empty_root], empty_root, make_config(OPT_IN), OPTIONS)
    messages = {
        (f.rule_id, f.span.line): (f.message, f.severity)
        for f in report.findings
        if f.rule_id.startswith("GODOT")
    }
    message, severity = messages[("GODOT001", 8)]
    assert message.startswith("input action 'jupm' is not in project.godot's [input] section")
    assert severity == "warning"
    message, severity = messages[("GODOT002", 17)]
    assert "'Sprit' does not exist in Main.tscn (script on .)" in message
    assert severity == "review"
    message, _severity = messages[("GODOT003", 1)]
    assert "Main.tscn connects 'body_entered' (from Sprite/Hitbox) to OnHitboxEntered" in message
    assert messages[("GODOT004", 23)][1] == "review"
    assert "use SignalName.Dead" in messages[("GODOT005", 29)][0]


def test_a_partial_run_or_an_unreadable_scene_judges_nothing(
    empty_root: Path, make_config: Any
) -> None:
    write(empty_root, PROJECT)
    config = make_config(OPT_IN)
    partial = analyze_paths([empty_root / "Player.cs"], empty_root, config, OPTIONS)
    assert [f for f in partial.findings if f.rule_id.startswith("GODOT")] == []
    (empty_root / "Broken.tscn").write_bytes(b"[gd_scene format=3]\n\xff\n")
    report = analyze_paths([empty_root], empty_root, config, OPTIONS)
    assert [f for f in report.findings if f.rule_id.startswith("GODOT")] == []


def test_no_project_and_no_scene_judges_nothing(empty_root: Path, make_config: Any) -> None:
    files = {"Player.cs": PROJECT["Player.cs"], "Actor.cs": PROJECT["Actor.cs"]}
    assert godot(empty_root, make_config, files) == []


def test_a_class_split_over_partial_files(empty_root: Path, make_config: Any) -> None:
    files = dict(PROJECT)
    files["PlayerSignals.cs"] = (
        "public partial class Player\n{\n    [Signal] public delegate void DeadEventHandler();\n"
        "    private void OnHitboxEntered(Node2D body) { }\n}\n"
    )
    found = godot(empty_root, make_config, files)
    assert ("GODOT003", "Player.cs", 1) not in found
    assert ("GODOT005", "Player.cs", 29) not in found


def test_the_rules_can_be_switched_off(empty_root: Path, make_config: Any) -> None:
    write(empty_root, PROJECT)
    config = make_config(OPT_IN + "\n[tool.shockharness.rules.godot_names]\nenabled = false\n")
    report = analyze_paths([empty_root], empty_root, config, OPTIONS)
    assert [f for f in report.findings if f.rule_id.startswith("GODOT")] == []
