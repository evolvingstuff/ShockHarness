"""The Python property-contracts runtime file (spec §6, P1a) and ``contracts install``.

The runtime keeps process state by design, so each test loads a fresh copy of the file
by path; the analyzer itself never imports it."""

import gc
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.cli import main
from shockharness.config import EffectiveConfig
from shockharness.constants import EXIT_OK, EXIT_VIOLATIONS
from shockharness.contracts.install import (
    CONTRACTS_MANIFEST,
    check_runtime,
    install_runtime,
    runtime_bytes,
)
from shockharness.errors import UsageError
from shockharness.skills.install import sha256_hex
from tests.conftest import REPO_ROOT

RUNTIME = REPO_ROOT / "src" / "shockharness" / "contracts" / "runtime" / "contracts.py"


class Record:
    """An ordinary object: weakly referenceable."""


class Slotted:
    """No __dict__ and no __weakref__: held strongly."""

    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


@pytest.fixture
def contracts(tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"contracts_{tmp_path.name}", RUNTIME)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_only_before_enable(contracts: ModuleType) -> None:
    value = Record()
    assert contracts.requires(value, "anything") is value
    assert contracts.produces(value, "p") is value
    assert contracts.preserves(value, Record()) is value
    assert contracts.preserves_except(value, Record(), "p") is value
    assert contracts.report() == {"mode": "off", "declarations": 4, "static_skips": {}}


def test_enable_refuses_a_bad_mode_verify_a_second_call_and_a_late_call(
    contracts: ModuleType,
) -> None:
    with pytest.raises(contracts.ContractError, match="takes 'check'"):
        contracts.enable("off", [])
    with pytest.raises(contracts.ContractError, match="verify mode"):
        contracts.enable("verify", [])
    contracts.enable("check", [])
    with pytest.raises(contracts.ContractError, match="already called"):
        contracts.enable("check", [])


def test_enable_after_a_declaration_ran_raises(contracts: ModuleType) -> None:
    contracts.produces(Record(), "p")
    with pytest.raises(contracts.ContractError, match="after 1 declaration"):
        contracts.enable("check", [])


def test_check_mode_records_and_requires(contracts: ModuleType) -> None:
    contracts.enable("check", [])
    value = contracts.produces(Record(), "normalized")
    assert contracts.requires(value, "normalized") is value
    with pytest.raises(contracts.ContractError) as caught:
        contracts.requires(Record(), "normalized")
    assert isinstance(caught.value, AssertionError)
    assert caught.value.property == "normalized"
    assert caught.value.function is None
    assert "does not carry 'normalized'" in caught.value.message


def test_preserves_and_preserves_except_carry_the_source_set(contracts: ModuleType) -> None:
    contracts.enable("check", [])
    source = contracts.produces(Record(), "a", "b")
    kept = contracts.preserves(Record(), source)
    contracts.requires(kept, "a", "b")
    narrowed = contracts.preserves_except(Record(), source, "b")
    contracts.requires(narrowed, "a")
    with pytest.raises(contracts.ContractError):
        contracts.requires(narrowed, "b")


def test_static_properties_are_skipped_and_counted_even_on_strings(contracts: ModuleType) -> None:
    contracts.enable("check", ["redacted"])
    text = contracts.produces("hello", "redacted")
    contracts.requires(text, "redacted")
    contracts.requires("other", "redacted")
    assert contracts.report() == {
        "mode": "check",
        "declarations": 3,
        "static_skips": {"redacted": 3},
    }


def test_a_check_level_property_on_a_scalar_is_a_catalog_mistake(contracts: ModuleType) -> None:
    contracts.enable("check", [])
    for scalar in ("text", 3, 2.5, True, None, b"x"):
        with pytest.raises(contracts.ContractError, match="cannot carry runtime properties"):
            contracts.produces(scalar, "normalized")


def test_lists_and_slotted_objects_are_held_strongly(contracts: ModuleType) -> None:
    contracts.enable("check", [])
    items = contracts.produces([1, 2], "checked")
    slotted = contracts.produces(Slotted(1), "checked")
    contracts.requires(items, "checked")
    contracts.requires(slotted, "checked")
    with pytest.raises(contracts.ContractError):
        contracts.requires([1, 2], "checked")  # an equal list is another value


def test_a_collected_value_is_forgotten(contracts: ModuleType) -> None:
    contracts.enable("check", [])
    contracts.produces(Record(), "p")
    gc.collect()
    assert len(contracts._REGISTRY.entries) == 0


def test_signatures_are_generic_identities(contracts: ModuleType) -> None:
    hints = contracts.requires.__annotations__
    assert hints["value"] is contracts.T and hints["return"] is contracts.T
    assert contracts.preserves.__annotations__["return"] is contracts.T


def test_the_runtime_file_passes_strict_as_production_code(strict_config: EffectiveConfig) -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    options = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
    result = analyze_text("app/contracts.py", "python", text, strict_config, options)
    assert result.status == "analyzed"
    assert [(f.rule_id, f.span.line, f.message) for f in result.findings] == []
    assert "# shockharness: ignore" not in text


# -- contracts install -----------------------------------------------------------------


