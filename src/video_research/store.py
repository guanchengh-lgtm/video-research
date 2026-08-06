"""Canonical artifact storage.

Canonical artifacts are the source of truth; ``summary.md`` and ``report.html``
are generated views of them (ADR 0001). Every canonical file carries a
``schema_version`` and is rejected on read if that version is unknown, so an
artifact from a future release fails loudly instead of being half-understood.

JSON is written with sorted keys and a fixed indent so that re-serializing
unchanged data is byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .claims import (
    AtomicClaim,
    ClaimLedger,
    ClaimRole,
    EvidenceReference,
    EvidenceRelation,
    ExternalReference,
)
from .diagnostics import Diagnostic, DiagnosticCode
from .run import (
    EngineIdentity,
    GateRecord,
    ResearchPack,
    RunRecord,
    RunStatus,
    SourceDescriptor,
    SupportEnvelope,
    TranscriptKind,
    VerifierRecord,
)
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

SCHEMA_VERSION = "1.1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0.0", SCHEMA_VERSION})

RUN_FILE = "run.json"
COVERAGE_FILE = "coverage.json"
CLAIMS_FILE = "claims.json"
SUMMARY_FILE = "summary.md"
REPORT_FILE = "report.html"


class SchemaError(ValueError):
    """Raised when a canonical artifact cannot be trusted to mean what it says."""


# --------------------------------------------------------------------------- #
# encoding
# --------------------------------------------------------------------------- #


def _interval(value: TimeInterval) -> dict[str, Any]:
    return {"start_ms": value.start_ms, "end_ms": value.end_ms}


def _span(value: SourceSpan) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "interval": _interval(value.interval),
        "artifact_id": value.artifact_id,
        "artifact_digest": value.artifact_digest,
        "raw_timestamp": value.raw_timestamp,
    }


def _diagnostic(value: Diagnostic) -> dict[str, Any]:
    return {
        "code": value.code.value,
        "severity": value.severity.value,
        "detail": value.detail,
        "interval": _interval(value.interval) if value.interval else None,
    }


def encode_run(record: RunRecord) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": record.run_id,
            "created_at": record.created_at,
            "status": record.status.value,
            "status_reasons": list(record.status_reasons),
            "manual_rescue": record.manual_rescue,
            "source": {
                "source_ref": record.source.source_ref,
                "source_kind": record.source.source_kind,
                "duration_ms": record.source.duration_ms,
                "language": record.source.language,
                "title": record.source.title,
                "digest": record.source.digest,
            },
            "envelope": {
                "envelope_id": record.envelope.envelope_id,
                "admitted_source_kinds": sorted(record.envelope.admitted_source_kinds),
                "max_duration_ms": record.envelope.max_duration_ms,
                "admitted_languages": (
                    sorted(record.envelope.admitted_languages)
                    if record.envelope.admitted_languages is not None
                    else None
                ),
                "requires_known_duration": record.envelope.requires_known_duration,
            },
            "engine": {
                "name": record.engine.name,
                "version": record.engine.version,
                "outbound_data": record.engine.outbound_data,
            },
            "transcript": {
                "kind": record.transcript_kind.value,
                "language": record.transcript_language,
            },
            "gates": [
                {"gate_id": g.gate_id, "name": g.name, "outcome": g.outcome, "detail": g.detail}
                for g in record.gates
            ],
            "verifier_checks": [
                {"name": c.name, "outcome": c.outcome, "detail": c.detail}
                for c in record.verifier_checks
            ],
            "diagnostics": [_diagnostic(d) for d in record.diagnostics],
        },
    }


def encode_coverage(coverage: CoverageManifest) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "coverage": {
            "duration_ms": coverage.duration_ms,
            "material_units": [
                {
                    "unit_id": unit.unit_id,
                    "description": unit.description,
                    "interval": _interval(unit.interval),
                }
                for unit in coverage.material_units
            ],
            "windows": [
                {
                    "interval": _interval(w.interval),
                    "speech": w.speech.value,
                    "visual": w.visual.value,
                    "extraction_method": w.extraction_method,
                    "material_unit_ids": list(w.material_unit_ids),
                }
                for w in coverage.windows
            ],
        },
    }


def encode_ledger(ledger: ClaimLedger) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ledger": {
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "statement": c.statement,
                    "role": c.role.value,
                    "material": c.material,
                    "covers_units": list(c.covers_units),
                    "speaker_label": c.speaker_label,
                }
                for c in ledger.claims
            ],
            "evidence": [
                {
                    "claim_id": e.claim_id,
                    "span": _span(e.span),
                    "relation": e.relation.value,
                    "note": e.note,
                }
                for e in ledger.evidence
            ],
            "external": [
                {
                    "claim_id": e.claim_id,
                    "url": e.url,
                    "title": e.title,
                    "relation": e.relation.value,
                }
                for e in ledger.external
            ],
        },
    }


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #


def _require_version(payload: dict[str, Any], filename: str) -> str:
    version = payload.get("schema_version")
    if not isinstance(version, str) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaError(
            f"{filename} declares schema_version {version!r}; "
            f"this build understands {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    return version


def _decode_interval(payload: dict[str, Any] | None) -> TimeInterval | None:
    if payload is None:
        return None
    return TimeInterval(int(payload["start_ms"]), int(payload["end_ms"]))


def _decode_span(payload: dict[str, Any]) -> SourceSpan:
    interval = _decode_interval(payload["interval"])
    assert interval is not None
    return SourceSpan(
        kind=SpanKind(payload["kind"]),
        interval=interval,
        artifact_id=payload.get("artifact_id"),
        artifact_digest=payload.get("artifact_digest"),
        raw_timestamp=payload.get("raw_timestamp"),
    )


def decode_run(payload: dict[str, Any]) -> RunRecord:
    _require_version(payload, RUN_FILE)
    try:
        body = payload["run"]
        source = body["source"]
        envelope = body["envelope"]
        engine = body["engine"]
        languages = envelope["admitted_languages"]
        return RunRecord(
            run_id=body["run_id"],
            created_at=body["created_at"],
            source=SourceDescriptor(
                source_ref=source["source_ref"],
                source_kind=source["source_kind"],
                duration_ms=int(source["duration_ms"]),
                language=source.get("language"),
                title=source.get("title", ""),
                digest=source.get("digest"),
            ),
            envelope=SupportEnvelope(
                envelope_id=envelope["envelope_id"],
                admitted_source_kinds=frozenset(envelope["admitted_source_kinds"]),
                max_duration_ms=envelope["max_duration_ms"],
                admitted_languages=frozenset(languages) if languages is not None else None,
                requires_known_duration=envelope["requires_known_duration"],
            ),
            engine=EngineIdentity(
                name=engine["name"],
                version=engine["version"],
                outbound_data=engine.get("outbound_data", "none"),
            ),
            transcript_kind=TranscriptKind(body["transcript"]["kind"]),
            transcript_language=body["transcript"].get("language"),
            status=RunStatus(body["status"]),
            status_reasons=tuple(body.get("status_reasons", ())),
            gates=tuple(
                GateRecord(g["gate_id"], g["name"], g["outcome"], g["detail"])
                for g in body.get("gates", ())
            ),
            verifier_checks=tuple(
                VerifierRecord(c["name"], c["outcome"], c["detail"])
                for c in body.get("verifier_checks", ())
            ),
            diagnostics=tuple(
                Diagnostic(
                    code=DiagnosticCode(d["code"]),
                    detail=d["detail"],
                    interval=_decode_interval(d.get("interval")),
                )
                for d in body.get("diagnostics", ())
            ),
            manual_rescue=bool(body.get("manual_rescue", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaError(f"{RUN_FILE} is not a valid canonical run record: {exc}") from exc


def decode_coverage(payload: dict[str, Any]) -> CoverageManifest:
    version = _require_version(payload, COVERAGE_FILE)
    try:
        body = payload["coverage"]
        windows = []
        for w in body.get("windows", ()):
            interval = _decode_interval(w["interval"])
            assert interval is not None
            windows.append(
                CoverageWindow(
                    interval=interval,
                    speech=SpeechCoverage(w["speech"]),
                    visual=VisualObservation(w["visual"]),
                    extraction_method=w["extraction_method"],
                    material_unit_ids=tuple(w.get("material_unit_ids", ())),
                )
            )
        if version == "1.0.0":
            material_units = _legacy_material_units(tuple(windows))
        else:
            material_units = tuple(
                MaterialContentUnit(
                    unit_id=unit["unit_id"],
                    description=unit.get("description", ""),
                    interval=_required_interval(unit["interval"]),
                )
                for unit in body["material_units"]
            )
        return CoverageManifest(
            duration_ms=int(body["duration_ms"]),
            windows=tuple(windows),
            material_units=material_units,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaError(f"{COVERAGE_FILE} is not a valid coverage manifest: {exc}") from exc


def _required_interval(payload: dict[str, Any]) -> TimeInterval:
    interval = _decode_interval(payload)
    assert interval is not None
    return interval


def _legacy_material_units(
    windows: tuple[CoverageWindow, ...],
) -> tuple[MaterialContentUnit, ...]:
    """Read the 1.0 window-id oracle while preserving its declared meaning.

    Version 1.0 did not persist descriptions or exact unit intervals. The first
    window carrying each id is the only recoverable location, so legacy reads
    retain that conservative location and all new writes use the 1.1 shape.
    """
    units: dict[str, MaterialContentUnit] = {}
    for window in windows:
        for unit_id in window.material_unit_ids:
            units.setdefault(unit_id, MaterialContentUnit(unit_id, "", window.interval))
    return tuple(units.values())


def decode_ledger(payload: dict[str, Any]) -> ClaimLedger:
    _require_version(payload, CLAIMS_FILE)
    try:
        body = payload["ledger"]
        return ClaimLedger(
            claims=tuple(
                AtomicClaim(
                    claim_id=c["claim_id"],
                    statement=c["statement"],
                    role=ClaimRole(c["role"]),
                    material=bool(c["material"]),
                    covers_units=tuple(c.get("covers_units", ())),
                    speaker_label=c.get("speaker_label"),
                )
                for c in body.get("claims", ())
            ),
            evidence=tuple(
                EvidenceReference(
                    claim_id=e["claim_id"],
                    span=_decode_span(e["span"]),
                    relation=EvidenceRelation(e["relation"]),
                    note=e.get("note", ""),
                )
                for e in body.get("evidence", ())
            ),
            external=tuple(
                ExternalReference(
                    claim_id=e["claim_id"],
                    url=e["url"],
                    title=e["title"],
                    relation=EvidenceRelation(e["relation"]),
                )
                for e in body.get("external", ())
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaError(f"{CLAIMS_FILE} is not a valid claim ledger: {exc}") from exc


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #


def dumps(payload: dict[str, Any]) -> str:
    """Serialize canonical data deterministically."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_pack(pack_dir: Path, pack: ResearchPack) -> None:
    """Write canonical artifacts and generated views into ``pack_dir``."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / RUN_FILE).write_text(dumps(encode_run(pack.run)), encoding="utf-8")
    (pack_dir / COVERAGE_FILE).write_text(dumps(encode_coverage(pack.coverage)), encoding="utf-8")
    (pack_dir / CLAIMS_FILE).write_text(dumps(encode_ledger(pack.ledger)), encoding="utf-8")
    if pack.summary_markdown:
        (pack_dir / SUMMARY_FILE).write_text(pack.summary_markdown, encoding="utf-8")
    if pack.report_html:
        (pack_dir / REPORT_FILE).write_text(pack.report_html, encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SchemaError(f"missing canonical artifact: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SchemaError(f"{path.name} is not a canonical artifact object")
    return payload


def read_pack(pack_dir: Path) -> ResearchPack:
    """Read a research pack back from its canonical artifacts.

    Views are read from disk when present but never used to reconstruct
    canonical data; they are outputs, not inputs.
    """
    run = decode_run(_load(pack_dir / RUN_FILE))
    coverage = decode_coverage(_load(pack_dir / COVERAGE_FILE))
    ledger = decode_ledger(_load(pack_dir / CLAIMS_FILE))
    summary_path = pack_dir / SUMMARY_FILE
    report_path = pack_dir / REPORT_FILE
    return ResearchPack(
        run=run,
        coverage=coverage,
        ledger=ledger,
        summary_markdown=summary_path.read_text(encoding="utf-8") if summary_path.exists() else "",
        report_html=report_path.read_text(encoding="utf-8") if report_path.exists() else "",
    )
