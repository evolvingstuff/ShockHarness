"""Structural checks on the GitHub Actions workflows, Dependabot config, and hook entry.

No YAML parser is available (stdlib only), so these tests check the lines the
specification requires rather than parsing the documents.
"""

from pathlib import Path

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def read(relative: str) -> str:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert "\t" not in text, f"{relative}: YAML must not contain tabs"
    assert (
        text.lstrip().startswith("name:")
        or text.lstrip().startswith("#")
        or (text.lstrip().startswith("version:"))
    ), relative
    return text


def test_ci_workflow_uses_check_and_is_callable() -> None:
    text = read(".github/workflows/ci.yml")
    assert "workflow_call:" in text
    assert "shockharness check src tests scripts" in text
    assert "shockharness scan" not in text
    assert "scripts/consumer_upgrade_check.py" in text
    assert "ruff check src tests scripts evals" in text
    assert "shockharness check src tests scripts evals" in text
    assert "python evals/run_evals.py --reference --output scorecard.json" in text
    assert "shockharness skills install --agent claude" in text
    assert "shockharness skills install --agent codex" in text
    assert "shockharness skills install --agent generic --project agent-skills" in text
    assert "shockharness skills update --agent claude --check" in text
    assert "/tmp/clean/bin/shockharness skills list" in text
    assert text.count("skill-evals:") == 1 and "actions/setup-node@v7" in text
    assert "--wheelhouse wheelhouse" in text
    assert "pip download --dest wheelhouse dist/shockharness-*.whl" in text
    for python in ('"3.11"', '"3.12"', '"3.13"', '"3.14"'):
        assert python in text
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in text


def test_publish_workflow_is_tag_triggered_trusted_publishing() -> None:
    text = read(".github/workflows/publish.yml")
    assert 'tags: ["v*"]' in text
    assert "uses: ./.github/workflows/ci.yml" in text
    assert "python -m build" in text
    assert "GITHUB_REF_NAME" in text and "version.py" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "id-token: write" in text
    assert "name: pypi" in text
    assert "password:" not in text
    assert "PYPI_API_TOKEN" not in text and "secrets." not in text


def test_reusable_check_workflow_inputs_and_permissions() -> None:
    text = read(".github/workflows/check.yml")
    assert "workflow_call:" in text
    for name in ("shockharness-version:", "config:", "base:", "python-version:"):
        assert name in text
    assert "required: true" in text
    assert 'default: "3.12"' in text
    assert '"shockharness==${SHOCKHARNESS_VERSION}"' in text
    assert "--format sarif --output shockharness.sarif" in text
    assert 'gate --base "${SHOCKHARNESS_BASE}" --head HEAD' in text
    assert "shockharness check ." in text
    assert "github/codeql-action/upload-sarif@v4" in text
    assert "contents: read" in text and "security-events: write" in text
    assert "write-all" not in text and "id-token" not in text
    assert "fetch-depth: 0" in text


def test_check_workflow_fetches_the_policy_outside_the_workspace() -> None:
    text = read(".github/workflows/check.yml")
    for name in ("policy-repository:", "policy-ref:", "policy-path:", "policy-token:"):
        assert name in text
    assert '"${RUNNER_TEMP}/shockharness-policy"' in text
    assert 'args+=(--policy "${RUNNER_TEMP}/shockharness-policy/${POLICY_PATH}")' in text
    assert "if: ${{ inputs.policy-repository != '' }}" in text
    # A token is only ever read from the secret, never from an input.
    assert "${{ secrets.policy-token }}" in text
    assert "inputs.policy-token" not in text


def test_dependabot_covers_actions_and_pip_weekly() -> None:
    text = read(".github/dependabot.yml")
    assert "version: 2" in text
    assert "package-ecosystem: github-actions" in text
    assert "package-ecosystem: pip" in text
    assert text.count("interval: weekly") == 2


def test_pre_commit_hook_uses_check() -> None:
    text = (REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "entry: shockharness check" in text


def test_example_workflows_call_the_reusable_workflow_pinned() -> None:
    for example in ("python", "js"):
        text = read(f"examples/{example}/.github/workflows/shockharness.yml")
        assert "uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@" in text
        assert "@main" not in text
        assert 'shockharness-version: "0.32.0"' in text
        assert "security-events: write" in text
        dependabot = read(f"examples/{example}/.github/dependabot.yml")
        assert "package-ecosystem: github-actions" in dependabot
    pyproject = (REPO_ROOT / "examples" / "python" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"shockharness==0.32.0"' in pyproject
    package = (REPO_ROOT / "examples" / "js" / "package.json").read_text(encoding="utf-8")
    assert "shockharness" not in package.split('"scripts"')[0]  # never an npm dependency
    assert "shockharness check ." in package


def test_docs_and_readme_use_check_not_scan() -> None:
    for relative in ("README.md", "docs/configuration.md", "docs/integration.md"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "shockharness scan" not in text, relative
    assert Path(REPO_ROOT / "docs" / "releasing.md").is_file()
