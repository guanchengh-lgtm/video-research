# Engineering Review: Settled Evidence Frames

Date: 2026-08-19  
Branch: `fm/vr-frame-chart-settle`  
Review target: launch brief, current extraction tool and adapter seam, named ORB/GEX evidence, and completed outside-voice report.

## Outcome

Proceed with four P1 requirements:

1. Interval-aware multi-probe settling, not a fixed delay.
2. An explicit evidence-quality contract that handles face-dominant mixed frames.
3. Fail-closed adapter behavior with versioned selection and rejection provenance.
4. A labeled regression corpus plus a public-boundary False Completeness test.

Keep final status in `video_research.status.decide`. Keep Pillow and ffmpeg outside the pure assurance core. No product fork remains.

## Step 0: Scope Challenge

Scope accepted at six repository surfaces, below the eight-file smell threshold:

1. `src/video_research/frame_adapter.py` owns Presentation Segment intervals, evidence-quality features, ranking, selection results, and provenance. It is an impure adapter module and is not imported by the pure core.
2. `tools/extract_evidence_frames.py` remains the executable ffmpeg entry point.
3. `tests/test_frame_adapter.py` locks interval math, scoring, ranking, and the labeled corpus.
4. `tests/test_extract_evidence_frames.py` locks ffmpeg errors, periodic coverage, candidate identity, and manifest provenance.
5. `tests/test_failure_injection.py` names the public-boundary regression: no eligible material visual leaves its window unobserved and cannot yield a Trusted-Complete Run.
6. `pyproject.toml` declares Pillow in a tools/extraction extra and development dependencies without changing the dependency-free core install.

No new gate, status path, canonical schema, service, or framework is justified. Existing G4 already degrades an unobserved visual Coverage Window. `TODOS.md` needs no new item.

## Diagnostic Reasoning

Trigger, mask, and symptom are distinct:

- **Trigger:** `detect_scene_timestamps()` finds the cut and `extract_frame()` samples the exact cut. Outside voice found a clean ORB 06:54 slide for the bad 06:52 boundary, directly proving the post-cut counterfactual.
- **Mask:** `is_screen_content()` uses only left-half mean saturation. It can hide the timing defect and independently drops dark colorful GEX charts.
- **Symptom:** 06:52 is a full talking head mislabeled as tariff/COVID visual evidence. 07:30 is a face-dominant mixed frame with text, so the literal phrase “talking-head-only” would not fix it.

Motivating code:

```python
# tools/extract_evidence_frames.py:72
"-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",

# tools/extract_evidence_frames.py:87
"ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video),

# tools/extract_evidence_frames.py:103-107
left = img.crop((0, 0, w // 2, h))
mean_sat = sum(pixels) / len(pixels)
return mean_sat <= MAX_LEFT_SATURATION
```

## What Already Exists

- ffmpeg scene detection and JPEG extraction already exist. Reuse their boundary and output plumbing.
- `ExtractionEngine` already isolates impure extraction from the pure core.
- `ExtractedSource.frames` already carries engine-neutral visual spans.
- G4 already makes unobserved visual windows Completeness Blockers.
- The prior frame pass already identified blank, skin, edge, dark-UI, text-slide, periodic, and claim-aligned signals.
- The undamaged benchmark and failure-injection suite already prove the one-status-producer contract.

The implementation creates one selector, not a parallel pipeline.

## Architecture Review

### A1. Exact-cut selection crosses presentation state

`[P1] (confidence: 10/10) tools/extract_evidence_frames.py:67-90` extracts one JPEG at each scene boundary with no settle window, next-cut bound, or ranking.

Decision: convert consecutive cuts into bounded Presentation Segment intervals. Probe 0.5, 1.0, and 2.0 seconds after each boundary, always before the next cut's guard. Short intervals use a safe midpoint. Long no-cut intervals receive bounded periodic probes. Prefer the earliest eligible candidate stable with an adjacent probe; when no pair stabilizes, choose the highest-quality eligible candidate or return no selection.

This costs more ffmpeg seeks than a fixed delay, but the verified 06:52 to 06:54 replacement and rapid-cut failure make the complete version necessary.

### A2. Selection belongs at the impure adapter boundary

`[P1] (confidence: 9/10) src/video_research/adapters.py:257-265` states that canonical verification cannot see visual evidence extraction missed.

Decision: keep image decoding and scoring in one impure adapter module used by the tool. A result is explicitly selected or rejected. A rejected material interval remains visually unobserved so G4 degrades the Research Pack. No selector code may decide run status.

```text
video
  |
  +-- ffmpeg cuts + duration
  |
  +-- Presentation Segment intervals [cut_i, cut_i+1)
  |
  +-- bounded probes: 0.5s / 1.0s / 2.0s + periodic probes
  |
  +-- downsample once -> evidence features + adjacent stability
  |
  +-- rank eligible candidates
  |      +-- hard-drop blank and full talking head
  |      +-- strongly penalize face-dominant mixed frame
  |      +-- keep dark colorful chart regardless of saturation
  |      +-- allow small PIP only when evidence dominates and no clean peer wins
  |
  +-- selected Evidence Frame + provenance
         OR rejection provenance + unobserved visual window -> G4 -> Partial Run
```

