"""G3: the Godot project model read from project.godot, .tscn and .tres files."""

from pathlib import Path

from shockharness.globs import compile_globset
from shockharness.godot_project import (
    SceneConnection,
    SceneNode,
    load_godot_projects,
    parse_resource,
)

EXCLUDE = compile_globset(["**/.godot/**", "**/.git/**"])

PROJECT = """\
; Engine configuration file.
config_version=5

[application]

config/name="Labyrinth"
config/description="A game; with a semicolon
and a second line"
run/main_scene="uid://main0001"

[autoload]

Global="*res://Global.cs"
Music="*uid://music001"

[input]

jump={
"deadzone": 0.2,
"events": [Object(InputEventKey,"keycode":32)]
}
fire={
"deadzone": 0.5,
"events": []
}
"""

MAIN = """\
[gd_scene load_steps=4 format=3 uid="uid://main0001"]

[ext_resource type="Script" uid="uid://script01" path="res://Main.cs" id="1_main"]
[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="2_player"]

[node name="Main" type="Node2D"]
script = ExtResource("1_main")

[node name="Player" parent="." groups=["actors", "player"] instance=ExtResource("2_player")]

[node name="Score" type="Label" parent="Player"]
text = "[b]score[/b]"

[connection signal="Hit" from="Player" to="." method="GameOver"]
[connection signal="timeout" from="MobTimer" to="." method="OnMobTimerTimeout" flags=3]
"""

PLAYER = """\
[gd_scene format=3]

[ext_resource type="Script" path="res://Player.cs" id="1"]

[sub_resource type="Animation" id="Animation_1"]
tracks/0/type = "method"
tracks/0/keys = {
"times": PackedFloat32Array(0.5),
"values": [{
"args": [],
"method": &"Die"
}]
}

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1")
"""


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def test_sections_keep_multiline_values_and_strings_with_separators() -> None:
    sections = parse_resource(PROJECT)
    assert [s.tag for s in sections] == ["", "application", "autoload", "input"]
    application = sections[1].properties
    assert application["config/description"] == "A game; with a semicolon\nand a second line"
    assert application["run/main_scene"] == "uid://main0001"
    assert list(sections[3].properties) == ["jump", "fire"]
    header = parse_resource(MAIN)[4]
    assert header.tag == "node" and header.attributes["groups"] == '["actors", "player"]'


def test_a_project_reads_scenes_scripts_connections_tracks_and_uids(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "game/project.godot": PROJECT,
            "game/scenes/Main.tscn": MAIN,
            "game/scenes/Player.tscn": PLAYER,
            "game/Music.tscn": (
                '[gd_scene format=3 uid="uid://music001"]\n[node name="Music" type="Node"]\n'
            ),
            "game/Global.cs.uid": "uid://global01\n",
            "game/.godot/editor/cache.tscn": '[gd_scene format=3]\n[node name="X" type="Node"]\n',
            "other/project.godot": "config_version=5\n",
        },
    )
    projects = {p.directory: p for p in load_godot_projects(tmp_path, EXCLUDE)}
    assert sorted(projects) == ["game", "other"]
    game = projects["game"]
    assert game.main_scene == "game/scenes/Main.tscn"
    assert game.autoloads == (("Global", "game/Global.cs"), ("Music", "game/Music.tscn"))
    assert game.input_actions == ("jump", "fire")
    assert game.problems == ()
    scenes = {s.path: s for s in game.scenes}
    assert sorted(scenes) == ["game/Music.tscn", "game/scenes/Main.tscn", "game/scenes/Player.tscn"]
    main = scenes["game/scenes/Main.tscn"]
    assert main.scripts == ("game/Main.cs",)
    assert main.nodes == (
        SceneNode(".", "game/Main.cs", None, ()),
        SceneNode("Player", None, "game/scenes/Player.tscn", ("actors", "player")),
        SceneNode("Player/Score", None, None, ()),
    )
    assert main.connections == (
        SceneConnection("Hit", "Player", ".", "GameOver", 14),
        SceneConnection("timeout", "MobTimer", ".", "OnMobTimerTimeout", 15),
    )
    assert scenes["game/scenes/Player.tscn"].track_methods == ("Die",)
    assert ("uid://script01", "game/Main.cs") in main.uids
    assert projects["other"].scenes == ()


def test_an_unreadable_scene_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    write(tmp_path, {"project.godot": "config_version=5\n"})
    (tmp_path / "Broken.tscn").write_bytes(b"[gd_scene format=3]\n\xff\xfe\n")
    (project,) = load_godot_projects(tmp_path, EXCLUDE)
    assert project.directory == "."
    assert project.scenes == ()
    assert len(project.problems) == 1 and "Broken.tscn" in project.problems[0]
