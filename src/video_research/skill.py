"""The public boundary: one invocation produces one research pack.

This is the seam tests use, because it is the seam a user uses. Everything
below it can be refactored freely; the observable contract is the research
pack's artifacts, evidence, coverage, diagnostics, and status.

Pipeline, in order:

    describe → G1 envelope → extract → G2 transcript → coverage windows
    → claims → G3..G7, G9 → draft serialization → independent verifier
    → provisional pack → G8 canonical rerender → status decision → write the pack

The verifier runs against a serialized draft in a scratch directory, so it only
ever sees what survived a round trip through JSON. Status is decided once,
afterwards, by :func:`video_research.status.decide`, and the pack is written a
single time carrying that verdict.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from .claims import ClaimLedger
from .diagnostics import Diagnostic, DiagnosticCode
from .gates import (
    GateOutcome,
    GateResult,
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
from .ports import (
    ClaimExtractor,
    ExtractedSource,
    ExtractionEngine,
    ExtractionError,
    IndependentVerifier,
    VerifierReport,
)
from .run import (
    EngineIdentity,
    GateRecord,
    ResearchPack,
    RunRecord,
    SourceDescriptor,
    SupportEnvelope,
    TranscriptKind,
    VerifierRecord,
)
from .status import decide
from .store import (
    SchemaError,
    decode_coverage,
    decode_ledger,
    dumps,
    encode_coverage,
    encode_ledger,
    read_pack,
    write_pack,
)
from .timeline import CoverageManifest
from .views import render_report, render_summary

#: The envelope slice 1 can honestly stand behind: deterministic fixture
#: sources only. Extraction adapters declare their own, wider envelopes.
FIXTURE_ENVELOPE = SupportEnvelope(
    envelope_id="fixture-v1",
    admitted_source_kinds=frozenset({"fixture"}),
    max_duration_ms=6 * 60 * 60 * 1000,
    admitted_languages=None,
    requires_known_duration=True,
)

_VIEW_DERIVATION_OK = "summary.md and report.html reproduce from canonical artifacts"


def research_video(
    source_ref: str,
    *,
    engine: ExtractionEngine,
    claim_extractor: ClaimExtractor,
    verifier: IndependentVerifier,
    envelope: SupportEnvelope = FIXTURE_ENVELOPE,
    output_dir: Path | str | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    manual_rescue: bool = False,
) -> ResearchPack:
    """Research one source and return its research pack.

    ``run_id`` and ``created_at`` are injectable so a test can pin them; left
    unset, each run mints its own. They are never derived from the source, which
    is what keeps a cold rerun a distinct run rather than a collision with the
    one it must not inherit findings from.
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    created_at = created_at or datetime.now(UTC).isoformat(timespec="seconds")

    descriptor = _safe_describe(engine, source_ref)
    if isinstance(descriptor, Diagnostic):
        return _abandon(
            run_id, created_at, envelope, _unknown_source(source_ref), descriptor, output_dir
        )

    envelope_gate = gate_envelope(envelope, descriptor)
    if envelope_gate.outcome is not GateOutcome.PASS:
        assert envelope_gate.diagnostic is not None
        return _abandon(
            run_id,
            created_at,
            envelope,
            descriptor,
            envelope_gate.diagnostic,
            output_dir,
            gates=(envelope_gate,),
        )

    try:
        source = engine.extract(source_ref)
    except ExtractionError as exc:
        return _abandon(
            run_id,
            created_at,
            envelope,
            descriptor,
            Diagnostic(DiagnosticCode.EXTRACTION_FAILED, str(exc)),
            output_dir,
            gates=(envelope_gate,),
        )

    coverage = CoverageManifest(
        duration_ms=source.descriptor.duration_ms,
        windows=source.windows,
        material_units=source.declared_material_units,
    )
    ledger = claim_extractor.extract_claims(source)

    evaluated = _evaluate(source, coverage, ledger, manual_rescue)
    provisional_view_gate = gate_view_derivation(True, _VIEW_DERIVATION_OK)
    gates = (envelope_gate, *evaluated[:-1], provisional_view_gate, evaluated[-1])

    # The verifier's own checks are the record of its disagreement; `decide`
    # reports each one, so restating them as a diagnostic would double-count.
    verifier_report = _verify_from_disk(verifier, coverage, ledger)

    candidate = _assemble_pack(
        run_id=run_id,
        created_at=created_at,
        envelope=envelope,
        source=source,
        coverage=coverage,
        ledger=ledger,
        gates=gates,
        verifier_report=verifier_report,
        manual_rescue=manual_rescue,
    )
    view_gate = _view_derivation_from_disk(candidate)
    gates = tuple(view_gate if gate.gate_id == "G8" else gate for gate in gates)
    pack = _assemble_pack(
        run_id=run_id,
        created_at=created_at,
        envelope=envelope,
        source=source,
        coverage=coverage,
        ledger=ledger,
        gates=gates,
        verifier_report=verifier_report,
        manual_rescue=manual_rescue,
    )

    if output_dir is not None:
        write_pack(Path(output_dir), pack)
    return pack