## Code Quality Review

### C1. Saturation is an invalid single-axis proxy

`[P1] (confidence: 10/10) tools/extract_evidence_frames.py:93-107` reduces evidence quality to left-half mean saturation. Named measurements are 86.66 for 06:52, 35.55 for 07:30, 3.56 for settled 06:54, and 130.08 for useful GEX 00:28.

Decision: downsample once; hard-drop blank/near-empty frames; positively score text/slide structure, chart/UI edges, and useful non-face area; estimate face/skin occupancy over full-frame tiles and connected regions; hard-drop face-only frames; strongly penalize face-dominant mixed frames; never use global saturation as a hard rejection.

If all relevant candidates are face-dominant, return no frame. Do not manufacture a misleading caption or Evidence Reference.

### C2. Extraction failure silently becomes a valid 0.0 sample

`[P1] (confidence: 9/10) tools/extract_evidence_frames.py:69-82,138-140` ignores ffmpeg's return code and converts an empty timestamp set to `[0.0]`.

Decision: distinguish successful no-cut output from ffmpeg failure. Raise an extraction error on process failure or missing output. No-cut video uses periodic probes; failed detection never marks a window observed.

### C3. Provenance is insufficient

`[P1] (confidence: 10/10) tools/extract_evidence_frames.py:165-170` stores only selected timestamp, path, and method.

Decision: version the manifest and record integer-millisecond boundary/interval times, selected time, settle offset, candidate method, feature and stability scores, selection or rejection reason, and immutable configuration version. Keep raw timestamps only for navigation.

### C4. Same-second candidate names overwrite files

`[P2] (confidence: 10/10) tools/extract_evidence_frames.py:146` names temporary candidates with integer `MMSS`.

Decision: use ordinal plus millisecond candidate identity.

### C5. Full-resolution pixel lists waste memory

`[P2] (confidence: 9/10) tools/extract_evidence_frames.py:101-106` materializes the full image's saturation values.

Decision: use a fixed analysis grid and reuse decoded feature data.

## Test Review

Framework: pytest from `AGENTS.md` and `pyproject.toml`.

```text
CODE PATHS                                        TRUST / RESEARCH-PACK OUTCOMES
[+] build_intervals()/probe_times()               [+] 06:52 Presentation Segment
  +-- [GAP][CRITICAL] normal multi-probe scene      +-- [GAP][CRITICAL] selects clean 06:54
  +-- [GAP][CRITICAL] rapid next cut                +-- [GAP][CRITICAL] never crosses segment
  +-- [GAP] final/no-cut periodic probes
  +-- [GAP] never-stable animation                 [+] 07:30 face-dominant mixed frame
                                                     +-- [GAP][CRITICAL] clean peer wins or gap
[+] analyze()/rank()
  +-- [GAP][CRITICAL] full talking head            [+] Chart and slide preservation
  +-- [GAP][CRITICAL] face-dominant mixed frame      +-- [GAP][CRITICAL] colorful dark GEX kept
  +-- [GAP] small PIP with dominant evidence         +-- [GAP] bright/dark/grayscale slides kept
  +-- [GAP][CRITICAL] dark colorful chart            +-- [GAP] black/fade/blur/transition dropped
  +-- [GAP] beige or grayscale slide
  +-- [GAP] blank/fade/blur/transition             [+] Public trust boundary
                                                     +-- [GAP][CRITICAL] no eligible visual
[+] tool integration                                      remains unobserved
  +-- [GAP][CRITICAL] ffmpeg nonzero exit             +-- [GAP][CRITICAL] G4 forces Partial
  +-- [GAP] same-second candidate identity
  +-- [GAP][CRITICAL] versioned provenance

CURRENT COVERAGE: 0/18 selector branches have repository tests.
GAPS: 18 | CRITICAL: 11
```

Required labeled corpus:

- `0652_scene.jpg`: reject, full talking head.
- `0654_scene.jpg`: select, settled tariff slide for the 06:52 interval.
- `0730_scene.jpg`: reject or lose to a clean peer, face-dominant mixed slide.
- GEX `0028_scene.jpg`: keep, high-saturation dark platform chart.
- Bright text slide, dark text slide, grayscale slide, and right-heavy chart: keep.
- Black/empty, fade, blur, and transition: reject.

Tests also cover rapid cuts, no scene changes, never-stable animation, same-second cuts, ffmpeg nonzero exit, and selected/rejected manifest records. The public `research_video` test mutates a copy of the golden fixture; it does not edit `talk_benchmark.json`.

No LLM eval is warranted. One small deterministic ffmpeg clip is enough for integration; unit tests own interval math and scoring.

## Performance Review

No performance P1 exists for supported short videos.

