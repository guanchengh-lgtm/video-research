"""The deterministic gates G1-G9.

Every gate is a pure function over canonical data. Each returns a
:class:`GateResult` and, when it does not pass, the diagnostic that explains
why. Nothing here performs I/O or calls a model, so the whole set can be driven
exhaustively from fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .claims import ClaimLedger
from .diagnostics import Diagnostic, DiagnosticCode
from .run import SourceDescriptor, SupportEnvelope, Transcript, TranscriptKind
from .timeline import CoverageManifest, MaterialContentUnit, TimeInterval

#: Fraction of the timeline a transcript must reach before it is not truncated.
TRANSCRIPT_REACH_RATIO = 0.95


class GateOutcome(Enum):
    """A gate's verdict.

    ``UNVERIFIED`` means the gate could not be decided from the available data.
    It is deliberately distinct from ``PASS`` so that an undecidable gate can
    never be mistaken for a satisfied one.
    """

    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    name: str
    outcome: GateOutcome
    detail: str = ""
    diagnostic: Diagnostic | None = None


def _passed(gate_id: str, name: str, detail: str = "") -> GateResult:
    return GateResult(gate_id, name, GateOutcome.PASS, detail)


def _failed(gate_id: str, name: str, code: DiagnosticCode, detail: str,
            interval: TimeInterval | None = None) -> GateResult:
    return GateResult(
        gate_id, name, GateOutcome.FAIL, detail, Diagnostic(code, detail, interval)
    )


def gate_envelope(envelope: SupportEnvelope, descriptor: SourceDescriptor) -> GateResult:
    """G1: the source falls inside the declared support envelope."""
    reason = envelope.rejection_reason(descriptor)
    if reason is None:
        return _passed("G1", "support envelope", f"inside envelope {envelope.envelope_id!r}")
    return _failed("G1", "support envelope", DiagnosticCode.SOURCE_OUT_OF_ENVELOPE, reason)


def gate_transcript(transcript: Transcript, duration_ms: int,
                    expected_language: str | None) -> GateResult:
    """G2: a validated transcript, or a usable fallback, exists.

    Captions are candidate evidence, not a transcript. This checks language,
    monotonic non-overlapping timing, and that the record reaches the end of the
    source rather than stopping early.
    """
    name = "validated transcript"
    if transcript.kind is TranscriptKind.NONE or not transcript.segments:
        return _failed("G2", name, DiagnosticCode.NO_USABLE_TRANSCRIPT,
                       "no transcript segments were produced")

    if expected_language and transcript.language and transcript.language != expected_language:
        return _failed(
            "G2", name, DiagnosticCode.TRANSCRIPT_LANGUAGE_UNEXPECTED,
            f"transcript is {transcript.language!r}, source is {expected_language!r}",
        )

    for earlier, later in zip(transcript.segments, transcript.segments[1:], strict=False):
        if later.interval.start_ms < earlier.interval.end_ms:
            return _failed(
                "G2", name, DiagnosticCode.TRANSCRIPT_TIMING_NONMONOTONIC,
                f"segment at {later.interval.label()} starts before the previous one ends",
                later.interval,
            )

    reach = transcript.last_end_ms
    if duration_ms > 0 and reach < duration_ms * TRANSCRIPT_REACH_RATIO:
        return _failed(
            "G2", name, DiagnosticCode.TRANSCRIPT_TRUNCATED,
            f"transcript stops at {reach} ms of a {duration_ms} ms source",
            TimeInterval(reach, duration_ms) if reach < duration_ms else None,
        )

    return _passed("G2", name, f"{transcript.kind.value}, reaches {reach} ms")


def gate_timeline_partition(coverage: CoverageManifest) -> GateResult:
    """G3: the coverage windows tile the whole timeline with no gap or overlap."""
    defects = coverage.partition_defects()
    if not defects:
        return _passed("G3", "timeline partition", f"{len(coverage.windows)} contiguous windows")
    return _failed("G3", "timeline partition", DiagnosticCode.TIMELINE_NOT_PARTITIONED,
                   "; ".join(defects))


def gate_observation(coverage: CoverageManifest) -> GateResult:
    """G4: every window carries a real speech and visual observation state.

    A partitioned timeline is bookkeeping. This gate is what asks whether anyone
    actually looked, which is why an unobserved window blocks completeness even
    though the timeline accounting is perfect.
    """
    unobserved = coverage.unobserved_windows()
    if not unobserved:
        return _passed("G4", "window observation", f"{len(coverage.windows)} windows observed")
    first = unobserved[0]
    return _failed(
        "G4", "window observation", DiagnosticCode.WINDOW_UNOBSERVED,
        f"{len(unobserved)} window(s) unobserved, first at {first.interval.label()}",
        first.interval,
    )


def gate_evidence(ledger: ClaimLedger, coverage: CoverageManifest) -> GateResult:
    """G5: every material claim cites evidence that resolves inside the source."""
    name = "evidence support"
    timeline = coverage.timeline if coverage.duration_ms > 0 else None

    for claim in sorted(ledger.material_claims(), key=lambda c: c.claim_id):
        refs = ledger.evidence_for(claim.claim_id)
        externals = ledger.external_for(claim.claim_id)
        if not refs and not externals:
            return _failed("G5", name, DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED,
                           f"material claim {claim.claim_id!r} cites no evidence")

    if timeline is not None:
        for ref in ledger.evidence:
            if not ref.span.interval.within(timeline):
                return _failed(
                    "G5", name, DiagnosticCode.EVIDENCE_OUT_OF_RANGE,
                    f"evidence for {ref.claim_id!r} at {ref.span.interval.label()} "
                    f"falls outside the source",
                    ref.span.interval,
                )

    orphan = sorted({r.claim_id for r in ledger.evidence} - ledger.claim_ids())
    if orphan:
        return _failed("G5", name, DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED,
                       f"evidence cites unknown claim(s): {', '.join(orphan)}")

    return _passed("G5", name, f"{len(ledger.material_claims())} material claim(s) supported")


def gate_material_recall(ledger: ClaimLedger,
                         declared: tuple[MaterialContentUnit, ...]) -> GateResult:
    """G6: every declared material content unit is represented by a claim.

    A source that declares no units cannot be checked. That is the honest answer
    for an arbitrary video, and it is reported as ``UNVERIFIED`` rather than
    ``PASS`` so the run lands partial instead of falsely complete.
    """
    name = "material recall"
    if not declared:
        return GateResult(
            "G6", name, GateOutcome.UNVERIFIED,
            "source declares no benchmark material units, so recall cannot be checked",
        )
    covered = ledger.covered_unit_ids()
    missing = sorted(u.unit_id for u in declared if u.unit_id not in covered)
    if missing:
        return _failed("G6", name, DiagnosticCode.MATERIAL_UNIT_UNREPRESENTED,
                       f"unrepresented material unit(s): {', '.join(missing)}")
    return _passed("G6", name, f"{len(declared)} declared unit(s) represented")


def gate_schema(schema_valid: bool, detail: str = "") -> GateResult:
    """G7: the canonical artifacts validate against their versioned schema."""
    if schema_valid:
        return _passed("G7", "canonical schema", detail or "artifacts validate")
    return _failed("G7", "canonical schema", DiagnosticCode.CANONICAL_SCHEMA_INVALID,
                   detail or "canonical artifacts failed schema validation")


def gate_view_derivation(views_match: bool, detail: str = "") -> GateResult:
    """G8: the human views regenerate exactly from the canonical artifacts."""
    if views_match:
        return _passed("G8", "view derivation", detail or "views regenerate from canonical data")
    return _failed("G8", "view derivation", DiagnosticCode.CANONICAL_SCHEMA_INVALID,
                   detail or "generated views drifted from the canonical artifacts")


def gate_unattended(manual_rescue: bool) -> GateResult:
    """G9: the run reached its result without a human editing the evidence."""
    if not manual_rescue:
        return _passed("G9", "unattended", "no manual rescue")
    return _failed("G9", "unattended", DiagnosticCode.MANUAL_RESCUE_USED,
                   "a manual rescue was required")


def collect_diagnostics(results: tuple[GateResult, ...]) -> tuple[Diagnostic, ...]:
    """Every diagnostic the given gate results raised, in gate order."""
    return tuple(r.diagnostic for r in results if r.diagnostic is not None)
