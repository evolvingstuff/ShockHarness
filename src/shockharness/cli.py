"""Command-line interface.

Exit codes: 0 all gates pass; 1 policy violations; 2 invalid configuration or
invocation; 3 analyzer internal error or (in strict mode) unhandled parse
failure. Report generation is separate from the gate verdict: a JSON report is
written even when the gate fails.
"""

import argparse
import json
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import (
    analyze_paths,
    apply_baseline,
    check_contract_references,
    with_accepted_policy,
    with_history,
)
from shockharness.config import (
    DEDICATED_FILENAME,
    DEDICATED_FILENAMES,
    NO_OVERRIDES,
    PARSE_ERROR_POLICIES,
    PYPROJECT_FILENAME,
    SKILLS_KEY,
    TEST_EXEMPTION_RULES,
    USER_TIERS,
    CliOverrides,
    EffectiveConfig,
    load_config_with_overrides,
    render_profile_config_toml,
)
from shockharness.constants import (
    EXIT_INTERNAL_ERROR,
    EXIT_INVALID_CONFIG,
    EXIT_OK,
    JSON_INDENT,
)
from shockharness.contracts.catalog import SECTION_PATH as PROPERTY_CONTRACTS_SECTION
from shockharness.contracts.catalog import static_properties
from shockharness.contracts.install import CONTRACTS_MANIFEST, check_runtime, install_runtime
from shockharness.contracts.install import LANGUAGES as CONTRACT_LANGUAGES
from shockharness.contracts.sorry import sorry_count
from shockharness.errors import ShockHarnessError, UsageError
from shockharness.gate import GATE_ERROR, as_advisory, process_exit_code
from shockharness.gating.baseline import Baseline, build_baseline, load_baseline, render_baseline
from shockharness.gating.diff import DiffReport, diff_revisions, head_paths, with_metrics
from shockharness.history.hotspots import collect_history
from shockharness.hook import (
    EVENT_SESSION_START,
    EVENT_STOP,
    HOOK_AGENTS,
    HOOK_EVENTS,
    SEVERITY_ORDER,
    read_stdin,
    run_post_edit,
    write_result,
)
from shockharness.hook_stop import run_session_start, run_stop
from shockharness.inventory import build_inventory
from shockharness.inventory import render_text as render_inventory
from shockharness.output import json as json_output
from shockharness.output import sarif as sarif_output
from shockharness.output import text as text_output
from shockharness.report import Report
from shockharness.rules import registry
from shockharness.rules.policy_integrity import read_text
from shockharness.schema import PROFILE_STRICT, PROFILES
from shockharness.skills import SKILL_NAMES, shipped_frontmatter, skill_text
from shockharness.skills.adapters import (
    AGENT_CLAUDE,
    AGENT_GENERIC,
    AGENTS,
    get_adapter,
    pointer_line,
    resolve_destination,
)
from shockharness.skills.freshness import skills_drift
from shockharness.skills.install import (
    ACTION_NONE,
    HOOK_COMMAND,
    MANIFEST_FILENAME,
    STATUS_EDITED,
    STATUS_UP_TO_DATE,
    SkillsResult,
    hook_command,
    install_claude_hook,
    install_claude_stop_hook,
    install_skills,
    update_skills,
    write_lock,
)
from shockharness.skills.lock import lock_path, render_lock
from shockharness.skills.presence import (
    KNOWN_AGENTS,
    KnownAgent,
    add_pointer,
    detected_agents,
    install_choices,
    known_agent,
    missing_skills_notices,
    skills_installed,
)
from shockharness.version import __version__

