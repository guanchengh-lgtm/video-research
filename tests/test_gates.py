"""Each gate, driven directly."""

from __future__ import annotations

import pytest

from video_research.claims import (
    AtomicClaim,
    ClaimLedger,
    ClaimRole,
    EvidenceReference,
    EvidenceRelation,
    ExternalReference,
)
from video_research.diagnostics import DiagnosticCode, Severity
from video_research.gates import (
    GateOutcome,
    collect_diagnostics,
    gate_envelope,
    gate_evidence,
    gate_material_recall,
    gate_observation,
    gate_schema,
    gate_timeline_partition,
    gate_transcript,
    gate_unattended,
    gate_view_derivation,
)
from video_research.run import (
    SourceDescriptor,
    SupportEnvelope,
    Transcript,
    TranscriptKind,
    TranscriptSegment,
)
from video_research.timeline import (
    CoverageManifest,
    CoverageWindow,
    MaterialContentUnit,
    SourceSpan,
    SpanKind,
    SpeechCoverage,
    TimeInterval,
    VisualObservation,
)

ENVELOPE = SupportEnvelope(
    envelope_id="test",
    admitted_source_kinds=frozenset({"fixture"}),
    max_duration_ms=600000,
    admitted_languages=frozenset({"en"}),
)


def descriptor(**overrides) -> SourceDescriptor:
    base = {
        "source_ref": "fixture://x",
        "source_kind": "fixture",
        "duration_ms": 60000,
        "language": "en",
    }
    return SourceDescriptor(**{**base, **overrides})


def window(
    start: int,
    end: int,
    *,
    speech=SpeechCoverage.CAPTURED,
    visual=VisualObservation.OBSERVED,
    units=(),
) -> CoverageWindow:
    return CoverageWindow(TimeInterval(start, end), speech, visual, "test", tuple(units))


def transcript(
    *segments: tuple[int, int], kind=TranscriptKind.NATIVE_CAPTIONS, language="en"
) -> Transcript:
    return Transcript(
        kind=kind,
        language=language,
        segments=tuple(TranscriptSegment(TimeInterval(a, b), "text") for a, b in segments),
    )


# --- G1 support envelope --------------------------------------------------- #


def test_g1_admits_a_source_inside_the_envelope():
    assert gate_envelope(ENVELOPE, descriptor()).outcome is GateOutcome.PASS


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"source_kind": "live_stream"}, "not admitted"),
        ({"duration_ms": 0}, "duration is unknown"),
        ({"duration_ms": 900000}, "beyond the"),
        ({"language": "de"}, "not admitted"),
        ({"language": None}, "language is unknown"),
    ],
)
def test_g1_rejects_sources_outside_the_envelope(overrides, expected):
    result = gate_envelope(ENVELOPE, descriptor(**overrides))
    assert result.outcome is GateOutcome.FAIL
    assert expected in result.detail
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.SOURCE_OUT_OF_ENVELOPE


# --- G2 transcript --------------------------------------------------------- #


def test_g2_accepts_a_transcript_reaching_the_end():
    assert gate_transcript(transcript((0, 30000), (30000, 59000)), 60000, "en").outcome is (
        GateOutcome.PASS
    )


def test_g2_accepts_an_asr_fallback():
    result = gate_transcript(transcript((0, 59000), kind=TranscriptKind.ASR_FALLBACK), 60000, "en")
    assert result.outcome is GateOutcome.PASS
    assert "asr_fallback" in result.detail


@pytest.mark.parametrize(
    "value,code",
    [
        (transcript(kind=TranscriptKind.NONE), DiagnosticCode.NO_USABLE_TRANSCRIPT),
        (transcript((0, 20000)), DiagnosticCode.TRANSCRIPT_TRUNCATED),
        (transcript((0, 59000), language="de"), DiagnosticCode.TRANSCRIPT_LANGUAGE_UNEXPECTED),
        (
            transcript((0, 30000), (20000, 59000)),
            DiagnosticCode.TRANSCRIPT_TIMING_NONMONOTONIC,
        ),
    ],
)
def test_g2_rejects_an_untrustworthy_transcript(value, code):
    result = gate_transcript(value, 60000, "en")
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is code


# --- G3 timeline partition ------------------------------------------------- #


def test_g3_accepts_an_exact_partition():
    coverage = CoverageManifest(60000, (window(0, 30000), window(30000, 60000)))
    assert gate_timeline_partition(coverage).outcome is GateOutcome.PASS


@pytest.mark.parametrize(
    "windows,expected",
    [
        ((window(0, 20000), window(30000, 60000)), "gap"),
        ((window(0, 40000), window(30000, 60000)), "overlap"),
        ((window(0, 30000), window(30000, 50000)), "tail uncovered"),
        ((window(10000, 60000),), "starts uncovered"),
        ((window(0, 30000), window(30000, 70000)), "runs past the source end"),
        ((), "no coverage windows"),
    ],
)
def test_g3_names_the_interval_it_could_not_account_for(windows, expected):
    result = gate_timeline_partition(CoverageManifest(60000, windows))
    assert result.outcome is GateOutcome.FAIL
    assert expected in result.detail
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.TIMELINE_NOT_PARTITIONED


def test_g3_notices_windows_out_of_order():
    coverage = CoverageManifest(60000, (window(30000, 60000), window(0, 30000)))
    assert "not in timeline order" in gate_timeline_partition(coverage).detail


# --- G4 observation -------------------------------------------------------- #


