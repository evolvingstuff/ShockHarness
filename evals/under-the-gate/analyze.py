"""Mechanical results of the under-the-gate builds, gathered by neither the builders nor
the reviewer: per spec, the gated and ungated trees side by side.

    python evals/under-the-gate/analyze.py BUILDS_DIR OUT_DIR

For each ``BUILDS_DIR/<spec>-<variant>/`` it records ShockHarness's findings under the
same strict configuration (the ungated tree gets a copy), whether the tree's tests pass,
the known-evasion detectors of evals/behavior/run.py over the whole source, and simple
structure counts. From ``BUILDS_DIR/logs/<spec>-gated.jsonl`` it extracts the hook
blocks: each edit the hook fed findings back on, the findings, and the next edit of the
same file (what the agent did about them). No text the builder wrote to explain itself
is kept: only tool calls and tool results.
"""

import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRICT = """[tool.shockharness]
profile = "strict"
include = ["**/*.py", "**/*.js", "**/*.mjs"]
exclude = ["**/node_modules/**", ".claude/**", "**/.venv/**"]
"""
HOOK_MARKER = "after this edit; fix them now"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
SOURCE_SUFFIXES = {".py", ".js", ".mjs"}
SKIP_PARTS = {".git", ".claude", "node_modules", "__pycache__", ".venv"}


