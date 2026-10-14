"""DEF001 dataclass kinds: field defaults and default_factory; ClassVar and plain classes are not."""

import dataclasses
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class Settings:
    host: str
    port: int = 5432
    name: str = "app"
    tags: list = field(default_factory=list)
    label: str = field(default="none")
    registry: ClassVar[dict] = {}
    required: float = field()


@dataclasses.dataclass(frozen=True)
class Frozen:
    value: int
    scale: float = 1.0


class Plain:
    limit = 10
    label: str = "plain"

    def __init__(self, limit):
        self.limit = limit