PROGRAM = "shockharness"
FORMAT_TEXT = "text"
FORMAT_JSON = "json"
FORMAT_SARIF = "sarif"
FORMATS = (FORMAT_TEXT, FORMAT_JSON, FORMAT_SARIF)
WORKING_TREE_REVISION = "HEAD"
COMMAND_CHECK = "check"
COMMAND_SCAN = "scan"  # hidden alias of check, kept so Milestone A-D invocations keep working
COMMAND_VERSION = "version"
COMMAND_SKILLS = "skills"
COMMAND_CONTRACTS = "contracts"
COMMAND_HOOK = "hook"
HOOK_DEFAULT_FAIL_ON = "warning"
COMMAND_EXCEPTIONS = "exceptions"
INVENTORY_FORMATS = (FORMAT_TEXT, FORMAT_JSON)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Strict static-analysis quality gate: no silent failures, no implicit defaults, "
            "no magic numbers."
        ),
    )
    parser.add_argument("--version", action="version", version=version_string())
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    check = commands.add_parser(
        COMMAND_CHECK,
        help="analyze files and directories, print a report, exit with the gate status",
    )
    _add_check_arguments(check)
    # `scan` is the pre-Milestone-F name: same arguments, same behaviour. A subparser added
    # without `help` is accepted but not listed in --help, which is how it stays hidden.
    scan = commands.add_parser(COMMAND_SCAN)
    _add_check_arguments(scan)

    commands.add_parser(COMMAND_VERSION, help="print the tool version (same as --version)")

    exceptions = commands.add_parser(
        COMMAND_EXCEPTIONS,
        help="list every exception the code and configuration make: inline suppressions, "
        "configuration exceptions with their source, policy attempts, baseline contents "
        "(read-only; exit 0)",
    )
    exceptions.add_argument("paths", nargs="+", type=Path, help="files or directories to analyze")
    _add_config_arguments(exceptions)
    _add_cache_argument(exceptions)
    _add_baseline_argument(exceptions)
    exceptions.add_argument("--format", choices=INVENTORY_FORMATS, default=FORMAT_TEXT)
    exceptions.add_argument(
        "--output", type=Path, default=None, help="write the list here instead of stdout"
    )

    _add_hook_parser(commands)

    baseline = commands.add_parser("baseline", help="create a reviewed baseline of findings")
    baseline_commands = baseline.add_subparsers(
        dest="baseline_command", required=True, metavar="SUBCOMMAND"
    )
    create = baseline_commands.add_parser(
        "create", help="analyze PATH... and write every current finding's fingerprint"
    )
    create.add_argument("paths", nargs="+", type=Path, help="files or directories to analyze")
    _add_config_arguments(create)
    _add_analysis_arguments(create)
    create.add_argument("--output", type=Path, required=True, help="baseline file to write")
    create.add_argument("--force", action="store_true", help="overwrite an existing baseline file")

    diff = commands.add_parser(
        "diff", help="compare findings between two committed revisions (reporting only)"
    )
    _add_revision_arguments(diff, required=True)
    _add_config_arguments(diff)
    _add_analysis_arguments(diff)
    _add_output_arguments(diff)

    gate = commands.add_parser(
        "gate",
        help=(
            "exit 1 on new hard violations: between --base and --head, "
            "or in PATH... against a --baseline"
        ),
    )
    gate.add_argument("paths", nargs="*", type=Path, help="files or directories to analyze")
    _add_revision_arguments(gate, required=False)
    _add_config_arguments(gate)
    _add_analysis_arguments(gate)
    _add_cache_argument(gate)
    _add_output_arguments(gate)
    _add_baseline_argument(gate)
    _add_exit_zero_argument(gate)
    _add_summary_argument(gate)

    config = commands.add_parser("config", help="validate or print the effective configuration")
    config_commands = config.add_subparsers(
        dest="config_command", required=True, metavar="SUBCOMMAND"
    )
    validate = config_commands.add_parser("validate", help="exit 0 if the configuration is valid")
    _add_config_arguments(validate)
    effective = config_commands.add_parser(
        "effective", help="print the merged configuration with origins"
    )
    _add_config_arguments(effective)

    rules = commands.add_parser("rules", help="list or explain rules")
    rules_commands = rules.add_subparsers(dest="rules_command", required=True, metavar="SUBCOMMAND")
    rules_commands.add_parser("list", help="list every registered rule and its status")
    explain = rules_commands.add_parser("explain", help="print the full description of one rule")
    explain.add_argument("rule_id")

    _add_init_parser(commands)
    _add_skills_parser(commands)
    _add_contracts_parser(commands)
    return parser


def _add_init_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    init = commands.add_parser(
        "init",
        help=f"write a {DEDICATED_FILENAME} selecting a built-in profile and install the agent "
        "skills for the coding agents working in the project",
    )
    init.add_argument(
        "--profile",
        choices=PROFILES,
        default=PROFILE_STRICT,
        help="strict writes the bundled defaults in full; other profiles write a short file "
        "that selects the profile (default: strict)",
    )
    init.add_argument(
        "--path", type=Path, default=Path(DEDICATED_FILENAME), help="where to write the file"
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.add_argument(
        "--no-skills",
        action="store_true",
        help="write only the configuration; by default init also installs the agent skills "
        "for each coding agent whose files are in the project (.claude/ or CLAUDE.md: "
        "claude; .agents/ or AGENTS.md: codex) and adds a pointer line to its instruction file",
    )
    init.add_argument(
        "--agent",
        action="append",
        choices=tuple(known.agent for known in KNOWN_AGENTS),
        default=None,
        help="install the skills for this agent instead of the detected ones (repeatable)",
    )


def _add_skills_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    skills = commands.add_parser(
        COMMAND_SKILLS, help="install, update or inspect the bundled agent skills"
    )
    skills_commands = skills.add_subparsers(
        dest="skills_command", required=True, metavar="SUBCOMMAND"
    )
    skills_commands.add_parser("list", help="list the shipped skills with their descriptions")
    show = skills_commands.add_parser("show", help="print one shipped SKILL.md")
    show.add_argument("name", choices=SKILL_NAMES)
    _add_skills_install_parser(skills_commands)
    skills_update = skills_commands.add_parser(
        "update",
        help="rewrite unedited skill files from the installed package, keep edited ones",
    )
    _add_skills_destination_arguments(skills_update)
    skills_update.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 when any installed skill is stale, edited, missing, new "
        "or removed relative to the installed package",
    )


