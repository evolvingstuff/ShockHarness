"""GODOT001-GODOT005 (milestone G4, decision 51): Godot names the project does not define.

The commonest silent failure in a Godot project is a misspelled name. ``Input.IsActionPressed
("jupm")`` is false forever; a renamed node makes ``GetNode("HUD/Score")`` fail; a renamed
method breaks a connection made in the editor. Godot reports each of these only at run
time, in the log, when that line runs. Here the names a C# script writes as strings
(ir/csharp_godot.py) are read against the project's files (godot_project.py):

* GODOT001: an input action that ``project.godot``'s ``[input]`` does not define and no
  code adds (``InputMap.AddAction``). Godot's own ``ui_*`` actions are defined.
* GODOT002: a node path that does not exist in a scene that attaches the script, relative
  to the node it is attached to (``..`` followed, one level into an instanced scene,
  ``%Unique`` names, ``/root/Name`` for an autoload). Review: a node added at run time is
  not in the scene file.
* GODOT003: an editor connection to a method the target script's class (its ``partial``
  files and project bases included) does not define.
* GODOT004: a group read (``GetNodesInGroup``, ``IsInGroup``, ``CallGroup``) that nothing
  adds a node to: no ``AddToGroup``, no ``groups=[...]`` in a scene, no ``[global_group]``.
  Review: a group can be added from a GDScript or an addon.
* GODOT005: a signal name given as a string (``EmitSignal("Hit")``, ``Connect("Hit", ...)``
  on the object itself) that the class does not declare (``[Signal] delegate void
  HitEventHandler``). An engine signal is snake_case (``body_entered``) and is not judged.

Judged only on a whole-project run whose scene and project files could all be read, for
the C# files under a ``project.godot``.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.findings import CONFIDENCE_APPROXIMATE, STATUS_VIOLATION, Finding
from shockharness.godot_project import GodotProject, GodotScene, SceneConnection, SceneNode
from shockharness.ir.model import (
    GODOT_ACTION,
    GODOT_ACTION_ADDED,
    GODOT_GROUP_ADDED,
    GODOT_GROUP_READ,
    GODOT_NODE_PATH,
    GODOT_SIGNAL_DECLARED,
    GODOT_SIGNAL_USE,
    ClassDecl,
    GodotNameUse,
    ReceiverClass,
    Span,
)
from shockharness.rules.registry import (
    GODOT001,
    GODOT002,
    GODOT003,
    GODOT004,
    GODOT005,
    RuleSpec,
)
from shockharness.source import SourceText

BUILT_IN_ACTION = "ui_"
ENGINE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # an engine signal or method: body_entered
SEPARATOR = "/"
ROOT = "."
PARENT = ".."
UNIQUE = "%"
ABSOLUTE_ROOT = "/root/"
CSHARP_SUFFIX = ".cs"
# The setting that holds each rule's severity.
SEVERITY_KEYS = {
    GODOT001.rule_id: "severity",
    GODOT002.rule_id: "godot002_severity",
    GODOT003.rule_id: "severity",
    GODOT004.rule_id: "godot004_severity",
    GODOT005.rule_id: "severity",
}


@dataclass(frozen=True)
class GodotFile:
    path: str
    applies: frozenset[str]
    source: SourceText
    uses: tuple[GodotNameUse, ...]
    classes: tuple[ReceiverClass, ...]
    declarations: tuple[ClassDecl, ...]


def _final(name: str) -> str:
    _head, _dot, last = name.rpartition(".")
    return last


def _leaf(path: str) -> str:
    _directory, _slash, name = path.rpartition(SEPARATOR)
    return name


def _stem(path: str) -> str:
    return _leaf(path).removesuffix(CSHARP_SUFFIX)


def _finding(rule: RuleSpec, severity: str, file: GodotFile, span: Span, message: str) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


# -- the project's classes -------------------------------------------------------------------


class _Classes:
    """The C# classes of a project by simple name, ``partial`` declarations merged: their
    methods, bases and declared signals."""

    def __init__(self, files: Sequence[GodotFile]) -> None:
        self.methods: dict[str, set[str]] = {}
        self.bases: dict[str, set[str]] = {}
        self.signals: dict[str, set[str]] = {}
        for file in files:
            for cls in file.classes:
                name = _final(cls.name)
                self.methods.setdefault(name, set()).update(cls.methods)
                self.bases.setdefault(name, set()).update(cls.bases)
            for use in file.uses:
                if use.kind == GODOT_SIGNAL_DECLARED and use.owner is not None:
                    self.signals.setdefault(_final(use.owner), set()).add(use.name)

    def lineage(self, name: str) -> list[str]:
        """The class and its project ancestors."""
        order: list[str] = []
        pending = [name]
        while len(pending) > 0:
            current = pending.pop()
            if current in order or current not in self.methods:
                continue
            order.append(current)
            pending.extend(sorted(self.bases[current]))
        return order

    def defines(self, name: str, method: str) -> bool:
        return any(method in self.methods[c] for c in self.lineage(name))

    def declares_signal(self, name: str, signal: str) -> bool:
        return any(c in self.signals and signal in self.signals[c] for c in self.lineage(name))


# -- node paths -----------------------------------------------------------------------------


def _join(base: str, path: str) -> str | None:
    """``path`` relative to the node at ``base``; ``None`` above the scene's root."""
    parts = [] if base == ROOT else base.split(SEPARATOR)
    for segment in path.split(SEPARATOR):
        if segment in ("", ROOT):
            continue
        if segment == PARENT:
            if len(parts) == 0:
                return None
            parts.pop()
        else:
            parts.append(segment)
    return SEPARATOR.join(parts) if len(parts) > 0 else ROOT


