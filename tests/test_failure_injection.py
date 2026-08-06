"""Failure injection through the public entry point.

Each case damages a copy of the golden benchmark fixture in one specific way and
asserts the run degrades. The suite-level property is the one that matters: no
injected material failure may produce a trusted-complete run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from video_research.run import RunStatus

Damage = Callable[[dict[str, Any]], None]


def truncated_captions(payload: dict[str, Any]) -> None:
    """Captions stop two thirds of the way through a ten-minute source."""
    payload["transcript"]["segments"] = payload["transcript"]["segments"][:4]


def wrong_language_captions(payload: dict[str, Any]) -> None:
    payload["transcript"]["language"] = "de"


def timestamp_drift(payload: dict[str, Any]) -> None:
    """A later caption starts before the previous one ended."""
    payload["transcript"]["segments"][5]["start_ms"] = 180000


def no_transcript_and_no_fallback(payload: dict[str, Any]) -> None:
    payload["transcript"] = {"kind": "none", "language": None, "segments": []}
    payload["fallback_available"] = False


def missing_final_window(payload: dict[str, Any]) -> None:
    """Material content near the end, and nothing accounting for that interval."""
    payload["windows"] = payload["windows"][:-1]


def gap_in_the_middle(payload: dict[str, Any]) -> None:
    payload["windows"][1]["end_ms"] = 250000


def overlapping_windows(payload: dict[str, Any]) -> None:
    payload["windows"][2]["start_ms"] = 250000


def unobserved_window(payload: dict[str, Any]) -> None:
    """The timeline is accounted for, but nobody actually looked at one stretch."""
    payload["windows"][2]["visual"] = "unobserved"


def sparse_visual_coverage(payload: dict[str, Any]) -> None:
    payload["windows"][0]["speech"] = "unobserved"


def material_claim_without_evidence(payload: dict[str, Any]) -> None:
    payload["claims"][0]["evidence"] = []


def evidence_outside_the_source(payload: dict[str, Any]) -> None:
    payload["claims"][2]["evidence"][0]["end_ms"] = 900000


def unrepresented_material_unit(payload: dict[str, Any]) -> None:
    """The engine saw a correction; no claim carries it."""
    payload["claims"][1]["covers_units"] = []


def claim_citing_an_undeclared_unit(payload: dict[str, Any]) -> None:
    payload["claims"][0]["covers_units"] = ["u-does-not-exist"]


def unsupported_source(payload: dict[str, Any]) -> None:
    payload["source"]["source_kind"] = "private_video"


def extraction_failure(payload: dict[str, Any]) -> None:
    payload["extraction_error"] = "captions and audio were both unavailable"


def unknown_duration(payload: dict[str, Any]) -> None:
    payload["source"]["duration_ms"] = 0


#: Damage that leaves useful research behind: the run must degrade to partial.
DEGRADING: dict[str, Damage] = {
    "truncated_captions": truncated_captions,
    "wrong_language_captions": wrong_language_captions,
    "timestamp_drift": timestamp_drift,
    "missing_final_window": missing_final_window,
    "gap_in_the_middle": gap_in_the_middle,
    "overlapping_windows": overlapping_windows,
    "unobserved_window": unobserved_window,
    "sparse_visual_coverage": sparse_visual_coverage,
    "material_claim_without_evidence": material_claim_without_evidence,
    "evidence_outside_the_source": evidence_outside_the_source,
    "unrepresented_material_unit": unrepresented_material_unit,
    "claim_citing_an_undeclared_unit": claim_citing_an_undeclared_unit,
}

#: Damage that removes the basis for any research at all.
FATAL: dict[str, Damage] = {
    "no_transcript_and_no_fallback": no_transcript_and_no_fallback,
    "unsupported_source": unsupported_source,
    "extraction_failure": extraction_failure,
    "unknown_duration": unknown_duration,
}

ALL_DAMAGE: dict[str, Damage] = {**DEGRADING, **FATAL}


@pytest.mark.parametrize("name", sorted(ALL_DAMAGE))
def test_injected_failure_never_produces_a_trusted_complete_run(
    name, benchmark_payload, write_fixture, run_fixture
):
    ALL_DAMAGE[name](benchmark_payload)
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is not RunStatus.TRUSTED_COMPLETE, (
        f"{name} produced false completeness"
    )
    assert pack.run.status_reasons, f"{name} degraded the run without saying why"


@pytest.mark.parametrize("name", sorted(DEGRADING))
def test_recoverable_damage_yields_a_partial_run_with_findings(
    name, benchmark_payload, write_fixture, run_fixture
):
    DEGRADING[name](benchmark_payload)
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.PARTIAL
    assert "Partial Run" in pack.summary_markdown
    assert "Completeness blockers" in pack.summary_markdown


@pytest.mark.parametrize("name", sorted(FATAL))
def test_unrecoverable_damage_yields_a_failed_run(
    name, benchmark_payload, write_fixture, run_fixture
):
    FATAL[name](benchmark_payload)
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.FAILED
    assert "Failed Run" in pack.summary_markdown


def test_the_undamaged_benchmark_still_passes(run_fixture):
    """The guard on the suite: if the fixture stopped passing, every injection
    test above would trivially 'succeed' while proving nothing."""
    assert run_fixture().status is RunStatus.TRUSTED_COMPLETE


def test_duplicate_evidence_is_harmless(benchmark_payload, write_fixture, run_fixture):
    """A diagnostic proven harmless to every trust gate may stay a warning."""
    payload = benchmark_payload
    payload["diagnostics"] = [
        {"code": "duplicate_evidence", "detail": "the same span is cited twice"}
    ]
    pack = run_fixture(write_fixture(payload))

    assert pack.status is RunStatus.TRUSTED_COMPLETE
    assert any(d.code.value == "duplicate_evidence" for d in pack.run.diagnostics)