def _add_contracts_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    contracts = commands.add_parser(
        COMMAND_CONTRACTS,
        help="copy the property-contracts runtime file into a project (nothing is published)",
    )
    contracts_commands = contracts.add_subparsers(
        dest="contracts_command", required=True, metavar="SUBCOMMAND"
    )
    static = contracts_commands.add_parser(
        "static-properties",
        help='print the catalog\'s runtime = "static" properties as the list enable(...) takes',
    )
    static.add_argument(
        "--root", type=Path, default=Path.cwd(), help="project root (default: current directory)"
    )
    static.add_argument("--config", type=Path, default=None, help="explicit configuration file")
    install = contracts_commands.add_parser(
        "install",
        help=f"copy the runtime file to --dest and record it in {CONTRACTS_MANIFEST}; "
        "with --check, report installed copies that are edited, missing or stale",
    )
    install.add_argument("--language", choices=CONTRACT_LANGUAGES, help="the runtime's language")
    install.add_argument(
        "--dest", type=Path, help="where the file goes, relative to --project (app/contracts.py)"
    )
    install.add_argument(
        "--project", type=Path, default=Path.cwd(), help="project root (default: current directory)"
    )
    install.add_argument(
        "--force", action="store_true", help="replace a file that was edited or not installed here"
    )
    install.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 when an installed copy is edited, missing or stale",
    )


def _add_skills_install_parser(
    skills_commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    skills_install = skills_commands.add_parser(
        "install",
        help=f"write every skill and a {MANIFEST_FILENAME} manifest into the agent's directory",
    )
    _add_skills_destination_arguments(skills_install)
    skills_install.add_argument(
        "--force", action="store_true", help="replace skill files that already exist"
    )
    skills_install.add_argument(
        "--hook",
        action="store_true",
        help="--agent claude: also add an edit-time hook to the project's .claude/settings.json "
        "(PostToolUse on Edit/Write/MultiEdit runs `shockharness hook claude-code post-edit`, "
        "so the agent hears findings right after each edit); appended, never replacing hooks",
    )
    skills_install.add_argument(
        "--stop-hook",
        action="store_true",
        help="--agent claude: also add the finish-time gate to the project's "
        ".claude/settings.json (a Stop hook running `shockharness hook claude-code stop`, "
        "which keeps the agent working while the gate against the commit the session "
        "started from fails, and a SessionStart hook recording that commit); appended, "
        "never replacing hooks",
    )
    skills_install.add_argument(
        "--lock",
        action="store_true",
        help="with --hook or --stop-hook: write the project's configuration (catch "
        "boundaries aside) as a policy file under ~/.config/shockharness/locks/ and run the "
        "hooks with --policy, so "
        "the project can tighten the configuration but not loosen it; kept if it exists "
        "(--force rewrites it)",
    )


def _add_hook_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    hook = commands.add_parser(
        COMMAND_HOOK,
        help="edit-time feedback for a coding agent: analyze the file the agent just edited "
        "(the agent's hook JSON on stdin); exit 2 with the findings on stderr, else exit 0",
    )
    hook.add_argument("agent", choices=HOOK_AGENTS, help="the agent whose hook calls this")
    hook.add_argument(
        "event",
        choices=HOOK_EVENTS,
        help="post-edit: after Edit/Write/MultiEdit/Bash; stop: when the agent is about to "
        "end its turn (the finish-time gate); session-start: records the session's base",
    )
    _add_config_arguments(hook)
    _add_analysis_arguments(hook)
    _add_cache_argument(hook)
    hook.add_argument(
        "--fail-on",
        choices=SEVERITY_ORDER,
        default=HOOK_DEFAULT_FAIL_ON,
        help="feed back findings of this severity or worse (default: warning, so the agent "
        "hears warnings while the code is in its context)",
    )
    hook.add_argument(
        "--base",
        default=None,
        help="stop: compare against the merge base of this ref and HEAD instead of the "
        "commit the session started from",
    )


def version_string() -> str:
    return f"{PROGRAM} {__version__}"


def _add_check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to analyze")
    _add_config_arguments(parser)
    _add_analysis_arguments(parser)
    _add_cache_argument(parser)
    _add_output_arguments(parser)
    _add_baseline_argument(parser)
    _add_exit_zero_argument(parser)
    _add_summary_argument(parser)


def _add_cache_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="neither read nor write the content-hash cache (cache.directory) for this "
        'run; the report records coverage.cache.status = "bypassed"',
    )


