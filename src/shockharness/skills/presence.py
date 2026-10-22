"""Which coding agents work in a project, and whether ShockHarness skills reach them.

An agent that adopts ShockHarness by running its commands never reads the README's setup
guide, so the skills have to reach it through the commands themselves: ``init`` installs
them for every agent it finds in the project, ``skills install`` adds a pointer line to
that agent's instruction file, and ``check`` prints one line when a configured project has
no skills installed for an agent that works in it (``skills.notify_missing = false``
records that the repository wants none).

An agent is found by what it keeps in the repository: Claude Code a ``.claude/`` directory
or a ``CLAUDE.md``; Codex, and the other agents that read ``AGENTS.md``, an ``.agents/``
directory or an ``AGENTS.md``. Skills count as installed for an agent when its project or
per-user skills directory holds a ShockHarness skills manifest.
"""

from dataclasses import dataclass
from pathlib import Path

from shockharness.errors import UsageError
from shockharness.skills.adapters import AGENT_CLAUDE, AGENT_CODEX, pointer_line
from shockharness.skills.install import MANIFEST_FILENAME, read_bytes, write_bytes

POINTER_ADDED = "added"
POINTER_PRESENT = "kept: it already points at the skills"
OPT_OUT = (
    "a repository that wants no skills sets notify_missing = false in [tool.shockharness.skills]"
)


@dataclass(frozen=True)
class KnownAgent:
    agent: str  # the --agent value
    name: str  # how a notice names it
    markers: tuple[str, ...]  # files or directories that show it works in a project
    instructions: str  # the instruction file the pointer line goes into
    skills_dir: str  # below the project and below the home directory (the adapter's)


KNOWN_AGENTS: tuple[KnownAgent, ...] = (
    KnownAgent(
        AGENT_CLAUDE, "Claude Code", (".claude", "CLAUDE.md"), "CLAUDE.md", ".claude/skills"
    ),
    KnownAgent(
        AGENT_CODEX,
        "Codex and the other agents that read AGENTS.md",
        (".agents", "AGENTS.md"),
        "AGENTS.md",
        ".agents/skills",
    ),
)


def known_agent(agent: str) -> KnownAgent:
    for known in KNOWN_AGENTS:
        if known.agent == agent:
            return known
    names = ", ".join(known.agent for known in KNOWN_AGENTS)
    raise UsageError(f"skills are found and pointed at only for {names}", agent)


def markers_found(project: Path, known: KnownAgent) -> list[str]:
    return [marker for marker in known.markers if (project / marker).exists()]


def detected_agents(project: Path) -> list[KnownAgent]:
    """The agents whose files are in ``project``, in ``KNOWN_AGENTS`` order."""
    return [known for known in KNOWN_AGENTS if len(markers_found(project, known)) > 0]


def skills_installed(project: Path, home: Path, known: KnownAgent) -> bool:
    places = (project / known.skills_dir, home / known.skills_dir)
    return any((place / MANIFEST_FILENAME).is_file() for place in places)


def install_command(agent: str) -> str:
    return f"shockharness skills install --agent {agent}"


def install_choices() -> str:
    """Every install command, each with the agents it is for."""
    return " or ".join(
        f"`{install_command(known.agent)}` for {known.name}" for known in KNOWN_AGENTS
    )


def _undetected_notice() -> str:
    return (
        "skills: none installed for this repository's coding agent; "
        f"run {install_choices()} ({OPT_OUT})"
    )


def missing_skills_notices(project: Path, home: Path) -> list[str]:
    """One line per agent that works in ``project`` with no ShockHarness skills installed;
    one line naming every install command when no agent's files are there and no skills
    are installed for any."""
    found = detected_agents(project)
    if len(found) == 0:
        if any(skills_installed(project, home, known) for known in KNOWN_AGENTS):
            return []
        return [_undetected_notice()]
    return [
        f"skills: none installed for {known.name}, which works here "
        f"({markers_found(project, known)[0]} found); run: {install_command(known.agent)} "
        f"({OPT_OUT})"
        for known in found
        if not skills_installed(project, home, known)
    ]


def add_pointer(project: Path, known: KnownAgent) -> tuple[Path, str]:
    """Append the pointer line to the agent's instruction file (created when absent),
    unless the file already names the skills directory. The skills are discovered
    without it; the line tells the agent to read the matching one before it writes."""
    path = project / known.instructions
    data = b""
    if path.is_file():
        data = read_bytes(path)
    if known.skills_dir.encode("utf-8") in data:
        return path, POINTER_PRESENT
    separator = b""
    if len(data) > 0:
        separator = b"\n\n"
        if data.endswith(b"\n"):
            separator = b"\n"
    line = pointer_line(Path(known.skills_dir)).encode("utf-8")
    write_bytes(path, data + separator + line + b"\n")
    return path, POINTER_ADDED
