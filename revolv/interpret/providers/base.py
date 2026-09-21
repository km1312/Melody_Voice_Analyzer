"""The provider protocol: one interface, any model (G5).

A provider declares how far its requests travel (`egress`), and the runner
refuses anything `remote` in Phase 1. `Completion.raw` is whatever the
endpoint returned and is never logged.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol


class ProviderError(RuntimeError):
    """The provider could not produce a completion."""


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    seconds: float
    model: str
    provider: str
    raw: dict = field(default_factory=dict)  # never logged


class Provider(Protocol):
    id: str                                   # "manual", "openai_compat", ...
    egress: Literal["none", "loopback", "remote"]

    def complete(self, *, system: str, user: str,
                 json_schema: dict | None,
                 temperature: float, seed: int | None,
                 max_tokens: int) -> Completion: ...