class _Scenes:
    def __init__(self, project: GodotProject) -> None:
        self.by_path = {scene.path: scene for scene in project.scenes}
        self.autoloads = {name for name, _path in project.autoloads}

    def attached(self, cls: str) -> list[tuple[GodotScene, SceneNode]]:
        """Where a class's script is attached: (scene, node)."""
        return [
            (scene, node)
            for scene in self.by_path.values()
            for node in scene.nodes
            if node.script is not None
            and node.script.endswith(CSHARP_SUFFIX)
            and _stem(node.script) == cls
        ]

    def exists(self, scene: GodotScene, base: str, path: str) -> bool:
        """Whether ``path`` names a node from the node at ``base``; unknown counts as yes."""
        if path.startswith(ABSOLUTE_ROOT):
            first = path[len(ABSOLUTE_ROOT) :].split(SEPARATOR, 1)[0]
            return first in self.autoloads
        if path.startswith(SEPARATOR):
            return True  # another absolute path: the tree at run time is not known
        if path.startswith(UNIQUE):
            name, _slash, rest = path[len(UNIQUE) :].partition(SEPARATOR)
            unique = [n for n in scene.nodes if n.unique and _leaf(n.path) == name]
            return len(unique) > 0 and (rest == "" or self.exists(scene, unique[0].path, rest))
        target = _join(base, path)
        if target is None:
            return True
        return self._in_scene(scene, target)

    def _in_scene(self, scene: GodotScene, target: str) -> bool:
        nodes = {node.path: node for node in scene.nodes}
        if target in nodes:
            return True
        parts = target.split(SEPARATOR)
        for cut in reversed(range(1, len(parts))):
            prefix = SEPARATOR.join(parts[:cut])
            if prefix not in nodes:
                continue
            instance = nodes[prefix].instance
            if instance is None or instance not in self.by_path:
                return instance is not None  # an instanced scene that was not read
            inner = {node.path for node in self.by_path[instance].nodes}
            return SEPARATOR.join(parts[cut:]) in inner
        return False


# -- the checks -----------------------------------------------------------------------------


def _defined(files: Sequence[GodotFile], project: GodotProject) -> tuple[set[str], set[str]]:
    """The actions and groups the project defines: its files, and what code adds."""
    actions = set(project.input_actions)
    groups = set(project.global_groups)
    groups.update(g for scene in project.scenes for node in scene.nodes for g in node.groups)
    for file in files:
        for use in file.uses:
            if use.kind == GODOT_ACTION_ADDED:
                actions.add(use.name)
            elif use.kind == GODOT_GROUP_ADDED:
                groups.add(use.name)
    return actions, groups


