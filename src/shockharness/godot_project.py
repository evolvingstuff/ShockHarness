"""Godot project model (milestone G3): what ``project.godot`` and the scene and resource
files (``.tscn``, ``.tres``) say about the code, read with the standard library.

A Godot project's callers, scripts and names live in these text files, not in the code:
the scripts each scene attaches to its nodes, the signal connections made in the editor
(``[connection signal="pressed" from="Button" to="." method="OnButtonPressed"]``), the
methods animation tracks call, the autoloads and the main scene. The format (Godot's
"text resource" format) is sections with a one-line header of ``key=value`` pairs and a
body of ``key = value`` properties, whose values are Variant literals that may span lines;
the reader only needs a string- and bracket-aware scanner and never evaluates a value.

Facts only: the rules (DEAD001/DEAD002 so far) decide what the model means. A file that
cannot be read is recorded as a problem; the rules then do not judge what it could have
named.
"""

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shockharness.globs import GlobSet

PROJECT_FILE = "project.godot"
RESOURCE_SUFFIXES = (".tscn", ".tres")
RES_PREFIX = "res://"
UID_PREFIX = "uid://"
UID_SUFFIX = ".uid"  # Godot 4.4+: the uid of a script or other file, in a file beside it
AUTOLOAD_SINGLETON = "*"
SCRIPT_TYPE = "Script"
ROOT_NODE = "."
PATH_SEPARATOR = "/"
QUOTE = '"'
ESCAPE = "\\"
ESCAPE_SEQUENCE_LENGTH = len(ESCAPE + QUOTE)  # a backslash and the character it escapes
OPENING = "([{"
CLOSING = ")]}"
COMMENT = ";"
HEADER_OPEN = "["
STRING_PREFIXES = ("&", "^")  # StringName and NodePath literals: &"name", ^"path"
EXT_RESOURCE_CALL = re.compile(r'^ExtResource\(\s*"(?P<id>[^"]*)"\s*\)$')
METHOD_TRACK_KEY = re.compile(r'"method"\s*:\s*[&]?"(?P<name>[^"]+)"')
HEADER_TAG = re.compile(r"^\[(?P<tag>[A-Za-z_][\w]*)")
APPLICATION = "application"
MAIN_SCENE = "run/main_scene"
AUTOLOAD = "autoload"
INPUT = "input"


# -- the text resource format --------------------------------------------------------------


@dataclass(frozen=True)
class ResourceSection:
    """One ``[tag ...]`` section: its header's ``key=value`` pairs and its body's
    properties, values as written (strings without their quotes). ``tag`` is "" for the
    properties before the first header (``config_version=5`` in ``project.godot``)."""

    tag: str
    line: int
    attributes: Mapping[str, str]
    properties: Mapping[str, str]


