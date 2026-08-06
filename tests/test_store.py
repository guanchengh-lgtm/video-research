"""Canonical artifact storage: round trips, schema versioning, and refusal."""

from __future__ import annotations

import json

import pytest

from video_research.store import (
    CLAIMS_FILE,
    COVERAGE_FILE,
    RUN_FILE,
    SchemaError,
    decode_coverage,
    decode_ledger,
    decode_run,
    dumps,
    encode_coverage,
    encode_ledger,
    encode_run,
    read_pack,
)


def test_run_record_round_trips(run_fixture):
    pack = run_fixture()
    assert decode_run(encode_run(pack.run)) == pack.run


def test_coverage_round_trips(run_fixture):
    pack = run_fixture()
    assert decode_coverage(encode_coverage(pack.coverage)) == pack.coverage


def test_coverage_persists_the_material_unit_oracle(run_fixture):
    pack = run_fixture()
    payload = encode_coverage(pack.coverage)

    encoded_units = payload["coverage"]["material_units"]
    assert {unit["unit_id"] for unit in encoded_units} == pack.coverage.declared_unit_ids()
    assert decode_coverage(payload).material_units == pack.coverage.material_units


def test_legacy_coverage_schema_recovers_its_window_declared_units(run_fixture):
    pack = run_fixture()
    payload = encode_coverage(pack.coverage)
    payload["schema_version"] = "1.0.0"
    del payload["coverage"]["material_units"]

    decoded = decode_coverage(payload)

    expected = {unit_id for window in pack.coverage.windows for unit_id in window.material_unit_ids}
    assert decoded.declared_unit_ids() == expected


def test_ledger_round_trips_including_evidence_relations(run_fixture):
    pack = run_fixture()
    decoded = decode_ledger(encode_ledger(pack.ledger))
    assert decoded == pack.ledger
    assert {e.relation for e in decoded.evidence} == {e.relation for e in pack.ledger.evidence}


def test_serialization_is_byte_stable(run_fixture):
    pack = run_fixture()
    once = dumps(encode_ledger(pack.ledger))
    twice = dumps(encode_ledger(decode_ledger(json.loads(once))))
    assert once == twice


@pytest.mark.parametrize("filename", [RUN_FILE, COVERAGE_FILE, CLAIMS_FILE])
def test_an_unknown_schema_version_is_refused_rather_than_guessed(run_fixture, tmp_path,
                                                                  filename):
    out = tmp_path / "pack"
    run_fixture(out=out)
    payload = json.loads((out / filename).read_text(encoding="utf-8"))
    payload["schema_version"] = "99.0.0"
    (out / filename).write_text(dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaError, match=r"99\.0\.0"):
        read_pack(out)


def test_a_missing_canonical_artifact_is_refused(run_fixture, tmp_path):
    out = tmp_path / "pack"
    run_fixture(out=out)
    (out / CLAIMS_FILE).unlink()

    with pytest.raises(SchemaError, match=CLAIMS_FILE):
        read_pack(out)


def test_corrupt_canonical_data_is_refused(run_fixture, tmp_path):
    out = tmp_path / "pack"
    run_fixture(out=out)
    (out / COVERAGE_FILE).write_text("{not json", encoding="utf-8")

    with pytest.raises(SchemaError, match="not valid JSON"):
        read_pack(out)


def test_a_canonical_artifact_missing_required_fields_is_refused(run_fixture, tmp_path):
    out = tmp_path / "pack"
    run_fixture(out=out)
    payload = json.loads((out / RUN_FILE).read_text(encoding="utf-8"))
    del payload["run"]["source"]
    (out / RUN_FILE).write_text(dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaError, match="not a valid canonical run record"):
        read_pack(out)


def test_reading_a_pack_never_reconstructs_canonical_data_from_the_views(run_fixture, tmp_path):
    """Views are outputs. Deleting them must not change what the pack means."""
    out = tmp_path / "pack"
    pack = run_fixture(out=out)
    (out / "summary.md").unlink()
    (out / "report.html").unlink()

    reloaded = read_pack(out)
    assert reloaded.run == pack.run
    assert reloaded.ledger == pack.ledger
    assert reloaded.summary_markdown == ""