def _assemble_pack(
    *,
    run_id: str,
    created_at: str,
    envelope: SupportEnvelope,
    source: ExtractedSource,
    coverage: CoverageManifest,
    ledger: ClaimLedger,
    gates: tuple[GateResult, ...],
    verifier_report: VerifierReport,
    manual_rescue: bool,
) -> ResearchPack:
    diagnostics = source.diagnostics + collect_diagnostics(gates)
    diagnostics += _fallback_diagnostics(source)
    decision = decide(diagnostics, gates, verifier_report, manual_rescue)

    record = RunRecord(
        run_id=run_id,
        created_at=created_at,
        source=source.descriptor,
        envelope=envelope,
        engine=source.engine,
        transcript_kind=source.transcript.kind,
        transcript_language=source.transcript.language,
        status=decision.status,
        status_reasons=decision.reasons,
        gates=_gate_records(gates),
        verifier_checks=tuple(
            VerifierRecord(c.name, c.outcome.value, c.detail) for c in verifier_report.checks
        ),
        diagnostics=diagnostics,
        manual_rescue=manual_rescue,
    )

    return _rendered(ResearchPack(run=record, coverage=coverage, ledger=ledger))


def _evaluate(
    source: ExtractedSource,
    coverage: CoverageManifest,
    ledger: ClaimLedger,
    manual_rescue: bool,
) -> tuple[GateResult, ...]:
    schema_ok, schema_detail = _canonical_round_trips(coverage, ledger)
    return (
        gate_transcript(source.transcript, coverage.duration_ms, source.descriptor.language),
        gate_timeline_partition(coverage),
        gate_observation(coverage),
        gate_evidence(ledger, coverage),
        gate_material_recall(ledger, coverage),
        gate_schema(schema_ok, schema_detail),
        gate_unattended(manual_rescue),
    )


def _canonical_round_trips(coverage: CoverageManifest, ledger: ClaimLedger) -> tuple[bool, str]:
    """Whether canonical data survives a serialization round trip unchanged.

    This is the drift check the generated views depend on: if encoding then
    decoding then re-encoding is not byte-identical, then what a reader sees was
    not fully derived from what was stored.
    """
    try:
        coverage_json = dumps(encode_coverage(coverage))
        ledger_json = dumps(encode_ledger(ledger))
        coverage_again = dumps(encode_coverage(decode_coverage(_reparse(coverage_json))))
        ledger_again = dumps(encode_ledger(decode_ledger(_reparse(ledger_json))))
    except (SchemaError, ValueError) as exc:
        return False, f"canonical artifacts do not serialize: {exc}"
    if coverage_json != coverage_again:
        return False, "coverage manifest changes across a serialization round trip"
    if ledger_json != ledger_again:
        return False, "claim ledger changes across a serialization round trip"
    return True, "canonical artifacts round-trip byte-identically"


def _reparse(text: str) -> dict:
    import json

    return json.loads(text)