def _scan_value(text: str, start: int, stops: str) -> int:
    """The end of the value that starts at ``start``: a string, or text up to one of
    ``stops`` outside strings and brackets (a newline always stops at depth 0)."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == QUOTE:
            index = _string_end(text, index)
            continue
        if char in OPENING:
            depth += 1
        elif char in CLOSING:
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and (char == "\n" or char in stops):
            return index
        index += 1
    return index


def _string_end(text: str, quote: int) -> int:
    """The index just after the string literal opened at ``quote``."""
    index = quote + 1
    while index < len(text):
        if text[index] == ESCAPE:
            index += ESCAPE_SEQUENCE_LENGTH
            continue
        if text[index] == QUOTE:
            return index + 1
        index += 1
    return index


def unquote(value: str) -> str:
    """``"res://a.cs"`` -> ``res://a.cs`` (also ``&"name"`` and ``^"path"``); anything
    else unchanged."""
    stripped = value.strip()
    for prefix in STRING_PREFIXES:
        stripped = stripped.removeprefix(prefix)
    if (
        len(stripped) >= len(QUOTE + QUOTE)
        and stripped.startswith(QUOTE)
        and stripped.endswith(QUOTE)
    ):
        return stripped[len(QUOTE) : len(stripped) - len(QUOTE)].replace(ESCAPE + QUOTE, QUOTE)
    return value.strip()


def _header(text: str, start: int) -> tuple[str, dict[str, str], int]:
    """The tag and attributes of the header that opens at ``start``, and where it ends."""
    end = _scan_value(text, start + len(HEADER_OPEN), "]")
    inside = text[start + len(HEADER_OPEN) : end]
    tag, _space, rest = inside.strip().partition(" ")
    attributes: dict[str, str] = {}
    index = 0
    while index < len(rest):
        if rest[index].isspace():
            index += 1
            continue
        equals = rest.find("=", index)
        if equals < 0:
            break
        key = rest[index:equals].strip()
        value_end = _scan_value(rest, equals + 1, " \t")
        attributes[key] = unquote(rest[equals + 1 : value_end])
        index = value_end
    return tag, attributes, end + 1


class _Sections:
    """The sections read so far, and the one being filled."""

    def __init__(self) -> None:
        self.done: list[ResourceSection] = []
        self.tag = ""
        self.line = 1
        self.attributes: dict[str, str] = {}
        self.properties: dict[str, str] = {}

    def open(self, tag: str, line: int, attributes: dict[str, str]) -> None:
        self.close()
        self.tag, self.line, self.attributes, self.properties = tag, line, attributes, {}

    def close(self) -> None:
        if self.tag != "" or len(self.properties) > 0:
            self.done.append(ResourceSection(self.tag, self.line, self.attributes, self.properties))


def parse_resource(text: str) -> tuple[ResourceSection, ...]:
    """The sections of a ``project.godot``, ``.tscn`` or ``.tres`` file, in order."""
    sections = _Sections()
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char == COMMENT:
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
        elif char == HEADER_OPEN and (index == 0 or text[index - 1] == "\n"):
            tag, attributes, end = _header(text, index)
            sections.open(tag, text.count("\n", 0, index) + 1, attributes)
            index = end
        else:
            index = _property(text, index, sections.properties)
    sections.close()
    return tuple(sections.done)


def _property(text: str, start: int, properties: dict[str, str]) -> int:
    """Read ``key = value`` at ``start`` into ``properties``; where the next token starts."""
    equals = text.find("=", start)
    newline = text.find("\n", start)
    if equals < 0 or (newline >= 0 and newline < equals):
        return len(text) if newline < 0 else newline + 1  # not a property line: skip it
    key = text[start:equals].strip()
    end = _scan_value(text, equals + 1, "")
    properties[key] = unquote(text[equals + 1 : end])
    return end


# -- the project model -------------------------------------------------------------------


@dataclass(frozen=True)
class SceneNode:
    """A ``[node]``: its path in the scene (``.`` for the root, ``HUD/Score``), the script
    attached to it and the scene it instances, as project file paths when known."""

    path: str
    script: str | None
    instance: str | None
    groups: tuple[str, ...]


@dataclass(frozen=True)
class SceneConnection:
    """An editor connection: ``signal`` from the node at ``source`` calls ``method`` on
    the node at ``target`` (node paths in the scene)."""

    signal: str
    source: str
    target: str
    method: str
    line: int


@dataclass(frozen=True)
class GodotScene:
    """A ``.tscn`` or ``.tres`` file: its nodes, its connections, the methods its
    animation tracks call, and every script it names (``ext_resource type="Script"``)."""

    path: str
    nodes: tuple[SceneNode, ...]
    connections: tuple[SceneConnection, ...]
    track_methods: tuple[str, ...]
    scripts: tuple[str, ...]
    uids: tuple[
        tuple[str, str], ...
    ]  # (uid://..., project file path): its own and its ext_resources'


@dataclass(frozen=True)
class GodotProject:
    """One ``project.godot`` and the scene and resource files under its directory.
    Paths are relative to the analysis root, with ``/`` separators."""

    directory: str
    main_scene: str | None
    autoloads: tuple[tuple[str, str], ...]  # (name, project file path)
    input_actions: tuple[str, ...]
    scenes: tuple[GodotScene, ...]
    problems: tuple[str, ...]


def _project_path(directory: str, resource: str) -> str | None:
    """``res://scenes/a.tscn`` -> ``<directory>/scenes/a.tscn``; ``None`` for anything
    that is not a ``res://`` path (``uid://...``, ``user://...``)."""
    if not resource.startswith(RES_PREFIX):
        return None
    inner = resource[len(RES_PREFIX) :]
    if directory in ("", "."):
        return inner
    return f"{directory}{PATH_SEPARATOR}{inner}"


