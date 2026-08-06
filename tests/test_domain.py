"""Domain invariants: severities, intervals, and the coverage partition."""

from __future__ import annotations

import pytest

from video_research.diagnostics import SEVERITY, Diagnostic, DiagnosticCode, Severity
from video_research.timeline import (
    CoverageManifest,
    CoverageWindow,
    SpeechCoverage,
    TimeInterval,
    VisualObservation,
)


def test_every_diagnostic_code_has_a_fixed_severity():
    """A code without a severity would crash at the moment it mattered most."""
    missing = sorted(c.value for c in DiagnosticCode if c not in SEVERITY)
    assert missing == []


def test_severity_is_looked_up_not_chosen():
    assert Diagnostic(DiagnosticCode.WINDOW_UNOBSERVED, "x").severity is (
        Severity.COMPLETENESS_BLOCKER
    )
    assert Diagnostic(DiagnosticCode.EXTRACTION_FAILED, "x").severity is Severity.FATAL
    assert Diagnostic(DiagnosticCode.DUPLICATE_EVIDENCE, "x").severity is Severity.INFORMATIONAL


def test_no_completeness_blocker_is_classified_as_a_warning():
    """The whole project fails if a blocker can be demoted to informational."""
    blocker_shaped = {
        DiagnosticCode.TRANSCRIPT_TRUNCATED,
        DiagnosticCode.WINDOW_UNOBSERVED,
        DiagnosticCode.MATERIAL_CLAIM_UNSUPPORTED,
        DiagnosticCode.MATERIAL_UNIT_UNREPRESENTED,
        DiagnosticCode.MANUAL_RESCUE_USED,
        DiagnosticCode.VERIFIER_DISAGREEMENT,
        DiagnosticCode.OUTPUT_TRUNCATED,
        DiagnosticCode.VIEW_DERIVATION_FAILED,
    }
    for code in blocker_shaped:
        assert SEVERITY[code] is not Severity.INFORMATIONAL, code


@pytest.mark.parametrize("start,end", [(-1, 10), (10, 10), (10, 5)])
def test_an_impossible_interval_is_rejected_at_construction(start, end):
    with pytest.raises(ValueError):
        TimeInterval(start, end)


def test_interval_membership_is_half_open():
    interval = TimeInterval(1000, 2000)
    assert interval.contains(1000)
    assert not interval.contains(2000)
    assert interval.duration_ms == 1000


def test_interval_labels_are_minutes_and_seconds():
    assert TimeInterval(90000, 125000).label() == "01:30-02:05"


def test_adjacent_windows_are_a_partition_not_an_overlap():
    """Half-open intervals mean window ends and the next start share a number."""
    coverage = CoverageManifest(
        2000,
        (
            CoverageWindow(
                TimeInterval(0, 1000), SpeechCoverage.CAPTURED, VisualObservation.OBSERVED, "test"
            ),
            CoverageWindow(
                TimeInterval(1000, 2000),
                SpeechCoverage.CAPTURED,
                VisualObservation.OBSERVED,
                "test",
            ),
        ),
    )
    assert coverage.partition_defects() == ()


def test_millisecond_timelines_do_not_invent_gaps():
    """Integer arithmetic: a thousand one-millisecond windows tile exactly."""
    windows = tuple(
        CoverageWindow(
            TimeInterval(i, i + 1), SpeechCoverage.CAPTURED, VisualObservation.OBSERVED, "test"
        )
        for i in range(1000)
    )
    assert CoverageManifest(1000, windows).partition_defects() == ()


def test_a_zero_length_source_cannot_be_partitioned():
    assert CoverageManifest(0, ()).partition_defects() == ("source duration is not positive",)
