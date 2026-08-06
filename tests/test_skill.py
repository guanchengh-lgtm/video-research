"""End-to-end tests at the public skill boundary.

These assert observable research-pack behaviour: artifacts, evidence, coverage,
status, and diagnostics. They do not reach into helpers, so the internals stay
free to change.
"""

from __future__ import annotations

import json
from pathlib import Path

from video_research import RunStatus
from video_research.adapters import (
    FixtureClaimExtractor,
    FixtureExtractionEngine,
    StructuralVerifier,
)
from video_research.skill import FIXTURE_ENVELOPE, research_video
from video_research.store import (
    CLAIMS_FILE,
    COVERAGE_FILE,
    REPORT_FILE,
    RUN_FILE,
    SCHEMA_VERSION,
    SUMMARY_FILE,
    read_pack,
)

from .conftest import BENCHMARK


def test_benchmark_fixture_reaches_trusted_complete(run_fixture):
    pack = run_fixture()
    assert pack.status is RunStatus.TRUSTED_COMPLETE, pack.run.status_reasons


def test_trusted_complete_run_has_no_open_gates(run_fixture):
    pack = run_fixture()
    assert [g.gate_id for g in pack.run.gates if g.outcome != "pass"] == []
    assert [c.name for c in pack.run.verifier_checks if c.outcome != "pass"] == []


def test_every_material_claim_carries_evidence(run_fixture):
    pack = run_fixture()
    material = pack.ledger.material_claims()
    assert material, "the benchmark fixture should establish material claims"
    for claim in material:
        assert pack.ledger.evidence_for(claim.claim_id), claim.claim_id


def test_coverage_accounts_for_the_whole_timeline(run_fixture):
    pack = run_fixture()
    assert pack.coverage.partition_defects() == ()
    assert pack.coverage.windows[0].interval.start_ms == 0
    assert pack.coverage.windows[-1].interval.end_ms == pack.coverage.duration_ms


def test_declared_material_units_all_appear(run_fixture, benchmark_payload):
    pack = run_fixture()
    declared = {u["unit_id"] for u in benchmark_payload["material_units"]}
    assert pack.coverage.declared_unit_ids() == declared
    assert declared <= pack.ledger.covered_unit_ids()


def test_g8_checks_views_by_rerendering_the_canonical_pack(run_fixture):
    pack = run_fixture()
    gate = next(gate for gate in pack.run.gates if gate.gate_id == "G8")

    assert gate.outcome == "pass"
    assert gate.detail == "summary.md and report.html reproduce from canonical artifacts"


def test_pack_is_written_to_disk_and_reads_back(run_fixture, tmp_path):
    out = tmp_path / "written"
    pack = run_fixture(out=out)

    for name in (RUN_FILE, COVERAGE_FILE, CLAIMS_FILE, SUMMARY_FILE, REPORT_FILE):
        assert (out / name).exists(), name

    reloaded = read_pack(out)
    assert reloaded.run.status is pack.status
    assert reloaded.run.run_id == pack.run.run_id
    assert reloaded.ledger.claims == pack.ledger.claims
    assert reloaded.coverage == pack.coverage


def test_canonical_artifacts_declare_their_schema_version(run_fixture, tmp_path):
    out = tmp_path / "written"
    run_fixture(out=out)
    for name in (RUN_FILE, COVERAGE_FILE, CLAIMS_FILE):
        payload = json.loads((out / name).read_text(encoding="utf-8"))
        assert payload["schema_version"] == SCHEMA_VERSION, name


def test_out_of_envelope_source_fails_without_extracting(benchmark_payload, write_fixture,
                                                         run_fixture):
    benchmark_payload["source"]["source_kind"] = "live_stream"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.FAILED
    assert any("live_stream" in reason for reason in pack.run.status_reasons)
    assert pack.ledger.claims == ()


def test_failed_run_produces_no_misleading_summary(benchmark_payload, write_fixture, run_fixture):
    benchmark_payload["extraction_error"] = "the source could not be downloaded"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.FAILED
    assert "Failed Run" in pack.summary_markdown
    assert "the source could not be downloaded" in pack.summary_markdown
    assert pack.ledger.material_claims() == ()


def test_malformed_extraction_output_becomes_a_failed_run(
    benchmark_payload, write_fixture, run_fixture
):
    benchmark_payload["transcript"]["kind"] = "invented_transcript_kind"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.FAILED
    assert any("malformed" in reason for reason in pack.run.status_reasons)


def test_a_source_declaring_no_material_units_cannot_be_trusted_complete(
    benchmark_payload, write_fixture, run_fixture
):
    """An arbitrary video has no oracle for material recall, so it stays partial."""
    benchmark_payload["material_units"] = []
    for window in benchmark_payload["windows"]:
        window["material_unit_ids"] = []
    for claim in benchmark_payload["claims"]:
        claim["covers_units"] = []

    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.PARTIAL
    assert any("material recall" in reason for reason in pack.run.status_reasons)


def test_partial_run_keeps_its_useful_findings(benchmark_payload, write_fixture, run_fixture):
    benchmark_payload["windows"][2]["visual"] = "unobserved"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.PARTIAL
    assert len(pack.ledger.material_claims()) == 3, "findings survive a partial run"
    assert any("unobserved" in reason for reason in pack.run.status_reasons)


def test_manual_rescue_forbids_trusted_completeness(run_fixture):
    pack = run_fixture(manual_rescue=True)
    assert pack.status is RunStatus.PARTIAL
    assert any("manual rescue" in reason for reason in pack.run.status_reasons)


def test_cold_rerun_is_a_distinct_run(tmp_path):
    def once(directory: Path, run_id: str | None):
        return research_video(
            str(BENCHMARK),
            engine=FixtureExtractionEngine(BENCHMARK),
            claim_extractor=FixtureClaimExtractor(BENCHMARK),
            verifier=StructuralVerifier(),
            envelope=FIXTURE_ENVELOPE,
            output_dir=directory,
            run_id=run_id,
        )

    first = once(tmp_path / "a", None)
    second = once(tmp_path / "b", None)

    assert first.run.run_id != second.run.run_id
    assert first.status is second.status
    assert first.ledger.claims == second.ledger.claims


def test_rerunning_with_pinned_provenance_is_byte_identical(tmp_path, run_fixture):
    first = run_fixture(out=tmp_path / "a")
    second = run_fixture(out=tmp_path / "b")

    for name in (RUN_FILE, COVERAGE_FILE, CLAIMS_FILE, SUMMARY_FILE, REPORT_FILE):
        assert (tmp_path / "a" / name).read_text("utf-8") == (
            tmp_path / "b" / name
        ).read_text("utf-8"), name
    assert first.summary_markdown == second.summary_markdown
