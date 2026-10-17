"""VERIFY003 without a base revision: a rule switched off since the configuration a person
last accepted (spec 21.1 decision 35).

``check`` and the edit hook compare the working tree's ShockHarness configuration with the
**accepted configuration**:

* the configuration at the merge base of ``HEAD`` and ``origin/HEAD``, when the
  repository has ``origin/HEAD``; else
* the configuration at ``HEAD``; else, when there is no commit yet or that revision has no
  ShockHarness configuration,
* what ``shockharness init`` writes for the configured profile (the strict defaults with
  the test exemption, for the strict profile).

Every loosening (``loosening.py``) except a catch boundary naming one file
(``loosening.is_remedy``) switches a rule off and is reported at
``rules.verification.rule_switching_severity``, the strictest of the working and the
accepted configuration's, so a change cannot lower the severity of the finding reporting
it. A person accepts the change by committing it (on a branch, by merging it).

Both sides are loaded from their files with no command-line overrides and no
``--policy``: a ``--profile`` flag is not a configuration change, and a loosening the
policy file blocks is reported as a policy attempt. Outside a git repository nothing can
be committed, so nothing is compared and the coverage block says so.
"""

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.config import (
    DEDICATED_FILENAME,
    TIER_CLI,
    EffectiveConfig,
    load_config,
    render_profile_config_toml,
)
from shockharness.constants import COMMIT_SHORT_HEX
from shockharness.errors import ConfigError
from shockharness.findings import Finding
from shockharness.history.git import (
    RepositoryLocation,
    committed_paths,
    export_paths,
    locate_repository,
    run_git_text,
)
from shockharness.loosening import is_remedy, loosenings
from shockharness.rules.policy_integrity import (
    CONFIG_CANDIDATES,
    FIRST_LINE,
    USER_TIERS,
    fingerprinted,
    policy_finding,
    read_text,
    strictest_verification,
    toml_key_line,
)
from shockharness.rules.registry import VERIFICATION_SECTION

DEFAULT_BRANCH = "origin/HEAD"
STATUS_COMPARED = "compared"
STATUS_NOT_COMPARED = "not_compared"
STATUS_DISABLED = "disabled"
STATUS_UNKNOWN = "unknown"
SCOPE = "configuration"


@dataclass(frozen=True)
class AcceptedResult:
    findings: tuple[Finding, ...]  # fingerprinted
    # status, accepted (where the accepted configuration came from, "" when none was
    # read) and reason (why it was not compared, "" when it was).
    coverage: dict[str, Any]


@dataclass(frozen=True)
class Accepted:
    """The accepted configuration (None with ``error`` when it could not be loaded) and a
    phrase naming where it came from."""

    config: EffectiveConfig | None
    error: str | None
    where: str


def _commit(root: Path, revision: str) -> str | None:
    text, _error = run_git_text(
        root, ["rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"]
    )
    if text is None:
        return None
    return text.strip()


def accepted_revision(root: Path) -> tuple[str | None, str]:
    """(commit, phrase) of the revision holding the accepted configuration; (None, why)
    when the repository has no commit yet."""
    default = _commit(root, DEFAULT_BRANCH)
    if default is not None:
        text, _error = run_git_text(root, ["merge-base", "HEAD", default])
        if text is not None:
            base = text.strip()
            return base, f"the merge base with {DEFAULT_BRANCH} ({base[:COMMIT_SHORT_HEX]})"
    head = _commit(root, "HEAD")
    if head is not None:
        return head, f"HEAD ({head[:COMMIT_SHORT_HEX]})"
    return None, "no commit yet"


def _load(root: Path, explicit: Path | None) -> tuple[EffectiveConfig | None, str | None]:
    # Boundary (declared in .shockharness.toml): a committed configuration is external
    # input; an invalid one makes the comparison unknown, never a crash or a pass.
    try:
        config = load_config(root, explicit)
    except ConfigError as exc:
        return None, str(exc)
    return config, None


def _init_config(profile: str) -> EffectiveConfig:
    """What ``shockharness init --profile PROFILE`` writes, loaded."""
    with tempfile.TemporaryDirectory(prefix="shockharness-") as directory:
        path = Path(directory) / DEDICATED_FILENAME
        path.write_text(render_profile_config_toml(profile), encoding="utf-8")
        return load_config(Path(directory), None)


def _names(location: RepositoryLocation, explicit: str | None) -> list[str]:
    """The configuration files to look for at the revision, relative to the toplevel."""
    if explicit is not None:
        return [explicit]
    return [location.prefix + name for name in CONFIG_CANDIDATES]


def _committed_config(
    location: RepositoryLocation, commit: str, explicit: str | None
) -> tuple[bool, EffectiveConfig | None, str | None]:
    """(found, configuration, error) at ``commit``: found is False when the revision has
    no ShockHarness configuration file."""
    present, error = committed_paths(location.toplevel, commit, _names(location, explicit))
    if present is None:
        return True, None, error
    if len(present) == 0:
        return False, None, None
    with tempfile.TemporaryDirectory(prefix="shockharness-") as directory:
        exported = Path(directory)
        error = export_paths(location.toplevel, commit, present, exported)
        if error is not None:
            return True, None, error
        explicit_path: Path | None = None
        if explicit is not None:
            explicit_path = exported / explicit
        config, error = _load(exported / location.prefix, explicit_path)
    if config is None:
        return True, None, error
    if config.source.tier not in USER_TIERS:
        return False, None, None  # a pyproject.toml without [tool.shockharness]
    return True, config, None


