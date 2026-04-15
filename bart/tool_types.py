from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable
    requires_confirmation: bool = False
    confirmation_reason: str = "This action changes your computer state."