- Cap probes per interval and per minute.
- Analyze a fixed 160x90 grid, at most 14,400 pixels per candidate.
- Reuse decoded/downsampled features for scoring and stability.
- Consider batched ffmpeg timestamp extraction only after correctness, if measured runtime warrants it.

Never gain speed by removing periodic coverage or silently skipping later Presentation Segments.

## Failure Modes

| Production failure | Test | Required handling | User outcome |
|---|---|---|---|
| Chart appears 2s after cut | 06:52/06:54 corpus | bounded probes rank settled frame | correct Evidence Frame |
| Next cut arrives early | rapid-cut fixture | guard before next boundary | no wrong-segment evidence |
| Gray full talking head passes low saturation | 06:52 corpus | face occupancy hard-drop | omitted, not mislabeled |
| Large face PIP plus text passes “only” rule | 07:30 corpus | strong penalty/ceiling | clean peer or explicit gap |
| Colorful GEX chart has high saturation | GEX corpus | structure can pass regardless of saturation | chart retained |
| ffmpeg fails | mocked nonzero exit | extraction error | never silent 0.0 fallback |
| No scene changes | no-cut clip | periodic probes | later material remains observable |
| Animation never stabilizes | moving clip/features | capped best eligible or gap | no hang or silent loss |
| Every candidate is rejected | public failure injection | unobserved window | G4 forces Partial Run |
| Two cuts share one second | focused integration | collision-free IDs | no overwritten evidence |

No listed failure remains silent without a planned test and handling path.

## NOT in Scope

- A new completeness gate or status producer.
- Pillow or ffmpeg inside the pure assurance core.
- OCR entailment, chart interpretation, or external truth verification.
- Manual replacement of the supplied pack's frames.
- Regenerating the full Desktop library.
- A hosted service, queue, database, UI, OpenCV, or general computer-vision framework.
- Rewriting the canonical fixture; failure injection mutates a copy.

## TODOS.md Updates

No deferred TODO is needed. Batched ffmpeg extraction may be reconsidered only after a benchmark proves capped probes too slow.

## Parallelization

Sequential implementation, no useful worktree split. Interval shapes, scoring, fixtures, and provenance share one selector contract.

## Implementation Tasks

- [ ] **T1 (P1, human: ~4h / CC: ~30min)** — frame selection — build interval-bounded post-cut and periodic probing.
  - Surfaced by: A1 and outside-voice P1.1
  - Files: `src/video_research/frame_adapter.py`, `tools/extract_evidence_frames.py`, focused tests
  - Verify: 06:52 selects 06:54; rapid cuts never cross boundaries
- [ ] **T2 (P1, human: ~1d / CC: ~60min)** — frame quality — enforce full-frame evidence and face-dominance policy.
  - Surfaced by: C1 and outside-voice P1.2
  - Files: adapter, labeled corpus, scoring tests
  - Verify: 0652/0730 fail policy; 0654/GEX pass
- [ ] **T3 (P1, human: ~4h / CC: ~30min)** — trust integration — fail closed and preserve versioned provenance.
  - Surfaced by: A2, C2, C3, and outside-voice P1.3
  - Files: adapter, tool, failure injection, manifest tests
  - Verify: no eligible material visual is Partial; ffmpeg failure is not fallback
- [ ] **T4 (P1, human: ~4h / CC: ~30min)** — regression corpus — cover all diagram branches.
  - Surfaced by: Test Review and outside-voice P1.4
  - Files: `tests/fixtures/evidence_frames/`, selector/tool tests
  - Verify: labeled corpus, `pytest`, and `ruff check .`
- [ ] **T5 (P2, human: ~30min / CC: ~5min)** — operability — collision-free IDs and bounded analysis.
  - Surfaced by: C4 and C5
  - Files: tool, adapter, tests
  - Verify: same-second and analysis-grid assertions

## Completion Summary

- Step 0: Scope Challenge — accepted at one impure adapter, one tool, focused tests/corpus, and dependency metadata
- Architecture Review: 2 P1 issues found and folded
- Code Quality Review: 3 P1 and 2 P2 issues found and folded
- Test Review: diagram produced; 18 gaps planned
- Performance Review: 0 P1 issues; bounded costs specified
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 0
- Failure modes: 0 unhandled critical gaps after four P1 requirements
- Outside voice: complete; four P1 requirements accepted
- Parallelization: 1 sequential lane
- Lake Score: 4/4 P1 recommendations chose the complete option

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not needed | Extraction bug fix |
| Outside Voice | Firstmate scout | Independent second opinion | 1 | complete | Four P1 requirements accepted |
| Eng Review | `/plan-eng-review` | Architecture & tests | 1 | clear | Four P1 requirements and supporting P2 work locked |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not needed | No UI change |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not needed | No workflow change |

**CROSS-MODEL:** Both reviews agree exact-cut sampling and saturation are defective. Outside voice expanded the initial fixed-delay idea into interval ranking, fail-closed provenance, and a labeled corpus.

**VERDICT:** ENG + OUTSIDE VOICE CLEARED. Implement P1.1-P1.4 before shipping.

NO UNRESOLVED DECISIONS