def _accepted(
    location: RepositoryLocation, root: Path, explicit: str | None, profile: str
) -> Accepted:
    commit, where = accepted_revision(root)
    init_where = f"what `shockharness init` writes for the {profile} profile"
    if commit is None:
        return Accepted(_init_config(profile), None, f"{init_where} (no commit yet)")
    found, config, error = _committed_config(location, commit, explicit)
    if not found:
        return Accepted(_init_config(profile), None, f"{init_where} ({where} has no configuration)")
    return Accepted(config, error, where)


def _explicit_in_repository(
    location: RepositoryLocation, working: EffectiveConfig
) -> tuple[bool, str | None]:
    """(comparable, the explicit --config path relative to the toplevel, or None)."""
    if working.source.tier != TIER_CLI:
        return True, None
    source = Path(working.source.path).resolve()
    toplevel = location.toplevel.resolve()
    if not source.is_relative_to(toplevel):
        return False, None
    return True, source.relative_to(toplevel).as_posix()


def _anchor(root: Path, working: EffectiveConfig) -> tuple[str, str | None]:
    source = Path(working.source.path)
    text, _error = read_text(source)
    if source.resolve().is_relative_to(root.resolve()):
        return source.resolve().relative_to(root.resolve()).as_posix(), text
    return source.name, text


def _findings(
    root: Path, working: EffectiveConfig, accepted: EffectiveConfig, where: str, severity: str
) -> list[Finding]:
    path, text = _anchor(root, working)
    found: list[Finding] = []
    for item in loosenings(
        accepted.values, accepted.deviations, working.values, working.deviations
    ):
        if is_remedy(item, working.values):
            continue
        line = FIRST_LINE
        if text is not None:
            line = toml_key_line(text, item.key)
        message = (
            f"{item.message}: this switches a rule off since {where}. Switching a rule off "
            "is the user's decision: undo the change and fix the findings, or stop and ask "
            "the user, quoting this line and your reason; do not commit it yourself"
        )
        found.append(
            policy_finding(
                path, line, message, f"since accepted: {item.message}", SCOPE, None, severity
            )
        )
    return found


def _not_compared(reason: str) -> AcceptedResult:
    return AcceptedResult((), {"status": STATUS_NOT_COMPARED, "accepted": "", "reason": reason})


def accepted_policy(root: Path, explicit: Path | None) -> AcceptedResult:
    """VERIFY003 for every rule switched off in ``root``'s configuration since the
    accepted configuration; ``explicit`` is the run's ``--config`` path, if any."""
    working = load_config(root, explicit)
    if working.source.tier not in USER_TIERS:
        return _not_compared("no project configuration file: the bundled strict defaults apply")
    location, error = locate_repository(root)
    if location is None:
        return _not_compared(f"not a git repository, so nothing can be accepted ({error})")
    comparable, explicit_name = _explicit_in_repository(location, working)
    if not comparable:
        return _not_compared("the --config file is outside the repository")
    accepted = _accepted(location, root, explicit_name, str(working.values["profile"]))
    current = working.section(VERIFICATION_SECTION)
    base: Mapping[str, Any] | None = None
    if accepted.config is not None:
        base = accepted.config.section(VERIFICATION_SECTION)
    settings = strictest_verification(current, base)
    coverage: dict[str, Any] = {"status": STATUS_COMPARED, "accepted": accepted.where, "reason": ""}
    if settings["enabled"] is not True:
        disabled = "rules.verification.enabled = false"
        return AcceptedResult((), {**coverage, "status": STATUS_DISABLED, "reason": disabled})
    if accepted.config is None:
        return _unknown(root, working, accepted, coverage, str(settings["rule_switching_severity"]))
    findings = _findings(
        root, working, accepted.config, accepted.where, str(settings["rule_switching_severity"])
    )
    return AcceptedResult(fingerprinted(findings), coverage)


def _unknown(
    root: Path,
    working: EffectiveConfig,
    accepted: Accepted,
    coverage: Mapping[str, Any],
    severity: str,
) -> AcceptedResult:
    """The accepted configuration could not be loaded: one unknown finding, never a pass."""
    path, _text = _anchor(root, working)
    finding = policy_finding(
        path,
        FIRST_LINE,
        f"the configuration accepted at {accepted.where} could not be loaded, so whether "
        "the working configuration switches a rule off cannot be established",
        "accepted configuration unreadable",
        SCOPE,
        str(accepted.error),
        severity,
    )
    return AcceptedResult(
        fingerprinted([finding]), {**coverage, "status": STATUS_UNKNOWN, "reason": accepted.error}
    )
