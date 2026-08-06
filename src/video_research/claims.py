"""The atomic claim ledger: claims, their roles, and their evidence edges."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .timeline import SourceSpan


class ClaimRole(Enum):
    """The epistemic basis of a claim. Every claim has exactly one.

    The split exists so that "the speaker claims X", "the video visibly shows X",
    "we inferred X", and "outside evidence supports X" can never be presented as
    the same kind of statement.
    """

    SOURCE_ASSERTION = "source_assertion"
    VISUAL_DEMONSTRATION = "visual_demonstration"
    AGENT_INFERENCE = "agent_inference"
    EXTERNAL_FACT = "external_fact"


class EvidenceRelation(Enum):
    """How a piece of evidence bears on a claim."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


@dataclass(frozen=True)
class EvidenceReference:
    """An edge from a claim to a source location, carrying its relation.

    The relation lives on the edge rather than on the location because one span
    can support one claim and qualify another.
    """

    claim_id: str
    span: SourceSpan
    relation: EvidenceRelation
    note: str = ""


@dataclass(frozen=True)
class ExternalReference:
    """Evidence from outside the source video, recorded separately from it."""

    claim_id: str
    url: str
    title: str
    relation: EvidenceRelation


@dataclass(frozen=True)
class AtomicClaim:
    """One independently assessable statement drawn from the source.

    ``covers_units`` is what makes "every material content unit appears" a
    checkable property: without an explicit link from claims back to units,
    material recall cannot be validated from the canonical artifacts at all.
    """

    claim_id: str
    statement: str
    role: ClaimRole
    material: bool
    covers_units: tuple[str, ...] = ()
    speaker_label: str | None = None


@dataclass(frozen=True)
class ClaimLedger:
    """Every claim in a run, with its video evidence and any external evidence.

    A claim keeps its video evidence even when external verification promotes its
    role to :attr:`ClaimRole.EXTERNAL_FACT`, so that checking a claim against the
    outside world never erases where it came from in the source.
    """

    claims: tuple[AtomicClaim, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    external: tuple[ExternalReference, ...] = field(default_factory=tuple)

    def evidence_for(self, claim_id: str) -> tuple[EvidenceReference, ...]:
        return tuple(e for e in self.evidence if e.claim_id == claim_id)

    def external_for(self, claim_id: str) -> tuple[ExternalReference, ...]:
        return tuple(e for e in self.external if e.claim_id == claim_id)

    def material_claims(self) -> tuple[AtomicClaim, ...]:
        return tuple(c for c in self.claims if c.material)

    def covered_unit_ids(self) -> frozenset[str]:
        return frozenset(
            uid for c in self.material_claims() for uid in c.covers_units
        )

    def claim_ids(self) -> frozenset[str]:
        return frozenset(c.claim_id for c in self.claims)