def _optional(mapping: Mapping[str, str], key: str) -> str | None:
    """An attribute or property a section may leave out (a root node has no ``parent``,
    most nodes no ``script``): absence is a normal state of the format, not a gap."""
    found: str | None = None
    if key in mapping:
        found = mapping[key]
    return found


def _node_path(attributes: Mapping[str, str]) -> str:
    name = _optional(attributes, "name")
    parent = _optional(attributes, "parent")
    if parent is None or name is None:
        return ROOT_NODE
    if parent == ROOT_NODE:
        return name
    return f"{parent}{PATH_SEPARATOR}{name}"


def _external(
    sections: Sequence[ResourceSection], directory: str, uids: list[tuple[str, str]]
) -> tuple[dict[str, str], list[str]]:
    """Each ``ext_resource`` id to its project file path, and the scripts among them;
    each ``uid`` an ``ext_resource`` gives is added to ``uids``."""
    by_id: dict[str, str] = {}
    scripts: list[str] = []
    for section in sections:
        if section.tag != "ext_resource" or "path" not in section.attributes:
            continue
        path = _project_path(directory, section.attributes["path"])
        if path is None or "id" not in section.attributes:
            continue
        uid = _optional(section.attributes, "uid")
        if uid is not None:
            uids.append((uid, path))
        by_id[section.attributes["id"]] = path
        if _optional(section.attributes, "type") == SCRIPT_TYPE:
            scripts.append(path)
    return by_id, scripts


def _referenced(value: str | None, external: Mapping[str, str]) -> str | None:
    """``ExtResource("1_abc")`` -> the file it names."""
    if value is None:
        return None
    match = EXT_RESOURCE_CALL.match(value.strip())
    if match is None or match.group("id") not in external:
        return None
    return external[match.group("id")]


