from dataclasses import dataclass
from typing import Protocol

from reaction_reference.domain.models import Material, QueryFamily, ReactionRecord


@dataclass(frozen=True)
class Candidate:
    structure_id: str
    material: Material
    record: ReactionRecord


@dataclass(frozen=True)
class CandidatePage:
    items: list[Candidate]
    next_cursor: int | None
    stream_exhausted: bool
    scope_complete: bool
    enumeration_kind: str


class CompoundSource(Protocol):
    snapshot_id: str
    issues: list[dict]

    def candidate_page(
        self,
        family: QueryFamily,
        role: str,
        cursor: int,
        limit: int,
        target_smiles: str,
        stage: int = 0,
    ) -> CandidatePage: ...

    def close(self) -> None: ...

    def hydrate(self, record: ReactionRecord) -> ReactionRecord: ...