def test_install_copies_the_file_and_records_it(tmp_path: Path) -> None:
    result = install_runtime(tmp_path, "python", Path("app/contracts.py"), force=False)
    assert result.exit_code == EXIT_OK
    assert (tmp_path / "app" / "contracts.py").read_bytes() == runtime_bytes("python")
    manifest = json.loads((tmp_path / CONTRACTS_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["agent"] == "contracts"
    assert manifest["skills"]["python"] == {
        "path": "app/contracts.py",
        "sha256": sha256_hex(runtime_bytes("python")),
    }
    assert check_runtime(tmp_path).exit_code == EXIT_OK


def test_an_edited_copy_is_drift_and_is_kept_without_force(tmp_path: Path) -> None:
    install_runtime(tmp_path, "python", Path("app/contracts.py"), force=False)
    target = tmp_path / "app" / "contracts.py"
    target.write_bytes(target.read_bytes() + b"# edited\n")
    checked = check_runtime(tmp_path)
    assert checked.exit_code == EXIT_VIOLATIONS
    assert [f.status for f in checked.files] == ["edited"]
    with pytest.raises(UsageError, match="edited since it was installed"):
        install_runtime(tmp_path, "python", Path("app/contracts.py"), force=False)
    install_runtime(tmp_path, "python", Path("app/contracts.py"), force=True)
    assert check_runtime(tmp_path).exit_code == EXIT_OK


def test_an_unedited_older_copy_is_stale(tmp_path: Path) -> None:
    target = tmp_path / "app" / "contracts.py"
    target.parent.mkdir(parents=True)
    older = b"# an older runtime\n"
    target.write_bytes(older)
    manifest = {
        "schema_version": "1",
        "tool_version": "0.0.1",
        "agent": "contracts",
        "skills": {"python": {"path": "app/contracts.py", "sha256": sha256_hex(older)}},
    }
    (tmp_path / CONTRACTS_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    checked = check_runtime(tmp_path)
    assert [f.status for f in checked.files] == ["stale"]
    assert checked.exit_code == EXIT_VIOLATIONS
    install_runtime(tmp_path, "python", Path("app/contracts.py"), force=False)  # unedited


def test_a_file_this_manifest_did_not_write_is_not_replaced(tmp_path: Path) -> None:
    (tmp_path / "contracts.py").write_text("mine\n", encoding="utf-8")
    with pytest.raises(UsageError, match="did not write it"):
        install_runtime(tmp_path, "python", Path("contracts.py"), force=False)
    with pytest.raises(UsageError, match="inside the project"):
        install_runtime(tmp_path, "python", Path("../elsewhere.py"), force=False)


def test_the_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = ["--project", str(tmp_path)]
    assert main(["contracts", "install", "--check", *project]) == 2  # no manifest yet
    install = ["contracts", "install", "--language", "python", "--dest", "app/contracts.py"]
    assert main([*install, *project]) == EXIT_OK
    assert main(["contracts", "install", "--check", *project]) == EXIT_OK
    assert main(["contracts", "install", *project]) == 2  # neither --check nor a destination
    out = capsys.readouterr().out
    assert "up-to-date python" in out
    assert "runtime_module" in out


def test_enable_takes_the_static_properties_as_a_list_of_strings(contracts: ModuleType) -> None:
    for wrong in (("redacted",), {"redacted"}, "redacted", [1], None):
        with pytest.raises(contracts.ContractError, match="list of strings"):
            contracts.enable("check", wrong)
    contracts.enable("check", [])
    assert contracts.report()["mode"] == "check"


def test_static_properties_prints_the_list_to_paste(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "stats"
    root.mkdir()
    (root / ".shockharness.toml").write_text(
        "[tool.shockharness.rules.property_contracts]\n"
        + "".join(
            "[[tool.shockharness.rules.property_contracts.properties]]\n"
            f'name = "{name}"\ndescription = "d"\nproducers = []\nruntime = "{level}"\n'
            for name, level in (("zeta", "static"), ("alpha", "static"), ("beta", "check"))
        ),
        encoding="utf-8",
    )
    assert main(["contracts", "static-properties", "--root", str(root)]) == EXIT_OK
    assert capsys.readouterr().out == '["alpha", "zeta"]\n'


def test_install_javascript_writes_the_module_and_its_declarations(tmp_path: Path) -> None:
    result = install_runtime(tmp_path, "javascript", Path("static/js/vendor/c.js"), force=False)
    assert [(f.language, f.path.name) for f in result.files] == [
        ("javascript", "c.js"),
        ("javascript-types", "c.d.ts"),
    ]
    assert (tmp_path / "static/js/vendor/c.d.ts").read_bytes() == runtime_bytes("javascript-types")
    assert check_runtime(tmp_path).exit_code == EXIT_OK
    (tmp_path / "static/js/vendor/c.d.ts").write_text("// edited\n", encoding="utf-8")
    assert [f.status for f in check_runtime(tmp_path).files] == ["up-to-date", "edited"]
    with pytest.raises(UsageError, match=r"ends in \.js or \.mjs"):
        install_runtime(tmp_path, "javascript", Path("static/js/c.ts"), force=False)
