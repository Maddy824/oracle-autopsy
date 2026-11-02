"""Evidence-bearing results shared by the honesty checks."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CheckResult:
    name: str
    verdict: Literal["PASS", "FAIL", "CAN'T TELL"]
    evidence: dict


__all__ = ["CheckResult"]
