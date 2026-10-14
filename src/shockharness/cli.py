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
from pathlib import Path

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import DEDICATED_FILENAME, load_config, render_default_config_toml
from shockharness.constants import EXIT_INTERNAL_ERROR, EXIT_INVALID_CONFIG, EXIT_OK, JSON_INDENT
from shockharness.errors import ShockHarnessError, UnsupportedFeatureError, UsageError
from shockharness.output import json as json_output
from shockharness.output import text as text_output
from shockharness.rules import registry
from shockharness.version import __version__

PROGRAM = "shockharness"
FORMAT_TEXT = "text"
FORMAT_JSON = "json"
FORMAT_SARIF = "sarif"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Strict static-analysis quality gate: no silent failures, no implicit defaults, "
            "no magic numbers."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    scan = commands.add_parser(
        "scan", help="analyze files and directories, print a report, exit with the gate status"
    )
    scan.add_argument("paths", nargs="+", type=Path, help="files or directories to analyze")
    _add_config_arguments(scan)
    scan.add_argument(
        "--format", choices=(FORMAT_TEXT, FORMAT_JSON, FORMAT_SARIF), default=FORMAT_TEXT
    )
    scan.add_argument(
        "--output", type=Path, default=None, help="write the report here instead of stdout"
    )
    scan.add_argument(
        "--no-inline-suppressions",
        action="store_true",
        help="ignore inline suppression comments and report each one",
    )

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

    init = commands.add_parser("init", help=f"write a {DEDICATED_FILENAME} with the strict profile")
    init.add_argument("--profile", choices=("strict",), default="strict")
    init.add_argument(
        "--path", type=Path, default=Path(DEDICATED_FILENAME), help="where to write the file"
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    return parser


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="analysis root (default: current directory)"
    )
    parser.add_argument("--config", type=Path, default=None, help="explicit configuration file")


def _write_output(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    # Boundary (declared in .shockharness.toml): writing the report to a user-chosen path.
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot write report: {exc}", str(output)) from exc


def _run_scan(args: argparse.Namespace) -> int:
    if args.format == FORMAT_SARIF:
        raise UnsupportedFeatureError(
            "SARIF output is not implemented until Milestone F", "--format sarif"
        )
    config = load_config(args.root, args.config)
    options = AnalysisOptions(inline_suppressions=not args.no_inline_suppressions)
    report = analyze_paths(list(args.paths), args.root, config, options)
    if args.format == FORMAT_JSON:
        rendered = json_output.render(report)
    else:
        rendered = text_output.render(report)
    _write_output(rendered, args.output)
    if args.output is not None:
        sys.stdout.write(
            f"{PROGRAM}: report written to {args.output}; "
            f"gate {report.gate.status} (exit {report.gate.exit_code})\n"
        )
    return report.gate.exit_code


def _run_config(args: argparse.Namespace) -> int:
    config = load_config(args.root, args.config)
    if args.config_command == "validate":
        sys.stdout.write(
            f"{PROGRAM}: configuration is valid ({config.source.tier}: {config.source.path})\n"
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
    _write_output(render_default_config_toml(), target)
    sys.stdout.write(f"{PROGRAM}: wrote {target} ({args.profile} profile)\n")
    return EXIT_OK


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "scan":
        return _run_scan(args)
    if args.command == "config":
        return _run_config(args)
    if args.command == "rules":
        return _run_rules(args)
    if args.command == "init":
        return _run_init(args)
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