def behavior_runner():
    spec = importlib.util.spec_from_file_location(
        "behavior_run", HERE.parent / "behavior" / "run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["behavior_run"] = module
    spec.loader.exec_module(module)
    return module


def sources(tree: Path) -> list[Path]:
    return sorted(
        p
        for p in tree.rglob("*")
        if p.suffix in SOURCE_SUFFIXES and p.is_file() and not SKIP_PARTS & set(p.parts)
    )


def check(tree: Path, shockharness: str) -> dict:
    copy = tree.parent / f".check-{tree.name}"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(tree, copy, ignore=shutil.ignore_patterns(".git", ".claude", "node_modules"))
    (copy / ".shockharness.toml").write_text(STRICT, encoding="utf-8")
    result = subprocess.run(
        [shockharness, "check", ".", "--format", "json", "--no-cache", "--exit-zero"],
        cwd=copy,
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(copy)
    report = json.loads(result.stdout)
    by_rule: dict[str, int] = {}
    for finding in report["findings"]:
        if finding["suppression"] is None:
            by_rule[finding["rule_id"]] = by_rule.get(finding["rule_id"], 0) + 1
    suppressed = len([f for f in report["findings"] if f["suppression"] is not None])
    # Round 3 exempts tests from MAGIC001 and DEF001 (spec 21.1 decision 35), so the
    # findings outside test files are counted too.
    roles = {f["path"]: f["role"] for f in report["files"]}
    outside: dict[str, int] = {}
    for finding in report["findings"]:
        if finding["suppression"] is None and roles.get(finding["path"]) != "test":
            outside[finding["rule_id"]] = outside.get(finding["rule_id"], 0) + 1
    return {
        "by_rule": dict(sorted(by_rule.items())),
        "outside_tests": dict(sorted(outside.items())),
        "suppressed": suppressed,
    }


def tests(tree: Path) -> dict:
    if any(tree.rglob("*.py")):
        argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
        if not (tree / "tests").is_dir():
            argv = [sys.executable, "-m", "unittest", "discover"]
        env_path = "src" if (tree / "src").is_dir() else "."
        result = subprocess.run(
            argv,
            cwd=tree,
            capture_output=True,
            text=True,
            check=False,
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            timeout=600,
        )
    else:
        result = subprocess.run(
            ["node", "--test"], cwd=tree, capture_output=True, text=True, check=False, timeout=600
        )
    return {"exit_code": result.returncode, "tail": (result.stdout + result.stderr)[-600:]}


def structure(tree: Path) -> dict:
    counts = {
        "files": 0,
        "lines": 0,
        "functions": 0,
        "try_blocks": 0,
        "frozen_dataclasses": 0,
        "parameter_defaults": 0,
        "module_constants": 0,
        "inline_suppressions": 0,
    }
    for path in sources(tree):
        text = path.read_text(encoding="utf-8", errors="replace")
        counts["files"] += 1
        counts["lines"] += len(text.splitlines())
        counts["inline_suppressions"] += len(
            re.findall(r"shockharness:\s*ignore\[|#\s*noqa|eslint-disable", text)
        )
        if path.suffix != ".py":
            counts["functions"] += len(re.findall(r"\bfunction\b|=>", text))
            counts["try_blocks"] += len(re.findall(r"\btry\s*\{", text))
            continue
        module = ast.parse(text)
        for node in ast.walk(module):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts["functions"] += 1
                counts["parameter_defaults"] += len(node.args.defaults) + len(
                    [d for d in node.args.kw_defaults if d is not None]
                )
            elif isinstance(node, (ast.Try, ast.TryStar)):
                counts["try_blocks"] += 1
            elif isinstance(node, ast.ClassDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and any(
                        k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value
                        for k in decorator.keywords
                    ):
                        counts["frozen_dataclasses"] += 1
        counts["module_constants"] += len(
            [
                s
                for s in module.body
                if isinstance(s, (ast.Assign, ast.AnnAssign))
                and all(
                    isinstance(t, ast.Name) and t.id.isupper()
                    for t in (s.targets if isinstance(s, ast.Assign) else [s.target])
                )
            ]
        )
    return counts


def evasions(tree: Path, run) -> dict:
    """The behavior suite's detectors over every source line, as if all were added."""
    lines = []
    for path in sources(tree):
        relative = path.relative_to(tree).as_posix()
        prefix = "tests/" if "test" in relative else "src/"
        lines.append(f"+++ b/{prefix}{relative}")
        lines.extend(
            "+" + line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    fired = run._pattern_hits(
        [row[1:] for row in lines if row.startswith("+") and not row.startswith("+++")],
        run.ADDED_SOURCE_PATTERNS,
    )
    restating = [
        row[1:].strip()
        for row in lines
        if (m := run.CONSTANT_ASSIGNMENT.match(row[1:])) and run._restates(m[1], m[2])
    ]
    if restating:
        fired["value_restating_constant"] = restating
    return {kind: hits[:8] for kind, hits in fired.items()}


def _tool_uses(event: dict) -> list[dict]:
    message = event.get("message", {})
    content = message.get("content", []) if isinstance(message, dict) else []
    if not isinstance(content, list):
        return []
    return [p for p in content if isinstance(p, dict) and p.get("type") == "tool_use"]


def hook_blocks(log: Path) -> list[dict]:
    """Each time the hook fed findings back: the tool call it followed, the findings,
    and the agent's next tool call (any tool: agents edit through Bash too). Only tool
    calls and tool results are kept, never text the builder wrote to explain itself."""
    events = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    blocks = []
    last_call = None
    for index, event in enumerate(events):
        uses = _tool_uses(event)
        if uses:
            last_call = uses[-1]
            continue
        text = json.dumps(event)
        if HOOK_MARKER not in text or event.get("type") == "assistant":
            continue
        following = next((u for e in events[index + 1 :] for u in _tool_uses(e)), None)
        blocks.append(
            {
                "after": last_call
                and {"tool": last_call.get("name"), "input": last_call.get("input")},
                "feedback": text[:4000],
                "next_call": following
                and {"tool": following.get("name"), "input": following.get("input")},
            }
        )
    return blocks


CHANGING_TOOLS = {"Edit", "Write", "MultiEdit", "Bash"}


def blocks_from_run_log(tree: Path, log: Path) -> list[dict]:
    """Newer Claude Code versions do not put hook feedback in the stream. The hook's own
    run log has one line per Edit/Write/MultiEdit/Bash call, in order, so the k-th run is
    the k-th such call: each run that fed findings back is paired with the call it
    followed and the agent's next call."""
    runs_path = tree / ".shockharness-cache" / "hook" / "runs.jsonl"
    if not runs_path.is_file():
        return []
    runs = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines() if line]
    calls = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        calls.extend(u for u in _tool_uses(event) if u.get("name") in CHANGING_TOOLS)
    blocks = []
    for index, run in enumerate(runs):
        if run["exit"] != 2 or index >= len(calls):
            continue
        after, following = calls[index], calls[index + 1] if index + 1 < len(calls) else None
        blocks.append(
            {
                "after": {"tool": after.get("name"), "input": after.get("input")},
                "feedback": {k: run[k] for k in ("files", "findings") if k in run}
                | {k: run[k] for k in ("details",) if k in run},
                "next_call": following
                and {"tool": following.get("name"), "input": following.get("input")},
            }
        )
    return blocks


def hook_runs(tree: Path) -> dict:
    """The hook's own run log: how often it ran, and how often it fed findings back."""
    log = tree / ".shockharness-cache" / "hook" / "runs.jsonl"
    if not log.is_file():
        return {"runs": 0, "feedback": 0}
    runs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    return {"runs": len(runs), "feedback": len([r for r in runs if r["exit"] == 2])}


def main(builds: Path, out: Path, shockharness: str) -> None:
    run = behavior_runner()
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for tree in sorted(p for p in builds.iterdir() if p.is_dir() and p.name != "logs"):
        results[tree.name] = {
            "check": check(tree, shockharness),
            "tests": tests(tree),
            "structure": structure(tree),
            "evasion_detectors": evasions(tree, run),
        }
        log = builds / "logs" / f"{tree.name}.jsonl"
        if tree.name.endswith("-gated") and log.exists():
            blocks = hook_blocks(log)
            if len(blocks) == 0:
                blocks = blocks_from_run_log(tree, log)
            results[tree.name]["hook_blocks"] = len(blocks)
            results[tree.name]["hook_log"] = hook_runs(tree)
            (out / f"{tree.name}-blocks.json").write_text(
                json.dumps(blocks, indent=2), encoding="utf-8"
            )
    (out / "mechanical.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, r in results.items():
        print(
            name,
            "tests",
            r["tests"]["exit_code"],
            "findings",
            sum(r["check"]["by_rule"].values()),
            r["check"]["by_rule"],
            "blocks",
            r.get("hook_blocks", "-"),
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
