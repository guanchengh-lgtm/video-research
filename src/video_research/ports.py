"""The seams between the assurance core and everything impure.

Extraction touches the network, ffmpeg, ASR, and OCR. Claim extraction and
semantic verification call a language model. None of that can run inside a
deterministic gate, so each crosses into the core through a port and hands over
plain data. Swapping the extraction engine means writing one adapter here; it
does not touch the assurance layer (spec: canonical interfaces never expose
engine-specific output shapes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from .claims import ClaimLedger
from .diagnostics import Diagnostic
from .run import EngineIdentity, SourceDescriptor, Transcript
from .timeline import CoverageWindow, MaterialContentUnit, SourceSpan


class ExtractionError(RuntimeError):
    """Raised by an extraction engine that cannot produce a usable source."""


@dataclass(frozen=True)
class ExtractedSource:
    """Everything one extraction pass produced, in engine-neutral shape.

    ``declared_material_units`` is populated by benchmark fixtures that know what
    a correct summary must contain. An arbitrary video declares none, which
    leaves material recall unverifiable and therefore forces a partial run.
    """

    descriptor: SourceDescriptor
    engine: EngineIdentity
    transcript: Transcript
    windows: tuple[CoverageWindow, ...] = field(default_factory=tuple)
    frames: tuple[SourceSpan, ...] = field(default_factory=tuple)
    ocr_spans: tuple[SourceSpan, ...] = field(default_factory=tuple)
    declared_material_units: tuple[MaterialContentUnit, ...] = field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)
    fallback_available: bool = True


@runtime_checkable
class ExtractionEngine(Protocol):
    """Turns a source reference into raw, engine-neutral artifacts."""

    def describe(self, source_ref: str) -> SourceDescriptor:
        """Cheaply identify the source so the envelope can reject it before
        an expensive extraction runs."""

    def extract(self, source_ref: str) -> ExtractedSource:
        """Produce transcript, frames, OCR, and coverage windows.

        Raises :class:`ExtractionError` when no usable source can be produced.
        """


@runtime_checkable
class ClaimExtractor(Protocol):
    """Turns extracted source material into an atomic claim ledger."""

    def extract_claims(self, source: ExtractedSource) -> ClaimLedger:
        ...


class CheckOutcome(Enum):
    """A verifier check's verdict.

    ``UNVERIFIED`` is not a pass. A check nobody could decide leaves the run
    partial, because absence of evidence is not evidence of completeness.
    """

    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class VerifierCheck:
    name: str
    outcome: CheckOutcome
    detail: str = ""


@dataclass(frozen=True)
class VerifierReport:
    checks: tuple[VerifierCheck, ...] = field(default_factory=tuple)

    def failing(self) -> tuple[VerifierCheck, ...]:
        return tuple(c for c in self.checks if c.outcome is not CheckOutcome.PASS)


@runtime_checkable
class IndependentVerifier(Protocol):
    """Reviews a finished run from the canonical artifacts alone.

    The argument is a directory, not the in-memory pack, and that is the point:
    the verifier reads what was actually written, so it cannot inherit the
    generator's reasoning and a serialization bug cannot hide behind objects
    that never went to disk.
    """

    def verify(self, pack_dir: Path) -> VerifierReport:
        ...
