"""The port implementations that slice 1 ships."""

from __future__ import annotations

import json

import pytest

from video_research.adapters import (
    FixtureClaimExtractor,
    FixtureExtractionEngine,
    StructuralVerifier,
)
from video_research.claims import (
    AtomicClaim,
    ClaimLedger,
    ClaimRole,
    EvidenceRelation,
    ExternalReference,
)
from video_research.ports import (
    CheckOutcome,
    ClaimExtractor,
    ExtractionEngine,
    ExtractionError,
    IndependentVerifier,
)
from video_research.store import dumps, encode_coverage, encode_ledger
from video_research.timeline import (
    CoverageManifest,
    CoverageWindow,
    SpeechCoverage,
    TimeInterval,
    VisualObservation,
)

from .conftest import BENCHMARK


def test_the_adapters_satisfy_their_protocols():
    assert isinstance(FixtureExtractionEngine(BENCHMARK), ExtractionEngine)
    assert isinstance(FixtureClaimExtractor(BENCHMARK), ClaimExtractor)
    assert isinstance(StructuralVerifier(), IndependentVerifier)


def test_describe_is_cheap_enough_to_gate_on(tmp_path):
    """The envelope must be able to reject a source before extraction runs."""
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    payload["extraction_error"] = "this must not be reached"
    path = tmp_path / "f.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    engine = FixtureExtractionEngine(path)
    assert engine.describe("x").duration_ms == 600000
    with pytest.raises(ExtractionError):
        engine.extract("x")


def test_a_missing_fixture_raises_an_extraction_error(tmp_path):
    with pytest.raises(ExtractionError, match="fixture not found"):
        FixtureExtractionEngine(tmp_path / "absent.json").describe("x")


def test_a_malformed_fixture_raises_an_extraction_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExtractionError, match="not valid JSON"):
        FixtureExtractionEngine(path).describe("x")


@pytest.mark.parametrize(
    "damage",
    [
        lambda payload: payload["transcript"].update(kind="not-a-kind"),
        lambda payload: payload["windows"][0].pop("speech"),
        lambda payload: payload["windows"][0].update(end_ms=0),
        lambda payload: payload.update(source=None),
        lambda payload: payload["source"].update(duration_ms=None),
    ],
    ids=["invalid-enum", "missing-key", "invalid-interval", "null-source", "null-duration"],
)
def test_malformed_extraction_shapes_are_normalized_to_extraction_errors(
    damage, benchmark_payload, write_fixture
):
    damage(benchmark_payload)
    engine = FixtureExtractionEngine(write_fixture(benchmark_payload))

    with pytest.raises(ExtractionError, match="extraction output is malformed"):
        engine.describe("x")
        engine.extract("x")


def test_raw_engine_timestamps_survive_extraction():
    """A merged navigation timeline may never replace the exact source location."""
    source = FixtureExtractionEngine(BENCHMARK).extract("x")
    assert any(span.raw_timestamp == "00:08:50.120" for span in source.ocr_spans)


def write_draft(tmp_path, coverage, ledger):
    (tmp_path / "coverage.json").write_text(dumps(encode_coverage(coverage)), encoding="utf-8")
    (tmp_path / "claims.json").write_text(dumps(encode_ledger(ledger)), encoding="utf-8")
    return tmp_path


def test_the_verifier_passes_a_clean_pack(run_fixture, tmp_path):
    pack = run_fixture()
    report = StructuralVerifier().verify(write_draft(tmp_path, pack.coverage, pack.ledger))
    assert report.failing() == ()


def test_the_verifier_reads_from_disk_not_from_memory(run_fixture, tmp_path):
    """Damaging the written file must change the verdict."""
    pack = run_fixture()
    draft = write_draft(tmp_path, pack.coverage, pack.ledger)

    payload = json.loads((draft / "coverage.json").read_text(encoding="utf-8"))
    payload["coverage"]["windows"][1]["interval"]["start_ms"] = 200000
    (draft / "coverage.json").write_text(dumps(payload), encoding="utf-8")

    report = StructuralVerifier().verify(draft)
    failing = {c.name for c in report.failing()}
    assert "timeline_partitioned" in failing


def test_the_verifier_refuses_unreadable_artifacts(tmp_path):
    (tmp_path / "coverage.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "claims.json").write_text("{}", encoding="utf-8")

    report = StructuralVerifier().verify(tmp_path)
    assert [c.name for c in report.checks] == ["artifacts_readable"]
    assert report.checks[0].outcome is CheckOutcome.FAIL


def test_the_verifier_abstains_rather_than_passing_a_semantic_check(
    benchmark_payload, write_fixture, run_fixture, tmp_path
):
    """Without a declared oracle, entailment is unverified, never assumed good."""
    benchmark_payload["material_units"] = []
    for window in benchmark_payload["windows"]:
        window["material_unit_ids"] = []
    for claim in benchmark_payload["claims"]:
        claim["covers_units"] = []

    pack = run_fixture(write_fixture(benchmark_payload))
    report = StructuralVerifier().verify(write_draft(tmp_path, pack.coverage, pack.ledger))

    outcomes = {c.name: c.outcome for c in report.checks}
    assert outcomes["claim_entailment"] is CheckOutcome.UNVERIFIED
    assert outcomes["material_recall"] is CheckOutcome.UNVERIFIED
    assert CheckOutcome.PASS not in (outcomes["claim_entailment"], outcomes["material_recall"])


def test_the_verifier_rejects_external_only_material_claims(tmp_path):
    coverage = CoverageManifest(
        1000,
        (
            CoverageWindow(
                TimeInterval(0, 1000),
                SpeechCoverage.CAPTURED,
                VisualObservation.OBSERVED,
                "test",
            ),
        ),
    )
    ledger = ClaimLedger(
        (AtomicClaim("c1", "statement", ClaimRole.EXTERNAL_FACT, True),),
        (),
        (ExternalReference("c1", "https://example.com/doc", "doc", EvidenceRelation.SUPPORTS),),
    )
    report = StructuralVerifier().verify(write_draft(tmp_path, coverage, ledger))
    outcomes = {c.name: c.outcome for c in report.checks}
    assert outcomes["material_claims_supported"] is CheckOutcome.FAIL
