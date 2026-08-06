# Implementation plan: assurance core (slice 1)

Status: implemented (slice 1)
Source spec: [`docs/specs/video-summary-skill.md`](../specs/video-summary-skill.md)
Domain language: [`CONTEXT.md`](../../CONTEXT.md)
Binding decision: [`docs/adr/0001`](../adr/0001-structured-source-generated-research-views.md)
Produced by: engineering plan review, 2026-08-06

This plan does not change the product specification. It sequences the
specification into slices and records the engineering decisions that the
specification deliberately left open.

## 1. Why the spec needs a sequencing plan

The specification describes a finished product: live YouTube ingestion, an
extraction engine trial, model-driven claim extraction, an independent
cold-context verifier, optional external fact checking, focused re-extraction,
a ten-format benchmark corpus, and eleven classes of injected failure.

Two properties of that product make "build it all at once" the wrong move:

- **The valuable half is deterministic; the expensive half is not.** Coverage
  accounting, evidence validation, severity classification, and the
  complete/partial/failed decision are pure functions over structured data.
  Extraction and claim extraction involve the network, ffmpeg, ASR, OCR, and a
  language model. Mixing them produces a system whose central guarantee cannot
  be tested without a video download and a model call.
- **The acceptance criterion is a negative.** Score 10 requires *zero*
  **False Completeness** results. Negatives are proven by exhaustively driving
  the decision function, which is only possible when the decision function is
  deterministic and reachable from a fixture.

So slice 1 builds the assurance core against a deterministic source fixture,
behind the same public entry point a live run will use.

## 2. Layer boundaries

The spec already draws the seam; this plan names it.

```
                    ┌─────────────────────────────────────────┐
  YouTube / files → │  L1  EXTRACTION (replaceable, impure)   │
                    │      network · ffmpeg · ASR · OCR       │
                    └──────────────────┬──────────────────────┘
                                       │ ExtractionEngine port
                                       │ (ExtractedSource: pure data)
                    ┌──────────────────▼──────────────────────┐
                    │  L2  ASSURANCE CORE (pure, canonical)   │
                    │      envelope · transcript validation   │
                    │      coverage windows · claim ledger    │
                    │      diagnostics · GATES · STATUS       │
                    └──────────────────┬──────────────────────┘
                                       │ canonical artifacts on disk
                                       │ (schema-versioned JSON)
                    ┌──────────────────▼──────────────────────┐
                    │  L3  GENERATED VIEWS (pure)             │
                    │      summary.md · report.html           │
                    └─────────────────────────────────────────┘
```

Rules that make the boundary real rather than aspirational:

- L2 imports nothing from L1 implementations. It consumes `ExtractedSource`,
  a plain data structure with no engine-specific shapes (spec: "Canonical
  project interfaces will not expose engine-specific output shapes").
- L2 performs no I/O and makes no model calls. Anything non-deterministic
  enters through a port.
- L3 reads canonical artifacts only. It never receives the in-memory objects
  the generator built, so a serialization bug cannot hide (ADR 0001).

## 3. Data flow of one run

```
research_video(source_ref, engine, extractor, verifier, config)
   │
   ├─1 SUPPORT ENVELOPE  ── out of envelope ────────────────► FAILED
   │      declared conditions vs source descriptor
   │
   ├─2 EXTRACT (port)  ──► ExtractedSource
   │      transcript candidate · frames · OCR · duration
   │
   ├─3 TRANSCRIPT VALIDATION
   │      language · monotonic timing · speech coverage ratio
   │      · truncation vs duration
   │      fail ──► FALLBACK TRANSCRIPT (port)  ── unavailable ──► blocker
   │
   ├─4 COVERAGE MANIFEST
   │      partition [0, duration] with no gap and no overlap
   │      each window: speech state · visual observation state
   │                   · extraction method · unit locations
   │      declared Material Content Units (the single recall oracle)
   │
   ├─5 CLAIM EXTRACTION (port)  ──► ClaimLedger
   │      atomic claims · roles · evidence references · relations
   │
   ├─6 DIAGNOSTICS
   │      each finding classified INFO | BLOCKER | FATAL (deterministic table)
   │
   ├─7 GATES G1..G9  (pure; each yields PASS | FAIL | UNVERIFIED)
   │
   ├─8 PERSIST canonical artifacts (schema-versioned)
   │
   ├─9 INDEPENDENT VERIFIER (port)
   │      input = the serialized pack re-read from disk. Nothing else.
   │      output = per-check outcomes PASS | FAIL | UNVERIFIED
   │
   ├─10 STATUS = decide(diagnostics, gates, verifier, manual_rescue)
   │      one pure function, the only place status is ever produced
   │
   └─11 RENDER views from canonical artifacts ──► ResearchPack
```

## 4. The status decision

`False Completeness` is prevented by making one pure function the sole
producer of run status, and by making it fail closed.

```
decide(diagnostics, gate_outcomes, verifier_checks, manual_rescue) -> RunStatus

  if any diagnostic.severity is FATAL                     -> FAILED
  if any gate outcome is FAIL and gate is minimum-coverage-> FAILED
  if any diagnostic.severity is COMPLETENESS_BLOCKER      -> PARTIAL
  if any gate outcome is not PASS                         -> PARTIAL
  if any verifier check outcome is not PASS               -> PARTIAL
  if manual_rescue                                        -> PARTIAL
  otherwise                                               -> TRUSTED_COMPLETE
```

Three properties carry the guarantee:

1. **`UNVERIFIED` is not a pass.** A check nobody could decide forces
   `PARTIAL`. Absence of evidence is never evidence of completeness. This is
   the difference between this design and every engine that degrades material
   failures into warnings (research note, integration risk 3).
2. **`TRUSTED_COMPLETE` is the fall-through, reachable only when every input
   is explicitly `PASS`.** A gate added later that nobody wired up yields
   `UNVERIFIED`, not silence.
3. **Status is never an argument.** No caller passes a status in; no renderer
   computes one. Views read the status the decision function produced.

### Gates

| ID | Gate | Fails when |
|----|------|-----------|
| G1 | Support envelope | Source outside declared conditions |
| G2 | Transcript | No **Validated Transcript** and no usable **Fallback Transcript** |
| G3 | Timeline partition | Windows do not tile `[0, duration]` exactly |
| G4 | Observation state | Any window lacks speech or visual observation state |
| G5 | Evidence support | A material claim has no resolvable **Evidence Reference** |
| G6 | Material recall | A declared **Material Content Unit** has no representing claim |
| G7 | Schema validity | Canonical artifacts fail their versioned schema |
| G8 | View derivation | Re-rendering from canonical artifacts does not reproduce views |
| G9 | Unattended | **Manual Rescue** was required |

G6 yields `UNVERIFIED` when the source declares no benchmark material units,
which is the honest answer for an arbitrary video and correctly forces
`PARTIAL`. Benchmark fixtures declare their units, so they can reach
`TRUSTED_COMPLETE`.

### Modelling corrections the gates depend on

Three shapes have to be right or the gates cannot be evaluated at all.

**A source location is not an evidence reference.** A timestamp alone cannot
express "this frame at 14:32 shows the error", "this speech spans 14:30-14:41",
or "this OCR text came from that frame". Split them:

```
SourceSpan            = kind (SPEECH | VISUAL | OCR) + [start_ms, end_ms]
                        + optional artifact id and digest
EvidenceReference     = claim_id + SourceSpan + EvidenceRelation
                        (SUPPORTS | CONTRADICTS | QUALIFIES)
```

`EvidenceReference` is the *edge*, which is what `CONTEXT.md` already says:
"Every **Evidence Reference** has exactly one **Evidence Relation** to its
**Atomic Claim**." The same span can therefore support one claim and qualify
another, as two edges over one location.

**Material-unit coverage needs one oracle and an explicit link.** "Every
**Material Content Unit** must appear in a **Trusted-Complete Run**" is
unverifiable if declarations are scattered. Declared units are persisted once on
the coverage manifest (`coverage.json` → `material_units`) — the single oracle
both G6 and the structural verifier re-read from the pack. Window
`material_unit_ids` only locate units on the timeline; they do not declare the
oracle. Claims carry `covers_units: [MaterialUnitId]`, and G6 checks that every
declared unit is named by at least one material claim.

**Diagnostics are an enumerated table, not free text.** Each diagnostic has a
stable code and a fixed severity. Severity is looked up, never chosen at the
call site, so "is this a warning or a blocker" cannot drift between callers.

| Code | Severity |
|------|----------|
| `SOURCE_OUT_OF_ENVELOPE` | fatal |
| `EXTRACTION_FAILED` | fatal |
| `NO_USABLE_TRANSCRIPT` | fatal |
| `CANONICAL_SCHEMA_INVALID` | fatal |
| `VIEW_DERIVATION_FAILED` | blocker |
| `TRANSCRIPT_TRUNCATED` | blocker |
| `TRANSCRIPT_LANGUAGE_UNEXPECTED` | blocker |
| `TRANSCRIPT_TIMING_NONMONOTONIC` | blocker |
| `TRANSCRIPT_FALLBACK_UNAVAILABLE` | blocker |
| `TIMELINE_NOT_PARTITIONED` | blocker |
| `WINDOW_UNOBSERVED` | blocker |
| `MATERIAL_CLAIM_UNSUPPORTED` | blocker |
| `EVIDENCE_OUT_OF_RANGE` | blocker |
| `MATERIAL_UNIT_UNREPRESENTED` | blocker |
| `OUTPUT_TRUNCATED` | blocker |
| `MANUAL_RESCUE_USED` | blocker |
| `VERIFIER_DISAGREEMENT` | blocker |
| `DUPLICATE_EVIDENCE` | informational |
| `FRAME_SAMPLING_SPARSE` | informational |

`OUTPUT_TRUNCATED` resolves the standing conflict between "bounded output
sizes" (user story 45) and "every material unit appears" (user story 3): a run
that had to drop material content to fit a budget is a **Partial Run**, never a
silent truncation.

### The Support Envelope is declared, not implied

"YouTube but not private or live" does not bound a run. The envelope is a
record with enumerated conditions, stored in the run record, and G1 evaluates
the source descriptor against it. Slice 1 declares an envelope admitting only
deterministic fixture sources; extraction adapters widen it with their own
conditions (duration ceiling, language set, caption availability) when they
land. A source that the envelope does not explicitly admit is out of it.

## 5. Engineering decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Python 3.11+, stdlib only for the core | Matches `tools/extract_evidence_frames.py` and the yt-dlp/ffmpeg/ASR/OCR ecosystem. A stdlib-only core keeps the assurance layer installable and auditable; extraction adapters may add dependencies. |
| D2 | Timestamps are integer milliseconds | Float timelines produce spurious sub-nanosecond gaps in a partition check. Integer ms makes G3 exact. Raw engine timestamps are preserved alongside (spec: "**Evidence References** preserve raw timestamps"). |
| D3 | Extraction, claim extraction, and verification are ports (Protocols) | Spec user story 35 and the provisional status of `mcp-video-analyzer`. Slice 1 ships fixture implementations; engine adapters land after the trial gate. |
| D4 | The verifier receives the serialized pack re-read from disk | Makes "cold context, not the generator's reasoning" a property of the type signature rather than of prompt discipline. Also catches serialization drift. |
| D5 | Status has exactly one producer, `video_research.status.decide` | The choke point that makes the negative acceptance criterion provable. |
| D6 | Canonical artifacts carry `schema_version` and validate on read | Spec user story 36; without it, migration is archaeology. |
| D7 | Rendering takes every time-dependent value from the run record | `datetime.now()` inside a renderer breaks "rerendering from unchanged canonical artifacts is deterministic". |
| D8 | `run_id` is generated once at run start and stored | A **Cold Rerun** must be a distinct run; a content-derived id would collide with the run it must not inherit from. |
| D9 | `mcp-video-analyzer` is not adopted in slice 1 | The spec makes adoption provisional pending a local compatibility review and benchmark corpus run. Adopting before that gate would contradict the spec, not follow it. |
| D10 | All source-derived text is escaped when rendered to HTML | Transcript, OCR, title, and metadata are attacker-controlled. `report.html` interpolating them unescaped is an injection hole in a file the user is told to open. |
| D11 | A claim keeps its video **Evidence References** even when its role is **External Fact** | Preserves origin through verification. The spec's four roles stay mutually exclusive as written; provenance survives because the video evidence stays attached alongside `external_references`. |

## 6. Slice 1 scope

In scope:

- Canonical domain types matching `CONTEXT.md` one-for-one.
- Extraction, claim-extraction, and verification ports.
- Deterministic fixture adapters for all three.
- Gates G1..G9 and the status decision function.
- Schema-versioned canonical store (`run.json`, `coverage.json`, `claims.json`).
- Generated `summary.md` and `report.html`.
- Public entry point `research_video(...)` and a CLI.
- Fixture corpus plus failure-injection fixtures.

### NOT in slice 1

Each item is deferred with a reason. None is cut from the specification.

| Deferred | Reason |
|----------|--------|
| Live YouTube ingestion (`yt-dlp`) | Needs network and violates CI determinism. Lands as an `ExtractionEngine` adapter behind the port already built here. |
| `mcp-video-analyzer` adapter | Spec makes adoption provisional pending the trial acceptance gate (research note §"Trial acceptance gate"). |
| Model-backed claim extraction | Lands as a `ClaimExtractor` adapter. The port and its contract tests exist in slice 1. |
| Model-backed semantic verifier | Lands as an `IndependentVerifier` adapter. Slice 1 ships the structural verifier; semantic checks report `UNVERIFIED`, which correctly forces `PARTIAL`. |
| External fact-check mode | Optional by specification. Needs the claim ledger to exist first, which is what slice 1 builds. |
| Focused re-extraction | Repairs weak intervals produced by a real engine; there is no real engine yet. |
| ASR fallback implementation | Port and blocker path exist; the Whisper adapter is extraction work. |
| Ten-format benchmark corpus | Requires real extraction. Slice 1 ships synthetic fixtures covering the same *shapes*. |
| Chunked processing for long videos | An optimization on a pipeline that must first exist. |

### What already exists

| Asset | Reuse |
|-------|-------|
| `tools/extract_evidence_frames.py` | Prior art for scene-change frame selection and manifest shape. Not imported: it hardcodes `/Users/stanley/...` paths and is an ad-hoc script. Its manifest shape informs `ExtractedSource.frames`. Left in place, untouched. |
| `CONTEXT.md` | Directly becomes the domain type names. No translation layer. |
| `research/github-video-summary-skills.md` | Supplies the integration risks encoded as D3 and D9. |

## 7. Test plan

Primary seam is the public entry point, per the spec's testing decisions.
Tests assert observable **Research Pack** behaviour: artifacts, evidence,
coverage, status, diagnostics. They do not assert helper calls or prompt text.

```
CODE PATHS                                      OBSERVABLE BEHAVIOUR
[+] skill.research_video
  ├── happy path (benchmark fixture)            ── TRUSTED_COMPLETE
  ├── out of envelope                           ── FAILED + reason
  ├── extraction raises                         ── FAILED, no misleading summary
  └── no material units declared                ── PARTIAL (G6 UNVERIFIED)

[+] video_research.status.decide
  ├── fatal beats blocker                       ── FAILED
  ├── blocker beats all-pass gates              ── PARTIAL
  ├── any UNVERIFIED gate                       ── PARTIAL
  ├── any UNVERIFIED verifier check             ── PARTIAL
  ├── manual rescue                             ── PARTIAL
  └── everything PASS                           ── TRUSTED_COMPLETE
      + exhaustive: no input combination containing a non-PASS
        yields TRUSTED_COMPLETE            (the False Completeness proof)

[+] video_research.gates
  ├── G3 gap / overlap / short tail / unsorted  ── FAIL with the interval named
  ├── G4 unobserved window                      ── FAIL
  ├── G5 material claim without evidence        ── FAIL
  ├── G5 evidence outside duration              ── FAIL
  └── G6 declared unit unrepresented            ── FAIL

[+] video_research.store
  ├── round trip                                ── identical canonical data
  ├── unknown schema_version                    ── raises, never silently reads
  └── cold rerun                                ── distinct run_id, no inherited findings

[+] views
  ├── summary.md and report.html                ── same status, same material claims
  └── re-render unchanged artifacts             ── byte-identical

FAILURE INJECTION (each must produce PARTIAL or FAILED, never TRUSTED_COMPLETE)
  truncated captions · wrong-language captions · timestamp drift
  · no transcript/fallback · missing final window · gap / overlap
  · unobserved / missing visual coverage · unsupported material claim
  · evidence out of range · unrepresented material unit
  · units only on non-material claims · claim cites undeclared unit
  · unsupported source · extraction failure · unknown duration
```

### Failure modes

| Codepath | Realistic production failure | Test | Error handling | User sees |
|----------|------------------------------|------|----------------|-----------|
| Extraction port | Engine raises or returns partial data | yes | Fatal diagnostic | `FAILED` + reason |
| Transcript validation | Captions truncated at 80% of duration | yes | Blocker diagnostic | `PARTIAL` + named gap |
| Coverage partition | Final window ends before duration | yes | G3 `FAIL` | `PARTIAL` + interval |
| Claim extraction port | Returns a claim citing a nonexistent window | yes | G5 `FAIL` | `PARTIAL` + claim id |
| Store read | `schema_version` from a future release | yes | Raises | `FAILED`, not a wrong read |
| Verifier port | Verifier disagrees with the draft | yes | Check `FAIL` | `PARTIAL` + finding |
| Renderer | Non-deterministic ordering | yes | Sorted output | n/a |

No critical gaps: every failure mode above has a test, error handling, and a
visible consequence in the run status.

## 8. Sequencing

Slice 1 is one lane. The layers have a strict dependency order, so there is no
parallelization opportunity within it:

```
Lane A (sequential):
  domain types → ports → gates + status → store → views → skill entry → fixtures + tests
```

Later slices do parallelize:

```
Lane B: yt-dlp / mcp-video-analyzer extraction adapter   (adapters/ only)
Lane C: model-backed claim extractor                     (adapters/ only)
Lane D: model-backed semantic verifier                   (adapters/ only)
```

B, C, and D depend on slice 1 and on nothing else; each touches only
`adapters/` plus its own tests, so they can run in parallel worktrees without
conflict. External fact checking depends on C.

## 9. Risks

| Risk | Mitigation |
|------|-----------|
| The structural verifier is a tautology of the gates | It reads the serialized pack, not in-memory state, and reports `UNVERIFIED` for semantic checks it cannot decide. Documented as a limitation in the skill, not hidden. |
| Fixture-only testing proves nothing about real videos | Correct, and stated. Slice 1 claims a tested assurance core, not a tested product. The **Support Envelope** in slice 1 admits only fixture sources. |
| Layering invites premature abstraction | Each layer is mandated by the spec or the ADR. No layer exists for a hypothetical second variant. |
| Coverage windows prove bookkeeping, not observation | A partitioned timeline shows every interval was *accounted for*, not that a brief material visual was *seen*. G3 and G4 are necessary, never sufficient. Real observation confidence arrives with real extraction plus benchmark recall, which is why arbitrary videos cannot reach `TRUSTED_COMPLETE` in slice 1. |
| The verifier cannot see what extraction never captured | True and unfixable by a second pass over the same evidence. Cold context removes shared reasoning, not shared blind spots. Recorded as a limitation of the assurance layer; upstream omission is an extraction-coverage problem, addressed by G4 and, later, focused re-extraction. |

## 10. Outside voice

An independent review of the specification (Codex, high reasoning effort) ran
against this plan. It reached the same slice-1 boundary independently. Its
substantive findings are folded in above: the undefined **Support Envelope**
(§4 "declared, not implied"), evidence relation as an edge and typed source
spans (§4 modelling corrections), missing unit-to-claim linkage (G6), unenumerated
diagnostic severities (§4 table), the bounded-output conflict
(`OUTPUT_TRUNCATED`), untrusted source text in generated HTML (D10), and the
two limits now recorded as risks above.

One finding is **not** adopted: that **External Fact** should be a verification
status orthogonal to claim origin rather than one of four mutually exclusive
roles. The argument is sound as modelling, but the four-role split is the
product's domain language (`CONTEXT.md`) and changing it is a product decision,
not an engineering one. D11 preserves the provenance the objection is about
without contradicting the spec. External fact checking is out of slice 1, so
nothing is blocked. **Open question for whoever implements external fact
checking:** if D11 turns out to lose information in practice, raise a domain
change against `CONTEXT.md` rather than diverging from it in code.
