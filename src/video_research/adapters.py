"""Deterministic adapters for the three ports.

These are the implementations slice 1 ships. They make the assurance core
runnable and exhaustively testable without a network, ffmpeg, or a model. Live
extraction, model-backed claim extraction, and semantic verification arrive as
further implementations of the same three protocols and touch nothing else.
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
from .ports import (
    CheckOutcome,
    ExtractedSource,
    ExtractionError,
    VerifierCheck,
    VerifierReport,
)
from .run import (
    EngineIdentity,
    SourceDescriptor,
    Transcript,
    TranscriptKind,
    TranscriptSegment,
)
from .store import (
    CLAIMS_FILE,
    COVERAGE_FILE,
    SchemaError,
    decode_coverage,
    decode_ledger,
)
from .timeline import (
    CoverageWindow,
    MaterialContentUnit,
    SourceSpan,
    SpanKind,
    SpeechCoverage,
    TimeInterval,
    VisualObservation,
)

FIXTURE_SOURCE_KIND = "fixture"


def _interval(payload: dict[str, Any]) -> TimeInterval:
    return TimeInterval(int(payload["start_ms"]), int(payload["end_ms"]))


def _span(payload: dict[str, Any]) -> SourceSpan:
    return SourceSpan(
        kind=SpanKind(payload.get("kind", "speech")),
        interval=_interval(payload),
        artifact_id=payload.get("artifact_id"),
        artifact_digest=payload.get("artifact_digest"),
        raw_timestamp=payload.get("raw_timestamp"),
    )


class FixtureExtractionEngine:
    """An extraction engine backed by a committed JSON fixture.

    The fixture stands in for a real engine's output: transcript, frames, OCR
    spans, coverage windows, and any diagnostics it would have raised. Because
    the shape is engine-neutral, a fixture describing a truncated transcript or
    an unobserved window exercises exactly the paths a real engine failure would.
    """

    name = "fixture"
    version = "1.0.0"

    def __init__(self, fixture_path: Path | str) -> None:
        self.fixture_path = Path(fixture_path)
        self._cache: dict[str, Any] | None = None

    def _payload(self) -> dict[str, Any]:
        if self._cache is None:
            if not self.fixture_path.exists():
                raise ExtractionError(f"fixture not found: {self.fixture_path}")
            try:
                payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ExtractionError(f"fixture is not valid JSON: {exc}") from exc
            except OSError as exc:
                raise ExtractionError(f"fixture could not be read: {exc}") from exc
            if not isinstance(payload, dict):
                raise ExtractionError("fixture root must be a JSON object")
            self._cache = payload
        return self._cache

    def describe(self, source_ref: str) -> SourceDescriptor:
        """Decode the source descriptor or normalize malformation at the port."""
        try:
            return self._describe(source_ref)
        except ExtractionError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ExtractionError(f"fixture extraction output is malformed: {exc}") from exc

    def _describe(self, source_ref: str) -> SourceDescriptor:
        source = self._payload()["source"]
        return SourceDescriptor(
            source_ref=source.get("source_ref", source_ref),
            source_kind=source.get("source_kind", FIXTURE_SOURCE_KIND),
            duration_ms=int(source["duration_ms"]),
            language=source.get("language"),
            title=source.get("title", ""),
            digest=source.get("digest"),
        )

    def extract(self, source_ref: str) -> ExtractedSource:
        """Decode fixture output or normalize every malformed shape at the port."""
        try:
            return self._extract(source_ref)
        except ExtractionError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ExtractionError(f"fixture extraction output is malformed: {exc}") from exc

    def _extract(self, source_ref: str) -> ExtractedSource:
        payload = self._payload()

        failure = payload.get("extraction_error")
        if failure:
            raise ExtractionError(str(failure))

        engine = payload.get("engine", {})
        transcript_payload = payload.get("transcript", {})
        segments = tuple(
            TranscriptSegment(
                interval=_interval(s),
                text=s.get("text", ""),
                speaker_label=s.get("speaker_label"),
            )
            for s in transcript_payload.get("segments", ())
        )

        return ExtractedSource(
            descriptor=self.describe(source_ref),
            engine=EngineIdentity(
                name=engine.get("name", self.name),
                version=engine.get("version", self.version),
                outbound_data=engine.get("outbound_data", "none"),
            ),
            transcript=Transcript(
                kind=TranscriptKind(transcript_payload.get("kind", "none")),
                language=transcript_payload.get("language"),
                segments=segments,
            ),
            windows=tuple(
                CoverageWindow(
                    interval=_interval(w),
                    speech=SpeechCoverage(w["speech"]),
                    visual=VisualObservation(w["visual"]),
                    extraction_method=w.get("extraction_method", "fixture"),
                    material_unit_ids=tuple(w.get("material_unit_ids", ())),
                )
                for w in payload.get("windows", ())
            ),
            frames=tuple(_span({**f, "kind": f.get("kind", "visual")})
                         for f in payload.get("frames", ())),
            ocr_spans=tuple(_span({**o, "kind": o.get("kind", "ocr")})
                            for o in payload.get("ocr_spans", ())),
            declared_material_units=tuple(
                MaterialContentUnit(
                    unit_id=u["unit_id"],
                    description=u.get("description", ""),
                    interval=_interval(u),
                )
                for u in payload.get("material_units", ())
            ),
            diagnostics=tuple(
                Diagnostic(
                    code=DiagnosticCode(d["code"]),
                    detail=d.get("detail", ""),
                    interval=_interval(d["interval"]) if d.get("interval") else None,
                )
                for d in payload.get("diagnostics", ())
            ),
            fallback_available=bool(payload.get("fallback_available", True)),
        )


class FixtureClaimExtractor:
    """Reads the claim ledger a fixture declares.

    A real claim extractor is a model call. Keeping the fixture's claims in the
    same file as its source material means one fixture defines both the input
    and the expected reading of it, which is what makes a golden test a golden
    test.
    """

    def __init__(self, fixture_path: Path | str) -> None:
        self.fixture_path = Path(fixture_path)

    def extract_claims(self, source: ExtractedSource) -> ClaimLedger:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        claims: list[AtomicClaim] = []
        evidence: list[EvidenceReference] = []
        external: list[ExternalReference] = []

        for entry in payload.get("claims", ()):
            claim_id = entry["claim_id"]
            claims.append(
                AtomicClaim(
                    claim_id=claim_id,
                    statement=entry["statement"],
                    role=ClaimRole(entry["role"]),
                    material=bool(entry.get("material", False)),
                    covers_units=tuple(entry.get("covers_units", ())),
                    speaker_label=entry.get("speaker_label"),
                )
            )
            for ref in entry.get("evidence", ()):
                evidence.append(
                    EvidenceReference(
                        claim_id=claim_id,
                        span=_span(ref),
                        relation=EvidenceRelation(ref["relation"]),
                        note=ref.get("note", ""),
                    )
                )
            for ref in entry.get("external", ()):
                external.append(
                    ExternalReference(
                        claim_id=claim_id,
                        url=ref["url"],
                        title=ref.get("title", ref["url"]),
                        relation=EvidenceRelation(ref["relation"]),
                    )
                )

        return ClaimLedger(tuple(claims), tuple(evidence), tuple(external))


class StructuralVerifier:
    """An independent pass over the canonical artifacts as they were written.

    It re-derives coverage and evidence properties from the files rather than
    from the objects the generator built, so a serialization bug shows up here
    even when the in-memory run looked perfect.

    What it cannot do is judge meaning. Whether a claim actually follows from the
    span it cites is a semantic question, and this verifier answers it only when
    the source declares benchmark material units, which supply an oracle. Without
    that oracle it reports ``UNVERIFIED`` — never ``PASS`` — so an arbitrary
    video cannot reach trusted completeness on a check nobody performed.

    It also cannot see what extraction never captured. A correction the engine
    missed is invisible to any second pass over the same evidence; that gap is
    the business of the coverage gates upstream, not of this verifier.
    """

    name = "structural"

    def verify(self, pack_dir: Path) -> VerifierReport:
        checks: list[VerifierCheck] = []

        try:
            coverage = decode_coverage(json.loads((pack_dir / COVERAGE_FILE).read_text("utf-8")))
            ledger = decode_ledger(json.loads((pack_dir / CLAIMS_FILE).read_text("utf-8")))
        except (OSError, json.JSONDecodeError, SchemaError) as exc:
            return VerifierReport(
                (VerifierCheck("artifacts_readable", CheckOutcome.FAIL, str(exc)),)
            )

        checks.append(
            VerifierCheck("artifacts_readable", CheckOutcome.PASS,
                          "canonical artifacts decoded from disk")
        )

        defects = coverage.partition_defects()
        checks.append(
            VerifierCheck(
                "timeline_partitioned",
                CheckOutcome.PASS if not defects else CheckOutcome.FAIL,
                "; ".join(defects) or f"{len(coverage.windows)} windows tile the timeline",
            )
        )

        unobserved = coverage.unobserved_windows()
        checks.append(
            VerifierCheck(
                "windows_observed",
                CheckOutcome.PASS if not unobserved else CheckOutcome.FAIL,
                f"{len(unobserved)} unobserved window(s)"
                if unobserved
                else "every window carries an observation state",
            )
        )

        unsupported = sorted(
            c.claim_id
            for c in ledger.material_claims()
            if not ledger.evidence_for(c.claim_id)
        )
        checks.append(
            VerifierCheck(
                "material_claims_supported",
                CheckOutcome.PASS if not unsupported else CheckOutcome.FAIL,
                f"unsupported: {', '.join(unsupported)}"
                if unsupported
                else f"{len(ledger.material_claims())} material claim(s) cite evidence",
            )
        )

        timeline = coverage.timeline if coverage.duration_ms > 0 else None
        stray = (
            sorted(
                f"{r.claim_id}@{r.span.interval.label()}"
                for r in ledger.evidence
                if not r.span.interval.within(timeline)
            )
            if timeline
            else []
        )
        checks.append(
            VerifierCheck(
                "evidence_in_range",
                CheckOutcome.PASS if not stray else CheckOutcome.FAIL,
                f"outside the source: {', '.join(stray)}"
                if stray
                else f"{len(ledger.evidence)} evidence reference(s) resolve inside the source",
            )
        )

        declared = coverage.declared_unit_ids()
        if not declared:
            unresolved = "source declares no material content units, so recall has no oracle"
            checks.append(VerifierCheck("material_recall", CheckOutcome.UNVERIFIED, unresolved))
            checks.append(
                VerifierCheck(
                    "claim_entailment",
                    CheckOutcome.UNVERIFIED,
                    "semantic entailment needs either a declared oracle or a model-backed "
                    "verifier, which this build does not have",
                )
            )
        else:
            missing = sorted(declared - ledger.covered_unit_ids())
            checks.append(
                VerifierCheck(
                    "material_recall",
                    CheckOutcome.PASS if not missing else CheckOutcome.FAIL,
                    f"unrepresented: {', '.join(missing)}"
                    if missing
                    else f"{len(declared)} declared unit(s) linked to claims",
                )
            )
            linked = frozenset(uid for c in ledger.claims for uid in c.covers_units)
            unlinked = sorted(linked - declared)
            checks.append(
                VerifierCheck(
                    "claim_entailment",
                    CheckOutcome.PASS if not unlinked else CheckOutcome.FAIL,
                    f"claims cite undeclared unit(s): {', '.join(unlinked)}"
                    if unlinked
                    else "every claim-to-unit link resolves against the declared oracle",
                )
            )

        return VerifierReport(tuple(checks))
