from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Literal


@dataclass(frozen=True)
class ExpansionEvidence:
    input_skill: str
    canonical_skill: str
    target: str
    target_kind: Literal["skill", "category"]
    relations: tuple[str, ...]
    nodes: tuple[str, ...]
    depth: int
    weight: float

    def to_dict(self) -> dict:
        value = asdict(self)
        value["relations"] = list(self.relations)
        value["nodes"] = list(self.nodes)
        return value


@dataclass(frozen=True)
class ExpansionResult:
    evidence: tuple[ExpansionEvidence, ...] = ()

    @classmethod
    def from_iterable(cls, values: Iterable[ExpansionEvidence]) -> "ExpansionResult":
        ordered = sorted(
            values,
            key=lambda item: (
                item.input_skill.casefold(),
                item.target.casefold(),
                -item.weight,
                item.depth,
                item.nodes,
                item.relations,
            ),
        )
        return cls(tuple(ordered))

    def targets(self) -> set[str]:
        return {item.target for item in self.evidence}

    def to_dict(self) -> dict:
        return {"evidence": [item.to_dict() for item in self.evidence]}
