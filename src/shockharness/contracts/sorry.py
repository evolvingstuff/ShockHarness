"""The sorry count (spec §9): every no-property ``requires(x)`` in the files where
``complete`` applies, for the ``exceptions`` command. Each one is an explicit decision that a
parameter needs nothing, listed alongside suppressions and boundaries."""

from pathlib import Path

from shockharness.analysis import FileResult
from shockharness.config import EffectiveConfig
from shockharness.contracts.catalog import SECTION_PATH, complete_scope, read_text
from shockharness.contracts.report import Considered, ContractFile
from shockharness.rules.property_contracts import considered_declarations
from shockharness.rules.registry import CONTRACT_RULES
from shockharness.source import SourceText

ANALYZED = "analyzed"


def sorry_count(
    files: tuple[FileResult, ...], config: EffectiveConfig, root: Path
) -> tuple[Considered, ...]:
    settings = config.section(SECTION_PATH)
    if settings["enabled"] is not True:
        return ()
    contract_ids = frozenset(rule.rule_id for rule in CONTRACT_RULES)
    chosen: list[ContractFile] = []
    sources: dict[str, tuple[str, SourceText]] = {}
    for file in files:
        if file.status != ANALYZED:
            continue
        text, _why = read_text(root / file.path)
        if text is None:
            continue
        source = SourceText.from_text(text)
        sources[file.path] = (file.language, source)
        applies = contract_ids & frozenset(file.rules_applied)
        if len(applies) > 0:
            complete = complete_scope(settings, file.path)
            chosen.append(ContractFile(file.path, file.language, source, applies, complete))
    return tuple(considered_declarations(chosen, sources, root, settings))
