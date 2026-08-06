"""Diagnostics and their severities.

Severity is looked up from :data:`SEVERITY`, never chosen at the call site. A
caller that could pick its own severity would eventually downgrade a real
completeness blocker into a warning, which is precisely the failure this
project exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .timeline import TimeInterval


class Severity(Enum):
    """What a diagnostic does to the run status.

    Informational diagnostics never change status. A completeness blocker forbids
    trusted completeness but keeps the research useful. A fatal research failure
    means no useful research pack can be produced.
    """

    INFORMATIONAL = "informational"
    COMPLETENESS_BLOCKER = "completeness_blocker"
    FATAL = "fatal_research_failure"


class DiagnosticCode(Enum):
    SOURCE_OUT_OF_ENVELOPE = "source_out_of_envelope"
    EXTRACTION_FAILED = "extraction_failed"
    NO_USABLE_TRANSCRIPT = "no_usable_transcript"
    CANONICAL_SCHEMA_INVALID = "canonical_schema_invalid"

    TRANSCRIPT_TRUNCATED = "transcript_truncated"
    TRANSCRIPT_LANGUAGE_UNEXPECTED = "transcript_language_unexpected"
    TRANSCRIPT_TIMING_NONMONOTONIC = "transcript_timing_nonmonotonic"
    TRANSCRIPT_FALLBACK_UNAVAILABLE = "transcript_fallback_unavailable"
    TIMELINE_NOT_PARTITIONED = "timeline_not_partitioned"
    WINDOW_UNOBSERVED = "window_unobserved"
    MATERIAL_CLAIM_UNSUPPORTED = "material_claim_unsupported"
    EVIDENCE_OUT_OF_RANGE = "evidence_out_of_range"
    MATERIAL_UNIT_UNREPRESENTED = "material_unit_unrepresented"
    OUTPUT_TRUNCATED = "output_truncated"
    MANUAL_RESCUE_USED = "manual_rescue_used"
    VERIFIER_DISAGREEMENT = "verifier_disagreement"

    DUPLICATE_EVIDENCE = "duplicate_evidence"
    FRAME_SAMPLING_SPARSE = "frame_sampling_sparse"


SEVERITY: dict[DiagnosticCode, Severity] = {
    DiagnosticCode.SOURCE_OUT_OF_ENVELOPE: Severity.FATAL,
    DiagnosticCode.EXTRACTION_FAILED: Severity.FATAL,
    DiagnosticCode.NO_USABLE_TRANSCRIPT: Severity.FATAL,
    DiagnosticCode.CANONICAL_SCHEMA_INVALID: Severity.FATAL,
    DiagnosticCode.TRANSCRIPT_TRUNCATED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.TRANSCRIPT_LANGUAGE_UNEXPECTED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.TRANSCRIPT_TIMING_NONMONOTONIC: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.TRANSCRIPT_FALLBACK_UNAVAILABLE: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.TIMELINE_NOT_PARTITIONED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.WINDOW_UNOBSERVED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.EVIDENCE_OUT_OF_RANGE: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.MATERIAL_UNIT_UNREPRESENTED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.OUTPUT_TRUNCATED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.MANUAL_RESCUE_USED: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.VERIFIER_DISAGREEMENT: Severity.COMPLETENESS_BLOCKER,
    DiagnosticCode.DUPLICATE_EVIDENCE: Severity.INFORMATIONAL,
    DiagnosticCode.FRAME_SAMPLING_SPARSE: Severity.INFORMATIONAL,
}


@dataclass(frozen=True)
class Diagnostic:
    """One detected condition, with a severity fixed by its code."""

    code: DiagnosticCode
    detail: str
    interval: TimeInterval | None = None

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.code]

    def describe(self) -> str:
        where = f" [{self.interval.label()}]" if self.interval else ""
        return f"{self.code.value}{where}: {self.detail}"


def blockers(diagnostics: tuple[Diagnostic, ...]) -> tuple[Diagnostic, ...]:
    return tuple(d for d in diagnostics if d.severity is Severity.COMPLETENESS_BLOCKER)


def fatals(diagnostics: tuple[Diagnostic, ...]) -> tuple[Diagnostic, ...]:
    return tuple(d for d in diagnostics if d.severity is Severity.FATAL)