class _Judge:
    def __init__(
        self, files: Sequence[GodotFile], project: GodotProject, settings: Mapping[str, Any]
    ) -> None:
        self.project = project
        self.settings = settings
        self.classes = _Classes(files)
        self.scenes = _Scenes(project)
        self.actions, self.groups = _defined(files, project)
        self.found: dict[str, list[Finding]] = {}

    def add(self, rule: RuleSpec, file: GodotFile, span: Span, message: str) -> None:
        if rule.rule_id in file.applies:
            severity = str(self.settings[SEVERITY_KEYS[rule.rule_id]])
            self.found.setdefault(file.path, []).append(
                _finding(rule, severity, file, span, message)
            )

    def uses(self, file: GodotFile) -> None:
        for use in file.uses:
            if use.kind == GODOT_ACTION and not self._action(use.name):
                self.add(GODOT001, file, use.span, self._action_message(use.name))
            elif use.kind == GODOT_GROUP_READ and use.name not in self.groups:
                self.add(GODOT004, file, use.span, _group_message(use.name))
            elif use.kind == GODOT_SIGNAL_USE and use.owner is not None:
                self._signal(file, use, _final(use.owner))
            elif use.kind == GODOT_NODE_PATH and use.owner is not None:
                self._node_path(file, use, _final(use.owner))

    def _action(self, name: str) -> bool:
        return name.startswith(BUILT_IN_ACTION) or name in self.actions

    def _action_message(self, name: str) -> str:
        where = _project_file(self.project)
        return (
            f"input action {name!r} is not in {where}'s [input] section and no code adds it "
            "(InputMap.AddAction): Input reads it as never pressed"
        )

    def _signal(self, file: GodotFile, use: GodotNameUse, cls: str) -> None:
        if ENGINE_NAME.match(use.name) is not None or cls not in self.classes.methods:
            return
        if self.classes.declares_signal(cls, use.name):
            return
        self.add(
            GODOT005,
            file,
            use.span,
            f"signal {use.name!r} is not declared by {cls} or a project base "
            f"([Signal] delegate void {use.name}EventHandler): Godot reports an error when "
            f"this runs; use SignalName.{use.name} so the compiler checks the name",
        )

    def _node_path(self, file: GodotFile, use: GodotNameUse, cls: str) -> None:
        missing = [
            f"{scene.path} (script on {node.path})"
            for scene, node in self.scenes.attached(cls)
            if not self.scenes.exists(scene, node.path, use.name)
        ]
        if len(missing) == 0:
            return
        self.add(
            GODOT002,
            file,
            use.span,
            f"node path {use.name!r} does not exist in {', '.join(missing)}, where {cls}'s "
            "script is attached: GetNode fails there unless the node is added at run time",
        )

    def connections(self, files: Sequence[GodotFile]) -> None:
        anchors = _anchors(files)
        for scene in self.project.scenes:
            scripts = _csharp_scripts(scene)
            for connection in scene.connections:
                if connection.target in scripts:
                    self._connection(scene, connection, scripts[connection.target], anchors)

    def _connection(
        self,
        scene: GodotScene,
        connection: SceneConnection,
        cls: str,
        anchors: Mapping[str, tuple[GodotFile, Span]],
    ) -> None:
        method = connection.method
        if ENGINE_NAME.match(method) is not None or cls not in self.classes.methods:
            return
        if self.classes.defines(cls, method) or cls not in anchors:
            return
        file, span = anchors[cls]
        self.add(
            GODOT003,
            file,
            span,
            f"{scene.path} connects {connection.signal!r} (from {connection.source}) to "
            f"{method}, which {cls} does not define: the connection fails when the scene loads",
        )


def _csharp_scripts(scene: GodotScene) -> dict[str, str]:
    """Each node of the scene with a C# script: its path to the script's class."""
    return {
        node.path: _stem(node.script)
        for node in scene.nodes
        if node.script is not None and node.script.endswith(CSHARP_SUFFIX)
    }


def _project_file(project: GodotProject) -> str:
    if project.directory in ("", ROOT):
        return "project.godot"
    return f"{project.directory}/project.godot"


def _group_message(name: str) -> str:
    return (
        f"group {name!r} is read but nothing adds a node to it (no AddToGroup, no "
        "groups=[...] in a scene, no [global_group]): the read finds nothing"
    )


def _declared(file: GodotFile) -> set[str]:
    return {_final(d.name) for d in file.declarations}


def _anchors(files: Sequence[GodotFile]) -> dict[str, tuple[GodotFile, Span]]:
    """Where each class is declared: the file named after it first (Godot's own file)."""
    found: dict[str, tuple[GodotFile, Span]] = {}
    for file in sorted(files, key=lambda f: (_stem(f.path) not in _declared(f), f.path)):
        for declaration in file.declarations:
            name = _final(declaration.name)
            if name not in found:
                found[name] = (file, declaration.span)
    return found


def _owner(path: str, directories: Sequence[str]) -> str | None:
    for directory in directories:
        if directory in ("", ROOT) or path.startswith(directory + SEPARATOR):
            return directory
    return None


def run_godot_names(
    files: Sequence[GodotFile], projects: Sequence[GodotProject], settings: Mapping[str, Any]
) -> Mapping[str, list[Finding]]:
    if len(projects) == 0 or any(len(p.problems) > 0 for p in projects):
        return {}
    directories = sorted((p.directory for p in projects), key=len, reverse=True)
    found: dict[str, list[Finding]] = {}
    for project in projects:
        mine = [f for f in files if _owner(f.path, directories) == project.directory]
        judge = _Judge(mine, project, settings)
        for file in mine:
            judge.uses(file)
        judge.connections(mine)
        for path, findings in judge.found.items():
            found.setdefault(path, []).extend(findings)
    return found