def test_g4_treats_confirmed_silence_and_static_screen_as_real_observations():
    coverage = CoverageManifest(
        60000,
        (
            window(
                0,
                60000,
                speech=SpeechCoverage.SILENCE_CONFIRMED,
                visual=VisualObservation.STATIC_CONFIRMED,
            ),
        ),
    )
    assert gate_observation(coverage).outcome is GateOutcome.PASS


@pytest.mark.parametrize(
    "kwargs",
    [{"speech": SpeechCoverage.UNOBSERVED}, {"visual": VisualObservation.UNOBSERVED}],
)
def test_g4_rejects_a_window_nobody_looked_at(kwargs):
    coverage = CoverageManifest(60000, (window(0, 60000, **kwargs),))
    result = gate_observation(coverage)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.WINDOW_UNOBSERVED


# --- G5 evidence ----------------------------------------------------------- #


def claim(claim_id: str, *, material: bool = True, units=()) -> AtomicClaim:
    return AtomicClaim(claim_id, "statement", ClaimRole.SOURCE_ASSERTION, material, tuple(units))


def evidence(claim_id: str, start: int, end: int) -> EvidenceReference:
    return EvidenceReference(
        claim_id, SourceSpan(SpanKind.SPEECH, TimeInterval(start, end)), EvidenceRelation.SUPPORTS
    )


COVERAGE = CoverageManifest(60000, (window(0, 60000),))


def test_g5_accepts_supported_material_claims():
    ledger = ClaimLedger((claim("c1"),), (evidence("c1", 0, 1000),))
    assert gate_evidence(ledger, COVERAGE).outcome is GateOutcome.PASS


def test_g5_ignores_immaterial_claims_without_evidence():
    ledger = ClaimLedger((claim("c1", material=False),), ())
    assert gate_evidence(ledger, COVERAGE).outcome is GateOutcome.PASS


def test_g5_rejects_a_material_claim_with_no_evidence():
    result = gate_evidence(ClaimLedger((claim("c1"),), ()), COVERAGE)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED


def test_g5_rejects_external_refs_as_a_substitute_for_source_evidence():
    ledger = ClaimLedger(
        (claim("c1"),),
        (),
        (ExternalReference("c1", "https://example.com/doc", "doc", EvidenceRelation.SUPPORTS),),
    )
    result = gate_evidence(ledger, COVERAGE)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED


def test_g5_rejects_evidence_pointing_outside_the_source():
    ledger = ClaimLedger((claim("c1"),), (evidence("c1", 59000, 90000),))
    result = gate_evidence(ledger, COVERAGE)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.EVIDENCE_OUT_OF_RANGE


def test_g5_rejects_evidence_citing_a_claim_that_does_not_exist():
    ledger = ClaimLedger((claim("c1"),), (evidence("c1", 0, 1000), evidence("ghost", 0, 1000)))
    result = gate_evidence(ledger, COVERAGE)
    assert result.outcome is GateOutcome.FAIL
    assert "ghost" in result.detail


# --- G6 material recall ---------------------------------------------------- #


def unit(unit_id: str) -> MaterialContentUnit:
    return MaterialContentUnit(unit_id, "description", TimeInterval(0, 1000))


def test_g6_passes_when_every_declared_unit_is_represented():
    ledger = ClaimLedger((claim("c1", units=("u1",)),))
    coverage = CoverageManifest(1000, (window(0, 1000, units=("u1",)),), (unit("u1"),))
    assert gate_material_recall(ledger, coverage).outcome is GateOutcome.PASS


def test_g6_fails_when_a_declared_unit_has_no_claim():
    coverage = CoverageManifest(1000, (window(0, 1000, units=("u1",)),), (unit("u1"),))
    result = gate_material_recall(ClaimLedger((claim("c1"),)), coverage)
    assert result.outcome is GateOutcome.FAIL
    assert "u1" in result.detail
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.MATERIAL_UNIT_UNREPRESENTED


def test_g6_ignores_coverage_from_non_material_claims():
    ledger = ClaimLedger((claim("c1", material=False, units=("u1",)),))
    coverage = CoverageManifest(1000, (window(0, 1000, units=("u1",)),), (unit("u1"),))
    result = gate_material_recall(ledger, coverage)
    assert result.outcome is GateOutcome.FAIL
    assert "u1" in result.detail
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.MATERIAL_UNIT_UNREPRESENTED


def test_g6_is_unverified_without_an_oracle_rather_than_passing():
    result = gate_material_recall(ClaimLedger((claim("c1"),)), CoverageManifest(1000))
    assert result.outcome is GateOutcome.UNVERIFIED
    assert result.diagnostic is None, "an undecidable gate raises no diagnostic, it just abstains"


# --- G7, G8, G9 ------------------------------------------------------------ #


def test_g7_fails_on_invalid_canonical_artifacts():
    result = gate_schema(False, "coverage.json will not decode")
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.CANONICAL_SCHEMA_INVALID


def test_g8_fails_when_views_drift_from_canonical_data():
    result = gate_view_derivation(False)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.VIEW_DERIVATION_FAILED
    assert result.diagnostic.severity is Severity.COMPLETENESS_BLOCKER


def test_g9_fails_when_a_human_had_to_step_in():
    result = gate_unattended(True)
    assert result.outcome is GateOutcome.FAIL
    assert result.diagnostic is not None
    assert result.diagnostic.code is DiagnosticCode.MANUAL_RESCUE_USED


def test_collect_diagnostics_returns_only_what_failed():
    results = (
        gate_unattended(False),
        gate_unattended(True),
        gate_material_recall(ClaimLedger(), CoverageManifest(1000)),
    )
    collected = collect_diagnostics(results)
    assert [d.code for d in collected] == [DiagnosticCode.MANUAL_RESCUE_USED]
