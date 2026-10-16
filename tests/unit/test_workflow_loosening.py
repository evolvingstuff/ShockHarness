"""Workflow tampering (VERIFY003): GitHub Actions jobs that run ShockHarness, read as text."""

from shockharness.rules.workflows import parse_jobs, workflow_loosenings

WORKFLOW = """\
name: ci
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pip install "shockharness==0.3.0"
      - run: shockharness gate --base origin/main --head HEAD
  unit:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest
permissions:
  contents: read
"""


def items(before: str | None, after: str | None) -> list[str]:
    return [item.item for item in workflow_loosenings(before, after)]


def test_jobs_are_parsed_up_to_the_next_top_level_key() -> None:
    jobs = parse_jobs(WORKFLOW)
    assert sorted(jobs) == ["gate", "unit"]
    assert jobs["gate"].line == 4
    assert jobs["gate"].runs_shockharness
    assert not jobs["unit"].runs_shockharness
    assert all("contents" not in text for _, text in jobs["unit"].lines)
    assert parse_jobs("name: x\n") == {}


def test_a_comment_does_not_make_a_job_run_shockharness() -> None:
    text = "jobs:\n  lint:\n    steps:\n      - run: ruff check  # shockharness later\n"
    assert not parse_jobs(text)["lint"].runs_shockharness


def test_unchanged_and_unrelated_changes_are_quiet() -> None:
    assert items(WORKFLOW, WORKFLOW) == []
    assert items(WORKFLOW, WORKFLOW.replace("python -m pytest", "python -m pytest -x")) == []
    assert items(WORKFLOW.replace("  gate:", "  gate2:"), None) == ["job gate2 removed"]


def test_removed_job_and_deleted_file() -> None:
    without_gate = WORKFLOW.replace(WORKFLOW.split("  gate:")[1].split("  unit:")[0], "")
    assert items(WORKFLOW, without_gate) == ["job gate removed"]
    (deleted,) = workflow_loosenings(WORKFLOW, None)
    assert "the workflow file was deleted" in deleted.message
    assert items(None, WORKFLOW) == []


def test_job_that_no_longer_runs_shockharness() -> None:
    after = WORKFLOW.replace("shockharness gate --base origin/main --head HEAD", "true").replace(
        '"shockharness==0.3.0"', "build"
    )
    assert items(WORKFLOW, after) == ["job gate no longer runs shockharness"]


def test_continue_on_error_and_disabled_condition() -> None:
    after = WORKFLOW.replace(
        "  gate:\n    runs-on: ubuntu-latest\n",
        "  gate:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n    if: false\n",
    )
    found = workflow_loosenings(WORKFLOW, after)
    assert [(item.item, item.line) for item in found] == [
        ("job gate: continue-on-error", 6),
        ("job gate: if false", 7),
    ]
    expression = WORKFLOW.replace("  gate:\n", "  gate:\n    continue-on-error: ${{ true }}\n")
    assert items(WORKFLOW, expression) == ["job gate: continue-on-error"]


def test_weakening_flags_are_reported_once_each() -> None:
    after = WORKFLOW.replace(
        "--head HEAD", "--head HEAD --exit-zero --profile minimal --parse-errors=warn"
    )
    assert items(WORKFLOW, after) == [
        "job gate: --exit-zero",
        "job gate: --profile minimal",
        "job gate: --parse-errors warn",
    ]
    # Already present at base: not added by this change.
    assert items(after, after) == []


def test_pin_downgrade_but_not_upgrade() -> None:
    older = WORKFLOW.replace("shockharness==0.3.0", "shockharness==0.2.0")
    newer = WORKFLOW.replace("shockharness==0.3.0", "shockharness==0.10.0")
    assert items(WORKFLOW, older) == ["job gate: pin 0.2.0"]
    assert items(WORKFLOW, newer) == []
    reusable = "jobs:\n  sh:\n    uses: o/ShockHarness/.github/workflows/check.yml@v1\n"
    pinned = reusable + '    with:\n      shockharness-version: "0.3.0"\n'
    assert items(pinned, pinned.replace("0.3.0", "0.1.0")) == ["job sh: pin 0.1.0"]
