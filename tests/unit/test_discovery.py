import os
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.config import EffectiveConfig
from shockharness.discovery import discover
from shockharness.errors import UsageError


def touch(root: Path, relative: str, body: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_directory_walk_is_sorted_filtered_and_pruned(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    touch(empty_root, "src/b.py", "")
    touch(empty_root, "src/a.js", "")
    touch(empty_root, "src/c.mjs", "")
    touch(empty_root, "src/d.cjs", "")
    touch(empty_root, "src/readme.md", "")
    touch(empty_root, "src/styles.css", "")
    touch(empty_root, "node_modules/pkg/index.js", "")
    touch(empty_root, "src/node_modules/x.js", "")
    touch(empty_root, ".git/hooks/x.py", "")
    touch(empty_root, "dist/bundle.js", "")
    result = discover(empty_root, [empty_root], strict_config)
    assert [f.relative for f in result.files] == ["src/a.js", "src/b.py", "src/c.mjs", "src/d.cjs"]
    assert {f.relative: f.language for f in result.files}["src/c.mjs"] == "javascript"
    assert result.counts["unsupported_extension"] == 2
    assert result.counts["directories_pruned"] >= 3


def test_explicit_file_is_analyzed_even_if_not_included(
    make_config: Callable[[str], EffectiveConfig], empty_root: Path
) -> None:
    config = make_config('include = ["src/**/*.py"]\n')
    other = touch(empty_root, "scripts/tool.py", "")
    result = discover(empty_root, [other], config)
    assert [f.relative for f in result.files] == ["scripts/tool.py"]


def test_explicit_file_matching_exclude_is_listed_not_hidden(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    vendored = touch(empty_root, "node_modules/x.js", "")
    result = discover(empty_root, [vendored], strict_config)
    assert result.files == ()
    assert [(s.relative, s.reason) for s in result.explicit_excluded] == [
        ("node_modules/x.js", "matches exclude pattern '**/node_modules/**'")
    ]


def test_unsupported_explicit_file_is_a_usage_error(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    ts = touch(empty_root, "a.ts", "")
    with pytest.raises(UsageError, match="unsupported file type"):
        discover(empty_root, [ts], strict_config)


def test_missing_path_is_a_usage_error(empty_root: Path, strict_config: EffectiveConfig) -> None:
    with pytest.raises(UsageError, match="does not exist"):
        discover(empty_root, [empty_root / "nope"], strict_config)


def test_no_targets_is_a_usage_error(empty_root: Path, strict_config: EffectiveConfig) -> None:
    with pytest.raises(UsageError, match="at least one"):
        discover(empty_root, [], strict_config)


def test_target_outside_root_is_a_usage_error(
    tmp_path: Path, empty_root: Path, strict_config: EffectiveConfig
) -> None:
    outside = tmp_path / "elsewhere.py"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(UsageError, match="outside the analysis root"):
        discover(empty_root, [outside], strict_config)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlinks_are_skipped_unless_configured(
    tmp_path: Path, empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    real = tmp_path / "outside"
    real.mkdir()
    (real / "leak.py").write_text("x = 99\n", encoding="utf-8")
    touch(empty_root, "src/ok.py", "")
    (empty_root / "src" / "link").symlink_to(real, target_is_directory=True)
    (empty_root / "src" / "file_link.py").symlink_to(real / "leak.py")

    strict = make_config("")
    result = discover(empty_root, [empty_root], strict)
    assert [f.relative for f in result.files] == ["src/ok.py"]
    assert result.counts["symlinks_skipped"] == 2

    following = make_config("follow_symlinks = true\n")
    with pytest.raises(UsageError, match="outside the analysis root"):
        discover(empty_root, [empty_root], following)


def test_duplicate_targets_collapse(empty_root: Path, strict_config: EffectiveConfig) -> None:
    file = touch(empty_root, "src/a.py", "")
    result = discover(empty_root, [file, empty_root / "src", file], strict_config)
    assert [f.relative for f in result.files] == ["src/a.py"]
