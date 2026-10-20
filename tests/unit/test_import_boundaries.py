"""IMPORT002: an import across a boundary the project declared."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import ConfigError, load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
HEADER = '[tool.shockharness]\nprofile = "strict"\ninclude = ["app/**/*.py", "web/**/*.js"]\n'
# MetaList's two pairs (its BKP001 startup check): startup and migrations may not import
# the backup service; the auth service may import only create_timestamped_backup from it.
BOUNDARIES = """
[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["app/main.py", "app/db/migrations.py"]
imported = ["app/services/backup_service.py"]
allowed_names = []
reason = "a migration can never touch a backup"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["app/services/auth_service.py"]
imported = ["app/services/backup_service.py"]
allowed_names = ["create_timestamped_backup"]
reason = "authentication may only take a new backup"
"""
SERVICE = (
    "def create_timestamped_backup():\n    return 0\n\n\ndef restore_backup():\n    return 1\n"
)


def write(root: Path, files: dict[str, str], config: str) -> None:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def found(root: Path, files: dict[str, str], config: str = HEADER + BOUNDARIES) -> list[str]:
    write(root, files, config)
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return sorted(
        f"{f.path}:{f.span.line} {f.severity} {f.message}"
        for f in report.findings
        if f.rule_id == "IMPORT002"
    )


def app(files: dict[str, str]) -> dict[str, str]:
    return {
        "app/__init__.py": "",
        "app/db/__init__.py": "",
        "app/services/__init__.py": "",
        "app/services/backup_service.py": SERVICE,
        **files,
    }


def test_every_import_form_across_a_boundary_is_reported(tmp_path: Path) -> None:
    migrations = (
        "from app.services.backup_service import restore_backup\n"
        "import app.services.backup_service\n"
        "from app.services import backup_service\n"
        "from ..services import backup_service as relative\n\n\n"
        "def migrate():\n"
        "    from app.services.backup_service import create_timestamped_backup\n"
        "    return create_timestamped_backup\n"
    )
    reported = found(tmp_path, app({"app/db/migrations.py": migrations}))
    lines = [line.split(" ")[0] for line in reported]
    assert lines == [f"app/db/migrations.py:{n}" for n in (1, 2, 3, 4, 8)]


def test_the_message_names_the_module_and_the_reason(tmp_path: Path) -> None:
    files = app({"app/main.py": "from app.services.backup_service import restore_backup\n"})
    assert found(tmp_path, files) == [
        "app/main.py:1 error imports app/services/backup_service.py, which this file may not "
        "import: a migration can never touch a backup"
    ]


def test_allowed_names_pass_and_the_rest_are_reported(tmp_path: Path) -> None:
    auth = (
        "from app.services.backup_service import create_timestamped_backup\n"
        "from app.services.backup_service import create_timestamped_backup, restore_backup\n"
        "from app.services import backup_service\n"
        "from app.services.backup_service import *\n"
    )
    assert found(tmp_path, app({"app/services/auth_service.py": auth})) == [
        "app/services/auth_service.py:2 error imports restore_backup from "
        "app/services/backup_service.py; only create_timestamped_backup may be imported from "
        "it here: authentication may only take a new backup",
        "app/services/auth_service.py:3 error imports all of app/services/backup_service.py; "
        "only create_timestamped_backup may be imported from it here: authentication may "
        "only take a new backup",
        "app/services/auth_service.py:4 error imports all of app/services/backup_service.py; "
        "only create_timestamped_backup may be imported from it here: authentication may "
        "only take a new backup",
    ]


def test_files_the_boundary_does_not_bind_import_freely(tmp_path: Path) -> None:
    files = app(
        {
            "app/services/restore.py": "from app.services.backup_service import restore_backup\n",
            "app/db/migrations.py": "from app.db import schema\n",
            "app/db/schema.py": "VERSION = 1\n",
        }
    )
    assert found(tmp_path, files) == []


def test_javascript_imports_requires_and_dynamic_imports(tmp_path: Path) -> None:
    config = (
        HEADER
        + """
[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["web/boot/**"]
imported = ["web/backup/*.js"]
allowed_names = ["takeBackup"]
reason = "startup only takes a backup"
"""
    )
    boot = (
        "import { takeBackup } from '../backup/store.js';\n"
        "import { restore } from '../backup/store.js';\n"
        "import * as store from '../backup/store.js';\n"
        "const { takeBackup: t } = require('../backup/store.js');\n"
        "export async function later() { return import('../backup/store.js'); }\n"
        "export { restore as undo } from '../backup/store.js';\n"
    )
    files = {
        "web/backup/store.js": "export function takeBackup() {}\nexport function restore() {}\n",
        "web/boot/start.js": boot,
    }
    lines = [line.split(" ")[0] for line in found(tmp_path, files, config)]
    assert lines == [f"web/boot/start.js:{n}" for n in (2, 3, 5, 6)]


def test_no_entry_means_the_rule_is_not_applied(tmp_path: Path) -> None:
    write(tmp_path, app({"app/main.py": "from app.services.backup_service import x\n"}), HEADER)
    report = analyze_paths([tmp_path], tmp_path, load_config(tmp_path, None), OPTIONS)
    assert all("IMPORT002" not in f.rules_applied for f in report.files)


def test_a_boundary_kept_on_purpose_can_be_suppressed(tmp_path: Path) -> None:
    main = (
        "from app.services.backup_service import restore_backup"
        '  # shockharness: ignore[IMPORT002] reason="the recovery screen restores"\n'
    )
    write(tmp_path, app({"app/main.py": main}), HEADER + BOUNDARIES)
    report = analyze_paths([tmp_path], tmp_path, load_config(tmp_path, None), OPTIONS)
    reported = [f for f in report.findings if f.rule_id == "IMPORT002"]
    assert len(reported) == 1 and reported[0].suppression is not None


def _invalid(root: Path, entry: str) -> str:
    (root / ".shockharness.toml").write_text(HEADER + entry, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_config(root, None)
    return str(raised.value)


def test_an_entry_needs_allowed_names_and_a_glob_on_each_side(tmp_path: Path) -> None:
    table = "[[tool.shockharness.rules.import_boundaries.forbidden]]\n"
    missing = table + 'importers = ["app/a.py"]\nimported = ["app/x.py"]\nreason = "r"\n'
    assert "forbidden[0].allowed_names: required key is missing" in _invalid(tmp_path, missing)
    empty = table + 'importers = []\nimported = ["app/x.py"]\nallowed_names = []\nreason = "r"\n'
    assert "forbidden[0].importers: must list at least one path glob" in _invalid(tmp_path, empty)


def _entry(importers: str, allowed: str) -> str:
    return (
        "[[tool.shockharness.rules.import_boundaries.forbidden]]\n"
        f"importers = [{importers}]\n"
        'imported = ["app/services/backup_service.py"]\n'
        f"allowed_names = [{allowed}]\n"
        'reason = "a migration can never touch a backup"\n'
    )


def test_removing_narrowing_or_allowing_more_is_a_loosening(tmp_path: Path) -> None:
    def keys(after_entries: str) -> list[str]:
        config = tmp_path / ".shockharness.toml"
        config.write_text(HEADER + _entry('"app/main.py", "app/db/*.py"', ""), encoding="utf-8")
        before = load_config(tmp_path, None)
        config.write_text(HEADER + after_entries, encoding="utf-8")
        after = load_config(tmp_path, None)
        found = loosenings(before.values, before.deviations, after.values, after.deviations)
        return [item.key for item in found]

    loosened = ["rules.import_boundaries.forbidden"]
    assert keys("") == loosened
    assert keys(_entry('"app/main.py"', "")) == loosened
    assert keys(_entry('"app/main.py", "app/db/*.py"', '"restore_backup"')) == loosened
    widened = _entry('"app/main.py", "app/db/*.py", "app/cli.py"', "")
    assert keys(widened) == []
    split = _entry('"app/main.py"', "") + _entry('"app/db/*.py", "app/main.py"', "")
    assert keys(split) == []