def _add_summary_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--summary",
        action="store_true",
        help="text format: print the first-contact overview (findings by rule and directory, "
        "files with the most policy findings, complexity counts, parse failures, elapsed "
        "time) instead of every finding; the totals and the gate line are unchanged. The "
        "JSON report always carries the same overview as `summary`",
    )


def _add_skills_destination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent",
        choices=AGENTS,
        required=True,
        help="claude: .claude/skills; codex: .agents/skills; generic: --project DIR itself",
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "--project",
        type=Path,
        default=None,
        help="project root holding the agent's skills directory (default: current directory); "
        "for --agent generic, the directory that receives <name>/SKILL.md (required)",
    )
    where.add_argument(
        "--user",
        action="store_true",
        help="use the per-user skills directory under the home directory instead",
    )


def _add_exit_zero_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="advisory run: report everything as usual but exit 0 instead of 1 on policy "
        "violations; exit 2 (configuration) and exit 3 (tool failure, strict parse "
        "failure) are never masked",
    )


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="analysis root (default: current directory)"
    )
    parser.add_argument("--config", type=Path, default=None, help="explicit configuration file")
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="organization policy file (TOML with [tool.shockharness]) kept outside the "
        "analyzed root; the repository's configuration cannot loosen the keys it sets",
    )
    # The only two configuration keys the command line may override (docs/configuration.md).
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=None,
        help="use this built-in profile instead of the configured one; the configuration "
        "file's other keys still apply on top of it",
    )
    parser.add_argument(
        "--parse-errors",
        choices=PARSE_ERROR_POLICIES,
        default=None,
        help="override parse_errors: fail (exit 3 on an unparseable file) or warn",
    )


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-inline-suppressions",
        action="store_true",
        help="ignore inline suppression comments and report each one",
    )


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=FORMATS, default=FORMAT_TEXT)
    parser.add_argument(
        "--output", type=Path, default=None, help="write the report here instead of stdout"
    )


def _add_baseline_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="reviewed baseline file; matched findings are legacy under gates.legacy",
    )


def _add_revision_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--base", default=None, required=required, help="base revision (any local git ref)"
    )
    parser.add_argument(
        "--head",
        default=None,
        required=required,
        help="head revision (any local git ref, e.g. HEAD; uncommitted changes are not included)",
    )


