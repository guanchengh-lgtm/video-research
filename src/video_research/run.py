"""The support envelope, the transcript, the run record, and the research pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .claims import ClaimLedger
from .diagnostics import Diagnostic
from .timeline import CoverageManifest, Millis, TimeInterval


class RunStatus(Enum):
    """A run finishes as exactly one of these."""

    TRUSTED_COMPLETE = "trusted_complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceDescriptor:
    """What is known about a source before the expensive extraction runs."""

    source_ref: str
    source_kind: str
    duration_ms: Millis
    language: str | None = None
    title: str = ""
    digest: str | None = None


@dataclass(frozen=True)
class SupportEnvelope:
    """The declared conditions inside which a run may claim trusted completeness.

    Conditions are enumerated rather than implied. "YouTube, but not private or
    live" does not bound a run: it says nothing about duration or language, so
    trusted completeness against it would be circular. A source this envelope
    does not explicitly admit is outside it.
    """

    envelope_id: str
    admitted_source_kinds: frozenset[str]
    max_duration_ms: Millis | None = None
    admitted_languages: frozenset[str] | None = None
    requires_known_duration: bool = True

    def rejection_reason(self, descriptor: SourceDescriptor) -> str | None:
        """Return why the source falls outside this envelope, or ``None``."""
        if descriptor.source_kind not in self.admitted_source_kinds:
            admitted = ", ".join(sorted(self.admitted_source_kinds))
            return f"source kind {descriptor.source_kind!r} is not admitted (admits: {admitted})"
        if self.requires_known_duration and descriptor.duration_ms <= 0:
            return "source duration is unknown"
        if self.max_duration_ms is not None and descriptor.duration_ms > self.max_duration_ms:
            return (
                f"source runs {descriptor.duration_ms} ms, "
                f"beyond the {self.max_duration_ms} ms ceiling"
            )
        if self.admitted_languages is not None:
            if descriptor.language is None:
                return "source language is unknown"
            if descriptor.language not in self.admitted_languages:
                return f"source language {descriptor.language!r} is not admitted"
        return None


class TranscriptKind(Enum):
    """Where a transcript came from.

    ``NATIVE_CAPTIONS`` that fail validation must be replaced by an
    ``ASR_FALLBACK``; captions are candidate evidence until they pass.
    """

    NATIVE_CAPTIONS = "native_captions"
    ASR_FALLBACK = "asr_fallback"
    NONE = "none"


@dataclass(frozen=True)
class TranscriptSegment:
    interval: TimeInterval
    text: str
    speaker_label: str | None = None


@dataclass(frozen=True)
class Transcript:
    kind: TranscriptKind
    language: str | None
    segments: tuple[TranscriptSegment, ...] = field(default_factory=tuple)

    @property
    def spoken_ms(self) -> Millis:
        return sum(s.interval.duration_ms for s in self.segments)

    @property
    def last_end_ms(self) -> Millis:
        return max((s.interval.end_ms for s in self.segments), default=0)


@dataclass(frozen=True)
class EngineIdentity:
    """Which extraction engine produced the raw artifacts, and at what version."""

    name: str
    version: str
    outbound_data: str = "none"


@dataclass(frozen=True)
class GateRecord:
    """A gate's verdict, as stored in the canonical run record."""

    gate_id: str
    name: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class VerifierRecord:
    """One independent-verifier check, as stored in the canonical run record."""

    name: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class RunRecord:
    """The canonical record of one run.

    ``run_id`` is minted once at run start and stored, never derived from the
    source. A cold rerun of the same source and configuration is a distinct run,
    so a content-derived identifier would collide with the very run it must not
    inherit findings from.
    """

    run_id: str
    created_at: str
    source: SourceDescriptor
    envelope: SupportEnvelope
    engine: EngineIdentity
    transcript_kind: TranscriptKind
    transcript_language: str | None
    status: RunStatus
    status_reasons: tuple[str, ...] = ()
    gates: tuple[GateRecord, ...] = ()
    verifier_checks: tuple[VerifierRecord, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    manual_rescue: bool = False


@dataclass(frozen=True)
class ResearchPack:
    """Everything one run produced: canonical artifacts plus generated views."""

    run: RunRecord
    coverage: CoverageManifest
    ledger: ClaimLedger
    summary_markdown: str = ""
    report_html: str = ""

    @property
    def status(self) -> RunStatus:
        return self.run.status
