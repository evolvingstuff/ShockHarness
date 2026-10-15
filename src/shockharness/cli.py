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
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths, apply_baseline, with_history
from shockharness.config import (
    DEDICATED_FILENAME,
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
from shockharness.errors import ShockHarnessError, UsageError
from shockharness.gate import GATE_ERROR, as_advisory, process_exit_code
from shockharness.gating.baseline import build_baseline, load_baseline, render_baseline
from shockharness.gating.diff import DiffReport, diff_revisions, head_paths, with_metrics
from shockharness.history.hotspots import collect_history
from shockharness.output import json as json_output
from shockharness.output import sarif as sarif_output
from shockharness.output import text as text_output
from shockharness.report import Report
from shockharness.rules import registry
from shockharness.schema import PROFILE_STRICT, PROFILES
from shockharness.skills import SKILL_NAMES, shipped_frontmatter, skill_text
from shockharness.skills.adapters import (
    AGENT_GENERIC,
    AGENTS,
    get_adapter,
    pointer_line,
    resolve_destination,
)
from shockharness.skills.install import (
    ACTION_NONE,
    MANIFEST_FILENAME,
    STATUS_EDITED,
    STATUS_UP_TO_DATE,
    SkillsResult,
    install_skills,
    update_skills,
)
from shockharness.version import __version__

PROGRAM = "shockharness"
FORMAT_TEXT = "text"
FORMAT_JSON = "json"
FORMAT_SARIF = "sarif"
FORMATS = (FORMAT_TEXT, FORMAT_JSON, FORMAT_SARIF)
WORKING_TREE_REVISION = "HEAD"
PARSE_ERROR_POLICIES = ("fail", "warn")
COMMAND_CHECK = "check"
COMMAND_SCAN = "scan"  # hidden alias of check, kept so Milestone A-D invocations keep working
COMMAND_VERSION = "version"
COMMAND_SKILLS = "skills"


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
    _add_revision_arguments(diff, True)
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
    _add_revision_arguments(gate, False)
    _add_config_arguments(gate)
    _add_analysis_arguments(gate)
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

    init = commands.add_parser(
        "init", help=f"write a {DEDICATED_FILENAME} selecting a built-in profile"
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

    skills = commands.add_parser(
        COMMAND_SKILLS, help="install, update or inspect the bundled agent skills"
    )
    skills_commands = skills.add_subparsers(
        dest="skills_command", required=True, metavar="SUBCOMMAND"
    )
    skills_commands.add_parser("list", help="list the shipped skills with their descriptions")
    show = skills_commands.add_parser("show", help="print one shipped SKILL.md")
    show.add_argument("name", choices=SKILL_NAMES)
    skills_install = skills_commands.add_parser(
        "install",
        help=f"write every skill and a {MANIFEST_FILENAME} manifest into the agent's directory",
    )
    _add_skills_destination_arguments(skills_install)
    skills_install.add_argument(
        "--force", action="store_true", help="replace skill files that already exist"
    )
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
    return parser


def version_string() -> str:
    return f"{PROGRAM} {__version__}"


def _add_check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to analyze")
    _add_config_arguments(parser)
    _add_analysis_arguments(parser)
    _add_output_arguments(parser)
    _add_baseline_argument(parser)
    _add_exit_zero_argument(parser)
    _add_summary_argument(parser)


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


def _add_revision_arguments(parser: argparse.ArgumentParser, required: bool) -> None:
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
    return AnalysisOptions(inline_suppressions=not args.no_inline_suppressions)


def _load_config(args: argparse.Namespace) -> EffectiveConfig:
    overrides = CliOverrides(profile=args.profile, parse_errors=args.parse_errors)
    return load_config_with_overrides(args.root, args.config, overrides)


def _analyze_working_tree(args: argparse.Namespace) -> Report:
    config = _load_config(args)
    report = analyze_paths(list(args.paths), args.root, config, _options(args))
    if args.baseline is not None:
        report = apply_baseline(report, load_baseline(args.baseline), config)
    report = with_history(report, args.root, WORKING_TREE_REVISION, config)
    if args.exit_zero:
        report = replace(report, gate=as_advisory(report.gate))
    return report


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


def _run_scan(args: argparse.Namespace) -> int:
    report = _analyze_working_tree(args)
    _write_output(_render_report(report, args.format, args.summary), args.output)
    _report_written(args, report.gate.status, process_exit_code(report.gate))
    return process_exit_code(report.gate)


def _run_baseline(args: argparse.Namespace) -> int:
    target: Path = args.output
    if target.exists() and not args.force:
        raise UsageError(
            "baseline file already exists; a baseline is never updated automatically, "
            "pass --force to replace it after review",
            str(target),
        )
    config = _load_config(args)
    report = analyze_paths(list(args.paths), args.root, config, _options(args))
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
    return EXIT_OK


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


def _run_skills(args: argparse.Namespace) -> int:
    if args.skills_command == "list":
        for name in SKILL_NAMES:
            sys.stdout.write(f"{name}\n  {shipped_frontmatter(name).description}\n")
        return EXIT_OK
    if args.skills_command == "show":
        sys.stdout.write(skill_text(args.name))
        return EXIT_OK
    destination, project_root = _skills_destination(args)
    adapter = get_adapter(args.agent)
    if args.skills_command == "install":
        result = install_skills(destination, args.agent, args.force)
        sys.stdout.write(
            f"{PROGRAM}: installed {len(result.files)} skill(s) for {args.agent} into "
            f"{destination}\n"
        )
        _print_skill_files(result)
        sys.stdout.write(f"  manifest   {MANIFEST_FILENAME} ({version_string()})\n")
        sys.stdout.write(f"{adapter.discovery}\n")
        if adapter.agent == AGENT_GENERIC:
            sys.stdout.write(
                "Add this line to the agent's instruction file (for example AGENTS.md):\n"
                f"  {pointer_line(project_root)}\n"
            )
        return result.exit_code
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


def _run_version() -> int:
    sys.stdout.write(version_string() + "\n")
    return EXIT_OK


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == COMMAND_CHECK or args.command == COMMAND_SCAN:
        return _run_scan(args)
    if args.command == COMMAND_VERSION:
        return _run_version()
    if args.command == "baseline":
        return _run_baseline(args)
    if args.command == "diff":
        return _run_diff(args)
    if args.command == "gate":
        return _run_gate(args)
    if args.command == "config":
        return _run_config(args)
    if args.command == "rules":
        return _run_rules(args)
    if args.command == "init":
        return _run_init(args)
    if args.command == COMMAND_SKILLS:
        return _run_skills(args)
    raise UsageError(f"unknown command {args.command!r}", None)


def main(argv: Sequence[str]) -> int:
    """Run the CLI with ``argv`` (without the program name) and return the exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv))
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
