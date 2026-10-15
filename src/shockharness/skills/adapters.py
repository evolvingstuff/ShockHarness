"""Where each supported agent expects skills (the adapter table).

The skill files themselves are identical for every agent; only the destination
differs. Paths were checked against each agent's own documentation on the date
recorded in ``documentation``; ``generic`` writes wherever ``--project DIR`` says
and prints the pointer line for the agent's instruction file.
"""

from dataclasses import dataclass
from pathlib import Path

from shockharness.errors import UsageError
from shockharness.skills import SKILL_NAMES

AGENT_CLAUDE = "claude"
AGENT_CODEX = "codex"
AGENT_GENERIC = "generic"


@dataclass(frozen=True)
class Adapter:
    agent: str
    # Skills directory below the project root; None means "--project DIR is the directory".
    project_subdir: str | None
    # Skills directory below the home directory; None means --user is not supported.
    user_subdir: str | None
    # How the agent finds the files once written (printed after install).
    discovery: str
    # The documentation the paths were verified against, with the verification date.
    documentation: str


ADAPTERS: tuple[Adapter, ...] = (
    Adapter(
        agent=AGENT_CLAUDE,
        project_subdir=".claude/skills",
        user_subdir=".claude/skills",
        discovery=(
            "Claude Code loads .claude/skills/<name>/SKILL.md from the project and "
            "~/.claude/skills/<name>/SKILL.md from the home directory automatically."
        ),
        documentation=(
            "https://code.claude.com/docs/en/skills (project .claude/skills, user "
            "~/.claude/skills; verified 2026-10-14)"
        ),
    ),
    Adapter(
        agent=AGENT_CODEX,
        project_subdir=".agents/skills",
        user_subdir=".agents/skills",
        discovery=(
            "Codex scans .agents/skills in the working directory and every parent up to "
            "the repository root, and $HOME/.agents/skills, automatically."
        ),
        documentation=(
            "https://developers.openai.com/codex/skills (redirects to "
            "https://learn.chatgpt.com/docs/build-skills; project $REPO_ROOT/.agents/skills, "
            "user $HOME/.agents/skills; verified 2026-10-14)"
        ),
    ),
    Adapter(
        agent=AGENT_GENERIC,
        project_subdir=None,
        user_subdir=None,
        discovery=(
            "No automatic discovery: add the printed pointer line to the agent's "
            "instruction file (for example AGENTS.md)."
        ),
        documentation="https://agentskills.io/specification (SKILL.md format; verified 2026-10-14)",
    ),
)
ADAPTERS_BY_AGENT: dict[str, Adapter] = {adapter.agent: adapter for adapter in ADAPTERS}
AGENTS: tuple[str, ...] = tuple(adapter.agent for adapter in ADAPTERS)


def get_adapter(agent: str) -> Adapter:
    if agent not in ADAPTERS_BY_AGENT:
        raise UsageError(f"unknown agent; known agents: {', '.join(AGENTS)}", agent)
    return ADAPTERS_BY_AGENT[agent]


def resolve_destination(adapter: Adapter, project_root: Path, user: bool, home: Path) -> Path:
    """The directory that will hold ``<name>/SKILL.md`` for every skill.

    ``project_root`` is ``--project`` (or the current directory for agents with a
    project subdirectory); ``home`` is the user's home directory when ``--user`` is set.
    """
    if user:
        if adapter.user_subdir is None:
            raise UsageError(
                f"--user is not supported for --agent {adapter.agent}: pass --project DIR",
                None,
            )
        return home / adapter.user_subdir
    if adapter.project_subdir is None:
        return project_root
    return project_root / adapter.project_subdir


def pointer_line(destination_as_given: Path) -> str:
    """The sentence a generic agent's instruction file needs so it finds the skills."""
    names = ", ".join(SKILL_NAMES)
    return (
        "Before writing, fixing, refactoring or reviewing code, read the matching "
        f"ShockHarness skill in {destination_as_given.as_posix()}/<name>/SKILL.md ({names})."
    )
