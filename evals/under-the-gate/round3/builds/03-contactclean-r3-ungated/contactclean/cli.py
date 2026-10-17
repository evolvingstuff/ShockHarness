"""Command-line interface for contactclean."""

from __future__ import annotations

import argparse
import json
import sys

from .core import InputError, clean, write_contacts

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_UNREADABLE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contactclean",
        description="Clean a CSV export of contacts.",
    )
    parser.add_argument("input", help="contacts CSV to read")
    parser.add_argument("--output", "-o", required=True, help="cleaned CSV to write")
    parser.add_argument("--report", "-r", required=True, help="JSON report to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with open(args.input, newline="", encoding="utf-8-sig") as stream:
            result = clean(stream)
    except (OSError, UnicodeDecodeError, InputError) as exc:
        print(f"contactclean: cannot read {args.input}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    with open(args.output, "w", newline="", encoding="utf-8") as out:
        write_contacts(out, result.contacts)
    with open(args.report, "w", encoding="utf-8") as rep:
        json.dump(result.report(), rep, indent=2, ensure_ascii=False)
        rep.write("\n")

    return EXIT_OK if result.all_rows_usable else EXIT_ISSUES


if __name__ == "__main__":
    raise SystemExit(main())