def _groups(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(re.findall(r'"([^"]*)"', value))


def read_scene(path: str, text: str, directory: str) -> GodotScene:
    sections = parse_resource(text)
    uids: list[tuple[str, str]] = []
    if len(sections) > 0:
        own = _optional(sections[0].attributes, "uid")
        if own is not None:
            uids.append((own, path))
    external, scripts = _external(sections, directory, uids)
    nodes: list[SceneNode] = []
    connections: list[SceneConnection] = []
    for section in sections:
        if section.tag == "node":
            nodes.append(
                SceneNode(
                    path=_node_path(section.attributes),
                    script=_referenced(_optional(section.properties, "script"), external),
                    instance=_referenced(_optional(section.attributes, "instance"), external),
                    groups=_groups(_optional(section.attributes, "groups")),
                )
            )
        elif section.tag == "connection" and _complete(section.attributes):
            attributes = section.attributes
            connections.append(
                SceneConnection(
                    attributes["signal"],
                    attributes["from"],
                    attributes["to"],
                    attributes["method"],
                    section.line,
                )
            )
    tracks = tuple(sorted({m.group("name") for m in METHOD_TRACK_KEY.finditer(text)}))
    return GodotScene(path, tuple(nodes), tuple(connections), tracks, tuple(scripts), tuple(uids))


CONNECTION_KEYS = ("signal", "from", "to", "method")


def _complete(attributes: Mapping[str, str]) -> bool:
    return all(key in attributes for key in CONNECTION_KEYS)


def _settings(
    sections: Sequence[ResourceSection],
) -> tuple[str | None, list[tuple[str, str]], list[str]]:
    """The main scene, the autoloads (name, reference) and the input action names of a
    ``project.godot``, references as written (``res://...`` or ``uid://...``)."""
    main_scene: str | None = None
    autoloads: list[tuple[str, str]] = []
    actions: list[str] = []
    for section in sections:
        if section.tag == APPLICATION and MAIN_SCENE in section.properties:
            main_scene = section.properties[MAIN_SCENE]
        elif section.tag == AUTOLOAD:
            autoloads.extend(
                (name, value.removeprefix(AUTOLOAD_SINGLETON))
                for name, value in section.properties.items()
            )
        elif section.tag == INPUT:
            actions.extend(section.properties)
    return main_scene, autoloads, actions


def _resolve(reference: str | None, directory: str, uids: Mapping[str, str]) -> str | None:
    """A ``res://`` or ``uid://`` reference as a project file path, when known."""
    if reference is None:
        return None
    if reference.startswith(UID_PREFIX):
        found: str | None = None
        if reference in uids:
            found = uids[reference]
        return found
    return _project_path(directory, reference)


# -- reading the files -----------------------------------------------------------------------


def _read(path: Path) -> tuple[str | None, str | None]:
    """(text, problem): one of the two is set."""
    # Boundary (declared in .shockharness.toml): reading the project's scene files.
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read {path.name}: {exc}"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, f"{path.name} is not valid UTF-8: {exc}"
    return text, None


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _walk(root: Path, exclude: GlobSet) -> tuple[list[Path], list[Path], list[Path]]:
    """Every ``project.godot`` and every scene or resource file under ``root``, skipping
    what ``exclude`` prunes (the ``.godot`` cache, ``node_modules``)."""
    projects: list[Path] = []
    resources: list[Path] = []
    sidecars: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        here = Path(directory)
        subdirectories[:] = sorted(
            d for d in subdirectories if not exclude.prunes_directory(_relative(root, here / d))
        )
        for name in sorted(files):
            relative = _relative(root, here / name)
            if exclude.matches(relative):
                continue
            if name == PROJECT_FILE:
                projects.append(here / name)
            elif name.endswith(RESOURCE_SUFFIXES):
                resources.append(here / name)
            elif name.endswith(UID_SUFFIX):
                sidecars.append(here / name)
    return projects, resources, sidecars


def load_godot_projects(root: Path, exclude: GlobSet) -> tuple[GodotProject, ...]:
    """Every Godot project under ``root``, with the scene and resource files under its
    directory (a nested project's files belong to the nested one)."""
    project_files, resource_files, sidecars = _walk(root, exclude)
    directories = sorted((_relative(root, p.parent) for p in project_files), key=len, reverse=True)
    return tuple(
        _project(root, project_file, directories, (resource_files, sidecars))
        for project_file in project_files
    )


def _project(
    root: Path,
    project_file: Path,
    directories: Sequence[str],
    files: tuple[Sequence[Path], Sequence[Path]],
) -> GodotProject:
    resource_files, sidecars = files
    directory = _relative(root, project_file.parent)
    problems: list[str] = []
    scenes: list[GodotScene] = []
    uids: dict[str, str] = {}
    for resource in resource_files:
        relative = _relative(root, resource)
        if _owner(relative, directories) != directory:
            continue
        content, issue = _read(resource)
        if content is None:
            problems.append(f"{relative}: {issue}")
            continue
        scene = read_scene(relative, content, directory)
        scenes.append(scene)
        uids.update(scene.uids)
    for sidecar in sidecars:
        relative = _relative(root, sidecar)
        content, _issue = _read(sidecar)
        if _owner(relative, directories) == directory and content is not None:
            uids[content.strip()] = relative.removesuffix(UID_SUFFIX)
    text, problem = _read(project_file)
    sections: tuple[ResourceSection, ...] = ()
    if text is not None:
        sections = parse_resource(text)
    if problem is not None:
        problems.append(f"{directory}/{PROJECT_FILE}: {problem}")
    main_scene, autoloads, actions = _settings(sections)
    resolved = [(name, _resolve(ref, directory, uids)) for name, ref in autoloads]
    return GodotProject(
        directory,
        _resolve(main_scene, directory, uids),
        tuple((name, path) for name, path in resolved if path is not None),
        tuple(actions),
        tuple(scenes),
        tuple(problems),
    )


def _owner(relative: str, directories: Sequence[str]) -> str | None:
    """The deepest project directory a file is in (``directories`` deepest first)."""
    for directory in directories:
        if directory in ("", ".") or relative.startswith(directory + PATH_SEPARATOR):
            return directory
    return None
