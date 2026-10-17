"""H4 async lifecycle: ASYNC001, ASYNC002, ASYNC003."""

from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.report import Report

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
ASYNC = ("ASYNC001", "ASYNC002", "ASYNC003")


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def analyze(root: Path, config: EffectiveConfig) -> Report:
    return analyze_paths([root / "src"], root, config, OPTIONS)


def rows(report: Report) -> list[tuple[str, str, int, str]]:
    return [
        (f.rule_id, f.path, f.span.line, f.status) for f in report.findings if f.rule_id in ASYNC
    ]


STORE = "async def write(record):\n    return record\n\n\ndef plain(record):\n    return record\n"


def test_async001_python_across_files_and_catalog(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/store.py", STORE)
    write(
        empty_root,
        "src/app.py",
        "import asyncio\n"
        "from store import write, plain\n\n\n"
        "async def save(record):\n"
        "    write(record)\n"  # 6
        "    plain(record)\n"
        "    await write(record)\n"
        "    asyncio.sleep(0)\n"  # 9
        "    task = write(record)\n"
        "    return await task\n\n\n"
        "class Repo:\n"
        "    async def flush(self):\n        return self\n\n"
        "    async def close(self):\n"
        "        self.flush()\n"  # 19
        "        await self.flush()\n",
    )
    report = analyze(empty_root, strict_config)
    assert rows(report) == [
        ("ASYNC001", "src/app.py", 6, "violation"),
        ("ASYNC001", "src/app.py", 9, "violation"),
        # self.flush(): the graph matches a method through self as probable (a subclass
        # may override it), so the finding is unknown.
        ("ASYNC001", "src/app.py", 19, "unknown"),
    ]
    first = next(f for f in report.findings if f.rule_id == "ASYNC001")
    assert first.message.startswith("write(...) is async; its coroutine is created and thrown away")
    assert first.severity == "warning"


def test_async001_javascript_void_and_entry_points(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(
        empty_root,
        "src/app.js",
        "async function writeRecord(r) { return r; }\n"
        "export function save(r) {\n"
        "  writeRecord(r);\n"  # 3
        "  void writeRecord(r);\n"  # 4
        '  fetch("/x");\n'  # 5
        "  writeRecord(r).catch((e) => { report(e); });\n"
        "  return writeRecord(r);\n"
        "}\n"
        "async function main() { await save(ONE); }\n"
        "main();\n",  # 10
    )
    report = analyze(empty_root, strict_config)
    assert [r[2] for r in rows(report)] == [3, 4, 5, 10]
    voided = next(f for f in report.findings if f.span.line == 4)
    assert "discarded with void" in voided.message


def test_async001_void_with_a_global_rejection_reporter(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # MetaList: `void` hands the failure to an unhandledrejection listener that reports it.
    app = (
        "async function writeRecord(r) { return r; }\n"
        "export function save(r) {\n"
        "  writeRecord(r);\n"  # 3: still dropped by accident
        "  void writeRecord(r);\n"
        "}\n"
    )
    write(empty_root, "src/app.js", app)
    write(
        empty_root,
        "src/overlay.js",
        "window.addEventListener('unhandledrejection', (event) => {\n"
        "  event.preventDefault();\n  showOverlay(event.reason);\n});\n",
    )
    assert [r[2] for r in rows(analyze(empty_root, strict_config))] == [3]
    silent = "window.addEventListener('unhandledrejection', (e) => { e.preventDefault(); });\n"
    write(empty_root, "src/overlay.js", silent)
    assert [r[2] for r in rows(analyze(empty_root, strict_config))] == [3, 4]
    write(empty_root, "src/overlay.js", "process.on('unhandledRejection', crash);\n")
    assert [r[2] for r in rows(analyze(empty_root, strict_config))] == [3]


def test_async001_probable_edge_is_unknown(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(
        empty_root,
        "src/app.py",
        "class Worker:\n    async def run(self):\n        return self\n\n\n"
        "def start(worker):\n    worker.run()\n",
    )
    report = analyze(empty_root, make_config(""))
    statuses = [(r[0], r[2], r[3]) for r in rows(report)]
    if statuses:  # resolved by name only, if at all: never a plain violation
        assert statuses == [("ASYNC001", 7, "unknown")]
        assert report.gate.status == "pass"
        gating = make_config("[tool.shockharness.rules.async_lifecycle]\nfail_on_unknown = true\n")
        assert analyze(empty_root, gating).gate.warnings >= 1


def test_async001_works_with_complexity_disabled(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(empty_root, "src/store.py", STORE)
    write(empty_root, "src/app.py", "from store import write\n\n\nasync def f(r):\n    write(r)\n")
    config = make_config("[tool.shockharness.complexity]\nenabled = false\n")
    assert rows(analyze(empty_root, config)) == [("ASYNC001", "src/app.py", 5, "violation")]


def test_async002_tasks_and_supervisors(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(
        empty_root,
        "src/app.py",
        "import asyncio\nimport anyio\n\n\n"
        "async def work():\n    return OK\n\n\n"
        "async def handler(loop, group):\n"
        "    asyncio.create_task(work())\n"  # 10
        "    asyncio.ensure_future(work())\n"  # 11
        "    loop.create_task(work())\n"  # 12
        "    async with asyncio.TaskGroup() as tg:\n        tg.create_task(work())\n"
        "    async with anyio.create_task_group() as nursery:\n"
        "        nursery.create_task(work())\n"
        "    group.create_task(work())\n"  # 17: a parameter, not recognized
        "    kept = asyncio.create_task(work())\n"
        "    await kept\n",
    )
    default = make_config("")
    found = [(r[0], r[2]) for r in rows(analyze(empty_root, default)) if r[0] == "ASYNC002"]
    assert found == [("ASYNC002", 10), ("ASYNC002", 11), ("ASYNC002", 12), ("ASYNC002", 17)]


def test_async003_settled_batches(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(
        empty_root,
        "src/app.py",
        "import asyncio\n\n\n"
        "async def a(jobs):\n    await asyncio.gather(*jobs, return_exceptions=True)\n\n\n"  # 5
        "async def b(jobs):\n"
        "    results = await asyncio.gather(*jobs, return_exceptions=True)\n"  # 9
        "    return len(results)\n\n\n"
        "async def c(jobs):\n    results = await asyncio.gather(*jobs, return_exceptions=True)\n"
        "    return [r for r in results if isinstance(r, Exception)]\n\n\n"
        "def d(jobs):\n    return asyncio.gather(*jobs, return_exceptions=True)\n\n\n"
        "async def e(jobs):\n    await asyncio.gather(*jobs)\n",
    )
    write(
        empty_root,
        "src/app.js",
        "export function f(ps) { Promise.allSettled(ps); }\n"  # 1
        "export async function g(ps) {\n"
        "  const rs = await Promise.allSettled(ps); return rs.length;\n"
        "}\n"
        "export async function h(ps) {\n"
        "  const rs = await Promise.allSettled(ps);\n"
        '  return rs.filter((r) => r.status === "rejected");\n'
        "}\n"
        "export const k = (ps) => Promise.allSettled(ps);\n",
    )
    found = [(r[1], r[2]) for r in rows(analyze(empty_root, strict_config)) if r[0] == "ASYNC003"]
    assert found == [("src/app.js", 1), ("src/app.js", 3), ("src/app.py", 5), ("src/app.py", 9)]


def test_roles_and_deviations(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(empty_root, "src/store.py", STORE)
    write(
        empty_root,
        "src/tests/test_app.py",
        "from store import write\n\n\nasync def test_f():\n    write(ONE)\n",
    )
    default = make_config("")
    assert [r[1] for r in rows(analyze(empty_root, default))] == ["src/tests/test_app.py"]
    narrowed = make_config(
        '[tool.shockharness.rules.async_lifecycle]\nroles = ["production"]\n'
        'supervisors = ["asyncio.TaskGroup", "app.Supervisor"]\nseverity = "review"\n'
    )
    assert rows(analyze(empty_root, narrowed)) == []
    deviations = "\n".join(narrowed.deviations)
    assert "rules.async_lifecycle.roles no longer lists 'test'" in deviations
    assert "rules.async_lifecycle.supervisors also permits 'app.Supervisor'" in deviations
    assert "rules.async_lifecycle.severity is 'review'" in deviations


def test_async003_skips_waiting_for_cancelled_tasks(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    """MetaList feedback (0.7.0): gather(return_exceptions=True) in a finally / except
    block after cancelling the tasks waits for cancellation to finish."""
    write(
        empty_root,
        "src/runtime.py",
        "import asyncio\n\n\n"
        "async def run(tasks):\n"
        "    try:\n        await asyncio.gather(*tasks)\n"
        "    finally:\n"
        "        for task in tasks:\n            task.cancel()\n"
        "        await asyncio.gather(*tasks, return_exceptions=True)\n\n\n"  # not reported
        "async def other(tasks):\n"
        "    try:\n        await asyncio.sleep(0)\n"
        "    finally:\n        await asyncio.gather(*tasks, return_exceptions=True)\n\n\n"  # 17
        "async def third(tasks):\n"
        "    for task in tasks:\n        task.cancel()\n"
        "    await asyncio.gather(*tasks, return_exceptions=True)\n",  # 23: not a cleanup block
    )
    lines = [
        line
        for rule, _path, line, _status in rows(analyze(empty_root, strict_config))
        if rule == "ASYNC003"
    ]
    assert lines == [17, 23]
