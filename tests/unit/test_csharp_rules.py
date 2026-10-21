"""G3 part two: the per-file families on C# (spec 21.1 decision 47): MAGIC002-MAGIC005,
ASYNC001, STATE001, IMPORT001, PROCESS001, STUB002 and STUB003."""

from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OPT_IN = 'include = ["**/*.cs"]\n'


def run(config: EffectiveConfig, text: str) -> FileResult:
    return analyze_text("Game.cs", "csharp", text, config, OPTIONS)


def found(result: FileResult, rules: tuple[str, ...]) -> list[tuple[str, int]]:
    return [(f.rule_id, f.span.line) for f in result.findings if f.rule_id in rules]


GAME = "\n".join(
    [
        "using System.Diagnostics;",
        "using Moq;",
        "public partial class Game : Node {",
        "    public static Game Instance;",
        "    private static int _count;",
        "    private static readonly int Limit = 3;",
        '    static Game() { File.ReadAllText("settings.json"); }',
        "    public override void _Ready() {",
        "        Instance = this;",
        "        _count++;",
        "        Select(-1);",
        '        Process.Start("sh", $"-c {_command}");',
        '        OS.Execute("git", new[] { "pull" });',
        '        int timeout = int.Parse("30");',
        '        var indent = "    ".Length;',
        "        LoadAsync();",
        "        _ = LoadAsync();",
        "        Task.Run(Work);",
        "        var part = text.Substring(-1);",
        "    }",
        "    public bool CanInteract() => true;",
        "    int Find() { return -1; }",
        "    private async Task LoadAsync() { await Task.Delay(5); }",
        "    private void Work() { }",
        "    private void Select(int index) { }",
        "    private string _command;",
        "}",
        "",
    ]
)


def test_the_per_file_families_on_csharp(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, GAME)
    rules = (
        "MAGIC003",
        "MAGIC005",
        "ASYNC001",
        "STATE001",
        "IMPORT001",
        "PROCESS001",
        "STUB002",
        "STUB003",
    )
    assert found(result, rules) == [
        ("STUB002", 2),
        ("STATE001", 4),
        ("STATE001", 5),
        ("IMPORT001", 7),
        ("MAGIC003", 11),
        ("PROCESS001", 12),
        ("PROCESS001", 13),
        ("MAGIC005", 14),
        ("MAGIC005", 15),
        ("ASYNC001", 16),
        ("ASYNC001", 18),
        ("STUB003", 21),
        ("MAGIC003", 22),
    ]
    messages = {(f.rule_id, f.span.line): f.message for f in result.findings}
    assert messages[("STATE001", 4)].startswith("static field Instance is mutable shared state")
    assert "static initialization" in messages[("IMPORT001", 7)]
    assert "shell command built from data" in messages[("PROCESS001", 12)]
    assert "exit status" in messages[("PROCESS001", 13)]
    assert "its Task is created and thrown away" in messages[("ASYNC001", 16)]


def test_a_base_class_hook_default_is_not_stub003(empty_root: Path, make_config: Any) -> None:
    files = {
        "Interactable.cs": (
            "public class Interactable : Node { public virtual bool CanUse() => true; }\n"
        ),
        "Door.cs": "public class Door : Interactable { public override bool CanUse() => _open; }\n",
        "Chest.cs": (
            "public class Chest : Interactable { public override bool CanUse() => true; }\n"
        ),
    }
    for name, body in files.items():
        (empty_root / name).write_text(body, encoding="utf-8")
    report = analyze_paths([empty_root], empty_root, make_config(OPT_IN), OPTIONS)
    stub = sorted((f.path, f.message) for f in report.findings if f.rule_id == "STUB003")
    assert [path for path, _message in stub] == ["Chest.cs"]
    assert stub[0][1].startswith(
        "Chest.CanUse repeats Interactable.CanUse, which already answers yes"
    )


def test_repeated_compared_strings_are_magic002(empty_root: Path, make_config: Any) -> None:
    files = {
        "Mob.cs": 'class Mob { void A(string s) { if (s == "chasing") { } Set("chasing"); } }\n',
        "Ai.cs": 'class Ai { bool B(string s) => s == "chasing"; }\n',
    }
    for name, body in files.items():
        (empty_root / name).write_text(body, encoding="utf-8")
    report = analyze_paths([empty_root], empty_root, make_config(OPT_IN), OPTIONS)
    assert [(f.rule_id, f.path) for f in report.findings if f.rule_id == "MAGIC002"] == [
        ("MAGIC002", "Ai.cs")
    ]
