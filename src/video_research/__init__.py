"""Video Research: evidence-backed video summaries with an honest verdict.

The package is three layers, and the import direction between them is the
architecture:

    adapters   impure edges — extraction, claim extraction, verification
       │       (each implements a protocol from `ports`)
       ▼
    core       timeline · claims · diagnostics · run · gates · status
       │       pure, no I/O, no model calls; decides complete/partial/failed
       ▼
    views      summary.md and report.html, pure functions of canonical data

The core never imports an adapter. Views never see anything but a research
pack. Run status has exactly one producer, :func:`video_research.status.decide`.
"""

from .claims import (
    AtomicClaim,
    ClaimLedger,
    ClaimRole,
    EvidenceReference,
    EvidenceRelation,
    ExternalReference,
)
from .diagnostics import Diagnostic, DiagnosticCode, Severity
from .ports import (
    CheckOutcome,
    ClaimExtractor,
    ExtractedSource,
    ExtractionEngine,
    ExtractionError,
    IndependentVerifier,
    VerifierCheck,
    VerifierReport,
)
from .run import ResearchPack, RunRecord, RunStatus, SourceDescriptor, SupportEnvelope
from .skill import FIXTURE_ENVELOPE, research_video
from .timeline import (
    CoverageManifest,
    CoverageWindow,
    MaterialContentUnit,
    SourceSpan,
    SpanKind,
    SpeechCoverage,
    TimeInterval,
    VisualObservation,
)

__version__ = "0.1.0"

__all__ = [
    "FIXTURE_ENVELOPE",
    "AtomicClaim",
    "CheckOutcome",
    "ClaimExtractor",
    "ClaimLedger",
    "ClaimRole",
    "CoverageManifest",
    "CoverageWindow",
    "Diagnostic",
    "DiagnosticCode",
    "EvidenceReference",
    "EvidenceRelation",
    "ExternalReference",
    "ExtractedSource",
    "ExtractionEngine",
    "ExtractionError",
    "IndependentVerifier",
    "MaterialContentUnit",
    "ResearchPack",
    "RunRecord",
    "RunStatus",
    "Severity",
    "SourceDescriptor",
    "SourceSpan",
    "SpanKind",
    "SpeechCoverage",
    "SupportEnvelope",
    "TimeInterval",
    "VerifierCheck",
    "VerifierReport",
    "VisualObservation",
    "__version__",
    "research_video",
]