def _verify_from_disk(
    verifier: IndependentVerifier,
    coverage: CoverageManifest,
    ledger: ClaimLedger,
) -> VerifierReport:
    """Serialize the canonical artifacts and hand the verifier only those files."""
    with tempfile.TemporaryDirectory(prefix="video-research-draft-") as tmp:
        draft = Path(tmp)
        (draft / "coverage.json").write_text(dumps(encode_coverage(coverage)), encoding="utf-8")
        (draft / "claims.json").write_text(dumps(encode_ledger(ledger)), encoding="utf-8")
        return verifier.verify(draft)


def _view_derivation_from_disk(pack: ResearchPack) -> GateResult:
    """G8: persist a full pack, re-read canonical data, and reproduce both views."""
    try:
        with tempfile.TemporaryDirectory(prefix="video-research-view-check-") as tmp:
            draft = Path(tmp)
            write_pack(draft, pack)
            reloaded = read_pack(draft)
            summary_matches = render_summary(reloaded) == reloaded.summary_markdown
            report_matches = render_report(reloaded) == reloaded.report_html
    except (OSError, SchemaError, ValueError) as exc:
        return gate_view_derivation(False, f"canonical rerender failed: {exc}")

    if not summary_matches or not report_matches:
        drifted = []
        if not summary_matches:
            drifted.append("summary.md")
        if not report_matches:
            drifted.append("report.html")
        detail = f"view drift after canonical reload: {', '.join(drifted)}"
        return gate_view_derivation(False, detail)
    return gate_view_derivation(True, _VIEW_DERIVATION_OK)


def _fallback_diagnostics(source: ExtractedSource) -> tuple[Diagnostic, ...]:
    needs_fallback = source.transcript.kind is TranscriptKind.NONE or not source.transcript.segments
    if needs_fallback and not source.fallback_available:
        return (
            Diagnostic(
                DiagnosticCode.TRANSCRIPT_FALLBACK_UNAVAILABLE,
                "captions were unusable and no speech-recognition fallback was available",
            ),
        )
    return ()


def _gate_records(gates: tuple[GateResult, ...]) -> tuple[GateRecord, ...]:
    return tuple(GateRecord(g.gate_id, g.name, g.outcome.value, g.detail) for g in gates)


def _safe_describe(engine: ExtractionEngine, source_ref: str) -> SourceDescriptor | Diagnostic:
    try:
        return engine.describe(source_ref)
    except (ExtractionError, OSError, ValueError, KeyError) as exc:
        return Diagnostic(DiagnosticCode.EXTRACTION_FAILED, f"could not describe source: {exc}")


def _unknown_source(source_ref: str) -> SourceDescriptor:
    return SourceDescriptor(source_ref=source_ref, source_kind="unknown", duration_ms=0)


def _abandon(
    run_id: str,
    created_at: str,
    envelope: SupportEnvelope,
    descriptor: SourceDescriptor,
    diagnostic: Diagnostic,
    output_dir: Path | str | None,
    gates: tuple[GateResult, ...] = (),
) -> ResearchPack:
    """Produce a failed run that carries its reason and no misleading findings."""
    decision = decide((diagnostic,), gates, VerifierReport(), manual_rescue=False)
    record = RunRecord(
        run_id=run_id,
        created_at=created_at,
        source=descriptor,
        envelope=envelope,
        engine=EngineIdentity(name="none", version="none"),
        transcript_kind=TranscriptKind.NONE,
        transcript_language=None,
        status=decision.status,
        status_reasons=decision.reasons,
        gates=_gate_records(gates),
        diagnostics=(diagnostic,),
    )
    pack = _rendered(
        ResearchPack(
            run=record,
            coverage=CoverageManifest(duration_ms=max(descriptor.duration_ms, 0)),
            ledger=ClaimLedger(),
        )
    )
    if output_dir is not None:
        write_pack(Path(output_dir), pack)
    return pack


def _rendered(pack: ResearchPack) -> ResearchPack:
    return replace(pack, summary_markdown=render_summary(pack), report_html=render_report(pack))


__all__ = ["FIXTURE_ENVELOPE", "research_video"]
