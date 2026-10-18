"""The catalog's references resolved against the project's files (spec §8.1): every
Python and JavaScript producer and sink reference of an enabled section. An unresolved
one is a configuration error, raised before an analysis and by ``config validate``."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shockharness.contracts.catalog import python_reference_issues
from shockharness.contracts.javascript_index import javascript_reference_issues
from shockharness.schema import ConfigIssue


def reference_issues(root: Path, values: Mapping[str, Any]) -> list[ConfigIssue]:
    if values["rules"]["property_contracts"]["enabled"] is not True:
        return []
    return [*python_reference_issues(root, values), *javascript_reference_issues(root, values)]