def _write_output(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    # Boundary (declared in .shockharness.toml): writing the report to a user-chosen path.
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot write report: {exc}", str(output)) from exc


def _options(args: argparse.Namespace) -> AnalysisOptions:
    """``--no-cache`` exists on the working-tree commands only; the others (baseline
    create, diff) never read the cache, so their options say bypassed."""
    cache = CACHE_BYPASSED
    if "no_cache" in args and not args.no_cache:
        cache = CACHE_CONFIGURED
    return AnalysisOptions(inline_suppressions=not args.no_inline_suppressions, cache=cache)


def _load_config(args: argparse.Namespace) -> EffectiveConfig:
    overrides = CliOverrides(
        profile=args.profile, parse_errors=args.parse_errors, policy=args.policy
    )
    return load_config_with_overrides(args.root, args.config, overrides)


def _analyze_working_tree(args: argparse.Namespace) -> tuple[Report, EffectiveConfig]:
    config = _load_config(args)
    report = analyze_paths(list(args.paths), args.root, config, _options(args))
    report = with_accepted_policy(report, args.root, args.config, config)
    if args.baseline is not None:
        report = apply_baseline(report, load_baseline(args.baseline), config)
    report = with_history(report, args.root, WORKING_TREE_REVISION, config)
    if args.exit_zero:
        report = replace(report, gate=as_advisory(report.gate))
    return report, config


def _render_report(report: Report, fmt: str, summary: bool) -> str:
    if fmt == FORMAT_JSON:
        return json_output.render(report)
    if fmt == FORMAT_SARIF:
        return sarif_output.render(report)
    if summary:
        return text_output.render_summary(report)
    return text_output.render(report)


def _render_diff(diff: DiffReport, fmt: str) -> str:
    if fmt == FORMAT_JSON:
        return json_output.render_diff(diff)
    if fmt == FORMAT_SARIF:
        return sarif_output.render_diff(diff)
    return text_output.render_diff(diff)


def _report_written(args: argparse.Namespace, status: str, exit_code: int) -> None:
    if args.output is not None:
        sys.stdout.write(
            f"{PROGRAM}: report written to {args.output}; gate {status} (exit {exit_code})\n"
        )


def _skills_notices(root: Path, config: EffectiveConfig) -> list[str]:
    """Installed skills behind the package; and, for a project with its own configuration
    that has not turned the notice off, agents working here with no skills at all."""
    notices = [drift.notice for drift in skills_drift(root)]
    if config.source.tier in USER_TIERS and config.values[SKILLS_KEY]["notify_missing"]:
        notices.extend(missing_skills_notices(root, Path.home()))
    return notices


def _run_scan(args: argparse.Namespace) -> int:
    report, config = _analyze_working_tree(args)
    _write_output(_render_report(report, args.format, args.summary), args.output)
    _report_written(args, report.gate.status, process_exit_code(report.gate))
    for notice in _skills_notices(args.root, config):
        sys.stderr.write(f"{PROGRAM}: {notice}\n")  # beside the report, never in it
    return process_exit_code(report.gate)


def _configuration_texts(config: EffectiveConfig) -> dict[str, str | None]:
    """The text of the configuration file and the policy file the inventory points into."""
    texts: dict[str, str | None] = {}
    paths: list[str] = []
    if config.source.tier in USER_TIERS:
        paths.append(config.source.path)
    if config.policy is not None:
        paths.append(config.policy.path)
    for path in paths:
        text, _error = read_text(Path(path))
        texts[path] = text
    return texts


def _run_exceptions(args: argparse.Namespace) -> int:
    config = _load_config(args)
    cache = CACHE_BYPASSED if args.no_cache else CACHE_CONFIGURED
    options = AnalysisOptions(inline_suppressions=True, cache=cache)
    report = analyze_paths(list(args.paths), args.root, config, options)
    baseline: tuple[Baseline, str] | None = None
    if args.baseline is not None:
        baseline = (load_baseline(args.baseline), str(args.baseline))
    considered = sorry_count(report.files, config, args.root)
    texts = _configuration_texts(config)
    inventory = build_inventory(report, config, args.root, texts, baseline, considered)
    if args.format == FORMAT_JSON:
        text = json.dumps(inventory.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"
    else:
        text = render_inventory(inventory, args.root)
    _write_output(text, args.output)
    return EXIT_OK


def _run_baseline(args: argparse.Namespace) -> int:
    target: Path = args.output
    if target.exists() and not args.force:
        raise UsageError(
            "baseline file already exists; a baseline is never updated automatically, "
            "pass --force to replace it after review",
            str(target),
        )
    config = _load_config(args)
    options = replace(_options(args), cache=CACHE_BYPASSED)  # a baseline never reads the cache
    report = analyze_paths(list(args.paths), args.root, config, options)
    if report.gate.status == GATE_ERROR:
        sys.stderr.write(text_output.render(report))
        raise UsageError(
            "analysis did not complete, so the findings are not a complete picture; "
            "no baseline was written",
            None,
        )
    baseline = build_baseline(report.findings, report.tool_version, config.digest)
    _write_output(render_baseline(baseline), target)
    sys.stdout.write(
        f"{PROGRAM}: wrote {target} with {len(baseline.entries)} fingerprint(s) from "
        f"{len(report.files)} file(s) (config digest {config.digest}); review it before "
        "committing it\n"
    )
    return EXIT_OK


def _run_diff_like(args: argparse.Namespace) -> DiffReport:
    config = _load_config(args)
    diff = diff_revisions(args.root, args.base, args.head, config, _options(args))
    metrics = dict(diff.metrics)
    metrics["history"] = collect_history(
        args.root, diff.head.commit, head_paths(diff), config, metrics["complexity"]
    )
    return with_metrics(diff, metrics)


def _run_diff(args: argparse.Namespace) -> int:
    diff = _run_diff_like(args)
    _write_output(_render_diff(diff, args.format), args.output)
    _report_written(args, diff.gate.status, diff.gate.exit_code)
    if diff.gate.status == GATE_ERROR:
        return diff.gate.exit_code
    return EXIT_OK


def _run_gate(args: argparse.Namespace) -> int:
    revisions = (args.base is not None, args.head is not None)
    if revisions == (True, False) or revisions == (False, True):
        raise UsageError("--base and --head must be given together", None)
    if revisions == (True, True):
        if len(args.paths) > 0:
            raise UsageError("PATH arguments cannot be combined with --base/--head", None)
        if args.baseline is not None:
            raise UsageError(
                "--baseline cannot be combined with --base/--head: the base revision is the "
                "legacy source for a revision gate",
                None,
            )
        diff = _run_diff_like(args)
        if args.exit_zero:
            diff = replace(diff, gate=as_advisory(diff.gate))
        _write_output(_render_diff(diff, args.format), args.output)
        _report_written(args, diff.gate.status, process_exit_code(diff.gate))
        return process_exit_code(diff.gate)
    if len(args.paths) == 0:
        raise UsageError("gate needs PATH... or --base and --head", None)
    return _run_scan(args)


def _run_config(args: argparse.Namespace) -> int:
    config = _load_config(args)
    if args.config_command == "validate":
        check_contract_references(args.root, config)
        sys.stdout.write(
            f"{PROGRAM}: configuration is valid ({config.source.tier}: {config.source.path}; "
            f"profile {config.values['profile']})\n"
        )
        for note in config.notes:
            sys.stdout.write(f"  note: {note}\n")
        for deviation in config.deviations:
            sys.stdout.write(f"  policy deviation: {deviation}\n")
        return EXIT_OK
    sys.stdout.write(json.dumps(config.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n")
    return EXIT_OK


def _run_rules(args: argparse.Namespace) -> int:
    if args.rules_command == "list":
        sys.stdout.write(text_output.render_rule_table(registry.RULES))
        return EXIT_OK
    if not registry.is_known_rule(args.rule_id):
        raise UsageError(
            f"unknown rule ID; known rules: {', '.join(registry.rule_ids())}", args.rule_id
        )
    sys.stdout.write(text_output.render_rule_explanation(registry.get_rule(args.rule_id)))
    return EXIT_OK


def _run_init(args: argparse.Namespace) -> int:
    target: Path = args.path
    if target.exists() and not args.force:
        raise UsageError(
            "configuration file already exists; pass --force to overwrite it", str(target)
        )
    _write_output(render_profile_config_toml(args.profile), target)
    sys.stdout.write(f"{PROGRAM}: wrote {target} ({args.profile} profile)\n")
    _init_skills(args, target.parent)
    return EXIT_OK


def _init_skills(args: argparse.Namespace, project_root: Path) -> None:
    """``init`` installs the skills for every agent working in the project, so an agent
    that adopts ShockHarness by running commands has them without reading the setup guide."""
    if args.no_skills:
        sys.stdout.write(
            f"{PROGRAM}: skills not installed (--no-skills); `check` says so while an agent "
            "works here without them, unless skills.notify_missing = false\n"
        )
        return
    agents = detected_agents(project_root)
    if args.agent is not None:
        agents = [known_agent(agent) for agent in args.agent]
    if len(agents) == 0:
        markers = ", ".join(marker for known in KNOWN_AGENTS for marker in known.markers)
        sys.stdout.write(
            f"{PROGRAM}: skills not installed: no coding agent's files in {project_root} "
            f"({markers}); run {install_choices()}\n"
        )
        return
    for known in agents:
        _init_agent_skills(project_root, known)


def _init_agent_skills(project_root: Path, known: KnownAgent) -> None:
    if skills_installed(project_root, Path.home(), known):
        sys.stdout.write(
            f"  skills     {known.agent}: already installed (in {known.skills_dir} here or "
            f"under the home directory); `shockharness skills update --agent {known.agent}` "
            "refreshes them\n"
        )
        return
    destination = project_root / known.skills_dir
    result = install_skills(destination, known.agent, force=False)
    sys.stdout.write(
        f"{PROGRAM}: installed {len(result.files)} skill(s) for {known.agent} into {destination}\n"
    )
    sys.stdout.write(f"{get_adapter(known.agent).discovery}\n")
    _report_pointer(project_root, known)
    if known.agent == AGENT_CLAUDE:
        sys.stdout.write(
            "Edit-time feedback: `shockharness skills install --agent claude --hook --force` "
            "also adds a PostToolUse hook to .claude/settings.json, so the agent hears "
            "findings right after each edit instead of at commit or in CI.\n"
        )


def _report_pointer(project_root: Path, known: KnownAgent) -> None:
    path, status = add_pointer(project_root, known)
    sys.stdout.write(f"  pointer    {path}: {status}\n")


def _skills_destination(args: argparse.Namespace) -> tuple[Path, Path]:
    """(destination directory, the --project path as the user typed it or the cwd)."""
    adapter = get_adapter(args.agent)
    if adapter.agent == AGENT_GENERIC and args.project is None and not args.user:
        raise UsageError(
            "--agent generic needs --project DIR (the directory that receives "
            "<name>/SKILL.md); there is no conventional location for a generic agent",
            None,
        )
    project_root = Path.cwd()
    if args.project is not None:
        project_root = args.project
    destination = resolve_destination(adapter, project_root, args.user, Path.home())
    return destination, project_root


def _print_skill_files(result: SkillsResult) -> None:
    for file in result.files:
        relative = file.path.relative_to(result.destination).as_posix()
        line = f"  {file.status:<10} {relative}"
        if file.action not in (file.status, ACTION_NONE):
            line += f": {file.action}"
        if file.detail != "":
            line += f" ({file.detail})"
        sys.stdout.write(line + "\n")


def _check_hook_arguments(args: argparse.Namespace, agent: str) -> None:
    if args.lock and not (args.hook or args.stop_hook):
        raise UsageError(
            "--lock locks the configuration the hooks run under; add --hook or --stop-hook",
            None,
        )
    for flag, asked in (("--hook", args.hook), ("--stop-hook", args.stop_hook)):
        if asked and agent != AGENT_CLAUDE:
            raise UsageError(f"{flag} is for --agent {AGENT_CLAUDE} (Claude Code hooks)", None)
        if asked and args.user:
            raise UsageError(
                f"{flag} writes the project's .claude/settings.json; it needs a project, "
                "not --user",
                None,
            )


def _report_hook(args: argparse.Namespace, agent: str, project_root: Path) -> None:
    """Install the edit-time hook and the finish-time gate when asked; offer the edit-time
    hook to a Claude Code project otherwise."""
    lock = None
    if args.lock:
        lock = _write_project_lock(project_root, args.force)
    if args.stop_hook:
        settings, status = install_claude_stop_hook(project_root, lock)
        sys.stdout.write(f"  stop hook  {settings} ({status})\n")
    if args.hook:
        command = hook_command(lock, HOOK_COMMAND)
        settings, status = install_claude_hook(project_root, command)
        sys.stdout.write(
            f"  hook       {settings} ({status}): {command}\n"
            "Edit-time feedback needs `shockharness` on the PATH the agent's hooks run with; "
            "if it lives in a virtual environment, put that path in the command.\n"
        )
    elif agent == AGENT_CLAUDE and not args.user:
        sys.stdout.write(
            "Edit-time feedback: rerun with --hook to add a PostToolUse hook to "
            ".claude/settings.json, so the agent hears findings right after each edit "
            "instead of at commit or in CI.\n"
        )


def _write_project_lock(project_root: Path, force: bool) -> Path:
    """The ``--lock`` policy file: written from the project's configuration, or kept."""
    path = lock_path(project_root, Path.home())
    if path.exists() and not force:
        sys.stdout.write(
            f"  lock       {path}: kept (edit it to accept a change; --force rewrites it)\n"
        )
        return path
    config = load_config_with_overrides(project_root, None, NO_OVERRIDES)
    write_lock(path, render_lock(config, project_root))
    sys.stdout.write(
        f"  lock       {path}: written; the project's configuration may tighten these keys "
        "but not loosen them (catch boundaries aside); edit the lock to accept a change\n"
    )
    return path


TOOL_TABLE_HEADER = "[tool.shockharness"


def _configured(project_root: Path) -> str | None:
    """The project's ShockHarness configuration file, None when it has none. Only
    presence is checked: ``check`` validates it."""
    for name in DEDICATED_FILENAMES:
        if (project_root / name).is_file():
            return name
    pyproject = project_root / PYPROJECT_FILENAME
    if not pyproject.is_file():
        return None
    text, _error = read_text(pyproject)
    if text is not None and any(
        line.strip().startswith(TOOL_TABLE_HEADER) for line in text.splitlines()
    ):
        return PYPROJECT_FILENAME
    return None


def _ensure_project_config(project_root: Path) -> None:
    """A project with no ShockHarness configuration gets what ``init`` writes, with the
    test exemption (spec 21.1 decision 35); an existing one is never changed."""
    present = _configured(project_root)
    if present is not None:
        sys.stdout.write(f"  config     {present}: kept as it is\n")
        return
    _write_output(render_profile_config_toml(PROFILE_STRICT), project_root / DEDICATED_FILENAME)
    exempt = ", ".join(TEST_EXEMPTION_RULES)
    sys.stdout.write(
        f"  config     {DEDICATED_FILENAME}: written (strict profile, as `init` writes it; "
        f"tests exempt from {exempt})\n"
    )


def _install_skills(args: argparse.Namespace, destination: Path, project_root: Path) -> int:
    adapter = get_adapter(args.agent)
    _check_hook_arguments(args, adapter.agent)
    result = install_skills(destination, args.agent, args.force)
    sys.stdout.write(
        f"{PROGRAM}: installed {len(result.files)} skill(s) for {args.agent} into {destination}\n"
    )
    _print_skill_files(result)
    sys.stdout.write(f"  manifest   {MANIFEST_FILENAME} ({version_string()})\n")
    sys.stdout.write(f"{adapter.discovery}\n")
    if adapter.agent == AGENT_GENERIC:
        sys.stdout.write(
            "Add this line to the agent's instruction file (for example AGENTS.md):\n"
            f"  {pointer_line(project_root)}\n"
        )
    elif not args.user:
        _report_pointer(project_root, known_agent(adapter.agent))
    if not args.user:
        _ensure_project_config(project_root)
    _report_hook(args, adapter.agent, project_root)
    return result.exit_code


def _run_skills(args: argparse.Namespace) -> int:
    if args.skills_command == "list":
        for name in SKILL_NAMES:
            sys.stdout.write(f"{name}\n  {shipped_frontmatter(name).description}\n")
        return EXIT_OK
    if args.skills_command == "show":
        sys.stdout.write(skill_text(args.name))
        return EXIT_OK
    destination, project_root = _skills_destination(args)
    if args.skills_command == "install":
        return _install_skills(args, destination, project_root)
    result = update_skills(destination, args.agent, args.check)
    mode = "checked" if args.check else "updated"
    sys.stdout.write(
        f"{PROGRAM}: {mode} skills for {args.agent} in {destination} ({version_string()})\n"
    )
    _print_skill_files(result)
    up_to_date = result.count(STATUS_UP_TO_DATE)
    if up_to_date == len(result.files):
        sys.stdout.write(f"{PROGRAM}: {up_to_date} skill(s) up to date\n")
    elif args.check:
        drifted = len(result.files) - up_to_date
        sys.stdout.write(
            f"{PROGRAM}: {drifted} of {len(result.files)} skill(s) drifted from the installed "
            f"package (exit {result.exit_code})\n"
        )
    else:
        conflicts = result.count(STATUS_EDITED)
        if conflicts == 0:
            sys.stdout.write(f"{PROGRAM}: {len(result.files)} skill(s) up to date\n")
        else:
            sys.stdout.write(
                f"{PROGRAM}: {conflicts} conflict(s) left unchanged (exit {result.exit_code})\n"
            )
    return result.exit_code


def _run_contracts(args: argparse.Namespace) -> int:
    if args.contracts_command == "static-properties":
        config = load_config_with_overrides(args.root, args.config, NO_OVERRIDES)
        settings = config.section(PROPERTY_CONTRACTS_SECTION)
        sys.stdout.write(json.dumps(static_properties(settings)) + "\n")
        return EXIT_OK
    if args.check:
        if args.language is not None or args.dest is not None:
            raise UsageError("contracts install --check takes no --language or --dest", None)
        result = check_runtime(args.project)
        verb = "checked"
    else:
        if args.language is None or args.dest is None:
            raise UsageError("contracts install needs --language and --dest (or --check)", None)
        result = install_runtime(args.project, args.language, args.dest, args.force)
        verb = "installed"
    sys.stdout.write(f"{PROGRAM}: {verb} contracts runtime ({version_string()})\n")
    for file in result.files:
        detail = "" if file.detail == "" else f" ({file.detail})"
        sys.stdout.write(f"  {file.status:<11}{file.language:<17}{file.path}{detail}\n")
    sys.stdout.write(f"  manifest   {result.manifest_path}\n")
    if not args.check:
        sys.stdout.write(
            "List the path under rules.property_contracts.runtime_module; the project owns "
            "the file from now on.\n"
        )
    return result.exit_code


def _run_hook(args: argparse.Namespace) -> int:
    """The agent's hook protocol (Claude Code): 2 feeds stderr back to the agent, 1 is a
    notice to the user, 0 is clean. A configuration error is the usual exit 2: the agent
    sees it, which is right when its edit broke the configuration."""
    config = _load_config(args)
    if args.event == EVENT_STOP:
        result = run_stop(read_stdin(), args.root, config, _options(args), args.base)
    elif args.event == EVENT_SESSION_START:
        result = run_session_start(read_stdin(), args.root, config)
    else:
        result = run_post_edit(read_stdin(), args.root, config, _options(args), args.fail_on)
    return write_result(result, sys.stderr)


def _run_version() -> int:
    sys.stdout.write(version_string() + "\n")
    return EXIT_OK


def _dispatch(args: argparse.Namespace) -> int:
    runners: dict[str, Callable[[argparse.Namespace], int]] = {
        COMMAND_CHECK: _run_scan,
        COMMAND_SCAN: _run_scan,
        COMMAND_VERSION: lambda _args: _run_version(),
        COMMAND_EXCEPTIONS: _run_exceptions,
        "baseline": _run_baseline,
        "diff": _run_diff,
        "gate": _run_gate,
        "config": _run_config,
        "rules": _run_rules,
        "init": _run_init,
        COMMAND_SKILLS: _run_skills,
        COMMAND_CONTRACTS: _run_contracts,
        COMMAND_HOOK: _run_hook,
    }
    if args.command not in runners:
        raise UsageError(f"unknown command {args.command!r}", None)
    return runners[args.command](args)


def main(argv: Sequence[str]) -> int:
    """Run the CLI with ``argv`` (without the program name) and return the exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv))
    if sys.flags.optimize:
        # ShockHarness checks its own invariants with assert (decision 28): an optimized
        # run would remove them, so it refuses to start.
        sys.stderr.write(
            f"{PROGRAM}: error: ShockHarness checks its invariants with assert and does not "
            "run under python -O or PYTHONOPTIMIZE\n"
        )
        return EXIT_INVALID_CONFIG
    # Boundary (declared in .shockharness.toml): the process edge. Typed errors map to
    # exit 2; anything unexpected prints its full traceback and exits 3. Nothing is hidden.
    try:
        return _dispatch(args)
    except ShockHarnessError as exc:
        sys.stderr.write(f"{PROGRAM}: error: {exc}\n")
        return EXIT_INVALID_CONFIG
    except Exception:
        sys.stderr.write(
            f"{PROGRAM}: internal error (exit {EXIT_INTERNAL_ERROR}); "
            "this is a bug, please report it:\n"
        )
        traceback.print_exc()
        return EXIT_INTERNAL_ERROR


def entry() -> None:
    """Console-script entry point."""
    sys.exit(main(sys.argv[1:]))
