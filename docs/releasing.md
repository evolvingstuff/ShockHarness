# Releasing ShockHarness

Releases are tag-triggered (specification section 20, decision 9). Pushing a
tag `vX.Y.Z` runs `.github/workflows/publish.yml`, which runs the full CI
workflow (ubuntu, macos, windows x Python 3.11-3.14, the self-gate, the
package smoke test, and the consumer-example upgrade check), builds the wheel
and sdist with `python -m build`, refuses to continue unless the tag equals
`src/shockharness/version.py`, and publishes to PyPI through **trusted
publishing**. No API token is stored in the repository or in GitHub secrets.

## One-time setup (maintainer)

1. On PyPI, open the `shockharness` project, *Manage* -> *Publishing*, and add
   a **GitHub** trusted publisher with exactly these values:

   | Field | Value |
   |---|---|
   | PyPI project name | `shockharness` |
   | Owner | `evolvingstuff` |
   | Repository name | `ShockHarness` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   (`shockharness` already exists on PyPI because 0.1.0a1 was uploaded with a
   token on 2026-10-14; the publisher is added to the existing project, not as
   a *pending* publisher. If the project were ever deleted, the same values go
   under *Add a new pending publisher* instead.)

2. On GitHub, *Settings* -> *Environments* -> *New environment* named `pypi`.
   Optional but recommended: add yourself as a required reviewer so a tag push
   still needs one click before anything reaches PyPI, and restrict deployment
   branches/tags to `v*`.

3. Nothing else: `publish.yml` already declares `environment: pypi` and
   `permissions: id-token: write` on the publish job and uses
   `pypa/gh-action-pypi-publish@release/v1` without a token input.

## Per-release steps

1. Pick the version. `0.1.0` is reserved for the release after Milestone F;
   pre-releases use PEP 440 forms such as `0.1.0a2`, `0.1.0rc1`.
2. Edit `src/shockharness/version.py` (`__version__ = "X.Y.Z"`); it is the only
   place the version lives (hatchling reads it at build time).
3. Move the `[Unreleased]` section of `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`.
   Call out rule or default-policy changes first: tightening a default gate is a
   breaking change for consumers.
4. Run the checks locally once more:

   ```bash
   ruff check src tests scripts && ruff format --check src tests scripts
   pytest -q
   shockharness check src tests scripts
   python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
   ```

5. Commit (`Release X.Y.Z`), then tag and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "shockharness X.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```

6. Watch the *Publish to PyPI* run. If the version check fails ("tag ... does
   not match"), delete the tag, fix `version.py`, and tag again; nothing was
   uploaded. After it succeeds, `pip install shockharness==X.Y.Z` is the
   consumer pin, and consumers' Dependabot opens upgrade PRs on their schedule.

7. Consumers pin the reusable workflow to the same tag
   (`.github/workflows/check.yml@vX.Y.Z`) or, preferably, to the tag's full
   commit SHA (`git rev-parse vX.Y.Z`). Tags are never moved.

## What the workflow checks before publishing

* The full CI matrix passed on the tagged commit (`uses: ./.github/workflows/ci.yml`).
* `GITHUB_REF_NAME` equals `v` + `__version__`.
* `dist/` contains `shockharness-X.Y.Z-py3-none-any.whl` and `shockharness-X.Y.Z.tar.gz`.
* The wheel installs in a clean venv and `shockharness version` prints `shockharness X.Y.Z`.
* The PyPI action verifies the distribution metadata before uploading.

A failed step anywhere stops the release; a tag never publishes a partially
checked build.
