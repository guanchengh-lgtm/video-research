# Build an evidence-backed, independently verified video-summary skill

## Problem Statement

People often want accurate, complete understanding of a YouTube video without spending time watching it. Built-in AI summaries frequently omit caveats, examples, corrections, demonstrations, or late-video material, while presenting a polished result that gives no honest indication of missing coverage.

A useful replacement must do more than condense a transcript. It must capture speech and material visual information, distinguish what the source says from what is actually verified, attach precise evidence to material claims, run an independent completeness and support check, and refuse to label degraded output complete.

## Solution

Create a reusable video-summary skill that accepts a YouTube URL and produces one **Research Pack** from canonical structured artifacts. It uses an existing video-analysis engine for transcript, frames, OCR, metadata, and timeline extraction, then adds the project-specific assurance layer.

The skill will:

1. Declare whether the video is inside its **Support Envelope**.
2. Build a **Validated Transcript**, using a **Fallback Transcript** when necessary.
3. Partition the full timeline into contiguous **Coverage Windows** and capture material speech and visual content.
4. Identify **Material Content Units**, including important ideas, examples, demonstrations, qualifications, corrections, numbers, and conclusions.
5. Express each material summary statement as an **Atomic Claim** with one or more timestamped **Evidence References**.
6. Label each claim as a **Source Assertion**, **Visual Demonstration**, **Agent Inference**, or **External Fact**, preventing a speaker's statement from being presented as independently proven truth.
7. Generate a readable timestamped summary from canonical structured artifacts.
8. Run an independent cold-context verifier that checks coverage, evidence support, omitted material, contradictions, qualifications, and proposed run status.
9. Finish as exactly one **Trusted-Complete Run**, **Partial Run**, or **Failed Run**, with explicit reasons for any degraded result.

Accuracy has two distinct meanings:

- Source fidelity is mandatory. Material summary claims must accurately represent and cite what the video says or visibly demonstrates.
- External truth checking is optional and explicit. When enabled, selected factual claims are checked against primary external sources and recorded as **External Facts** with references. Without external evidence, claims remain attributed **Source Assertions**, not verified facts.

The five quality areas reach score 10 when all defined gates pass inside the declared **Support Envelope**:

- Content capture: full timeline accounted for; every benchmark **Material Content Unit** represented; speech and material visuals included.
- Evidence traceability: every material **Atomic Claim** has precise supporting, contradicting, or qualifying **Evidence References**.
- Automation: one invocation creates the complete **Research Pack** without **Manual Rescue**.
- Failure detection: injected and natural evidence failures never produce **False Completeness**.
- Unattended trust: independent verifier passes, canonical artifacts validate, and the final status follows deterministic gates.

Score 10 means operationally trusted within a declared **Support Envelope**. It does not mean universal support, perfect transcription, or proof that every source speaker is truthful.

## User Stories

1. As a viewer, I want to provide a YouTube URL, so that I can understand the video without watching it.
2. As a viewer, I want one clear summary, so that I do not need to inspect raw extraction artifacts.
3. As a viewer, I want the summary to cover the entire video, so that late sections are not silently omitted.
4. As a viewer, I want important caveats and corrections preserved, so that compression does not change the source's meaning.
5. As a viewer, I want important examples and demonstrations preserved, so that I understand how advice works in practice.
6. As a viewer, I want material numbers, names, steps, and conclusions preserved, so that actionable details survive summarization.
7. As a viewer, I want chapters or logical sections with timestamps, so that I can navigate directly to relevant moments.
8. As a viewer, I want each material claim linked to precise evidence, so that I can inspect the source quickly.
9. As a viewer, I want transcript evidence cited by timestamp, so that I can verify what a speaker said.
10. As a viewer, I want visual claims backed by frames or OCR, so that on-screen information is not invented from speech alone.
11. As a viewer, I want the summary to distinguish speaker claims from verified facts, so that confident delivery is not mistaken for truth.
12. As a viewer, I want inferences labeled as inferences, so that I can separate interpretation from source content.
13. As a viewer, I want contradictory or qualifying evidence shown, so that the summary does not cherry-pick support.
14. As a viewer, I want optional external fact checking, so that important real-world claims can be assessed beyond the video itself.
15. As a viewer, I want external fact checks to cite primary sources, so that I can evaluate verification quality.
16. As a viewer, I want unverified factual statements attributed to the source, so that they are never presented as established truth.
17. As a viewer, I want a visible complete, partial, or failed status, so that I know how much trust to place in the output.
18. As a viewer, I want partial summaries to remain available, so that useful findings are not discarded when some evidence is missing.
19. As a viewer, I want partial summaries to identify exact gaps, so that I know what remains uncertain or unseen.
20. As a viewer, I want failed runs to explain the failure, so that I can retry or choose another source.
21. As a viewer, I want missing or truncated captions detected, so that an incomplete transcript cannot create a complete status.
22. As a viewer, I want automatic speech recognition used when captions are unusable, so that more videos remain researchable.
23. As a viewer, I want transcript timing and language validated, so that available captions are not trusted blindly.
24. As a viewer, I want visual coverage across the full timeline, so that slides, code, UI, and silent demonstrations are not missed.
25. As a viewer, I want static or slowly changing screen content handled, so that scene-change detection does not create invisible gaps.
26. As a viewer, I want speaker identity left unknown when evidence is insufficient, so that the skill never guesses attribution.
27. As a viewer, I want an independent second pass, so that omissions and weak evidence can be caught before delivery.
28. As a viewer, I want the verifier to review source evidence rather than trust the draft summary, so that verification is meaningful.
29. As a viewer, I want the verifier's findings recorded, so that the final status is explainable.
30. As a viewer, I want one reusable skill invocation, so that the same workflow works consistently across videos.
31. As a viewer, I want generated output to be reproducible from canonical artifacts, so that human-readable files do not drift from evidence.
32. As a viewer, I want reruns to preserve provenance, so that results from different runs are not accidentally mixed.
33. As a viewer, I want extraction warnings classified by impact, so that harmless diagnostics do not hide completeness blockers.
34. As a viewer, I want no manual frame selection required for a complete result, so that unattended status remains honest.
35. As a developer, I want the extraction engine isolated behind one adapter, so that it can be replaced without rewriting the assurance layer.
36. As a developer, I want versioned canonical schemas, so that generated views and older Research Packs remain understandable.
37. As a developer, I want deterministic status rules, so that polished prose cannot override evidence failures.
38. As a developer, I want focused re-extraction of weak intervals, so that the system can repair gaps before declaring a partial result.
39. As a developer, I want cached raw extraction separated from canonical findings, so that retries are efficient without confusing provenance.
40. As a developer, I want benchmark fixtures representing different video formats, so that completeness claims are tested across realistic sources.
41. As a developer, I want injected caption, ASR, OCR, frame, cache, and late-video failures, so that **False Completeness** is actively tested.
42. As a developer, I want tests at the public skill boundary, so that refactoring internals does not invalidate useful tests.
43. As a developer, I want exact engine version and outbound-data behavior recorded, so that runs are reproducible and privacy behavior is visible.
44. As a developer, I want the reusable skill to include setup checks and actionable errors, so that installation problems are easy to resolve.
45. As a developer, I want output sizes and model context use bounded, so that long videos remain practical without silent content loss.

## Implementation Decisions

- Initial source scope is YouTube URLs. Unsupported, inaccessible, live, private, or protected sources remain outside the initial **Support Envelope**.
- The project will not rebuild general video extraction. It will trial `mcp-video-analyzer` behind a narrow adapter for transcript, frames, OCR, metadata, timeline, and focused re-extraction.
- Engine selection remains replaceable. Canonical project interfaces will not expose engine-specific output shapes.
- Raw engine artifacts, canonical research artifacts, and generated human views remain separate layers.
- One canonical run record stores source metadata, engine identity and version, **Support Envelope** result, duration, transcript provenance, **Coverage Windows**, diagnostics, verifier outcome, and final status.
- One canonical claim ledger stores each **Atomic Claim**, its role, materiality, evidence relations, precise source locations, and optional external verification.
- **Evidence References** preserve raw timestamps. A merged or rounded navigation timeline cannot replace exact evidence locations.
- Evidence relations are explicit: supports, contradicts, or qualifies.
- **Coverage Windows** partition the whole source timeline without gaps. Each window records speech coverage, visual observation state, extraction method, and detected **Material Content Units**.
- The system first attempts native captions, validates them, and uses ASR as a **Fallback Transcript** when required.
- Visual extraction combines scene changes with periodic or focused sampling. Zero-frame fallback alone is insufficient because static scrolling or silent demonstrations may still contain material content.
- OCR is evidence assistance, not unquestioned truth. OCR text retains frame and timestamp provenance and may trigger focused re-extraction when confidence is weak.
- Draft generation works from canonical evidence, not directly from an unconstrained prompt over the video URL.
- Human-readable `summary.md` and `report.html` are generated views of canonical data. They are never independently authored sources of truth.
- The summary begins with final run status and concise coverage disclosure. **Partial Runs** list every **Completeness Blocker**; **Failed Runs** state each **Fatal Research Failure**.
- **Trusted-Complete Run** requires successful transcript validation or fallback, contiguous timeline accounting, captured material speech and visuals, evidence for every material claim, zero completeness blockers, successful canonical validation, independent verifier pass, and no **Manual Rescue**.
- **Partial Run** contains useful research but has one or more completeness blockers, unresolved material evidence gaps, failed verifier checks, or manual rescue.
- **Failed Run** cannot establish minimum source coverage or produce useful supported findings.
- Diagnostic severity remains small and deterministic: informational diagnostics do not change status; completeness blockers force partial; fatal research failures force failed.
- Independent verification runs in cold context and receives canonical evidence plus the draft outputs, but not the draft generator's hidden reasoning. It checks source coverage, material-unit recall, evidence entailment, contradiction handling, qualification handling, visual support, and proposed status.
- Verifier disagreement cannot be hidden. Unresolved material findings force a **Partial Run**.
- External fact-check mode is optional. It uses primary sources when available, records external references separately from video evidence, and never upgrades a **Source Assertion** to an **External Fact** without evidence.
- Focused re-extraction may repair weak intervals before final status. Every repair remains recorded in run provenance.
- A **Cold Rerun** creates a distinct run and must not reuse prior generated findings. Cached source media or raw extraction may be reused only when integrity and provenance checks pass.
- The final deliverable is a portable Codex-compatible skill with concise setup, one main invocation, bounded dependencies, and scripts for deterministic processing where appropriate.
- Skill output defaults to a layered summary: executive overview, chapter-level detail, important claims and evidence, caveats or contradictions, verification notes, and coverage/status disclosure.
- Long videos may use chunked processing, but chunk boundaries must overlap or otherwise preserve cross-boundary context, and full-video reconciliation remains mandatory.
- Adoption of `mcp-video-analyzer` is provisional until a local compatibility review and benchmark corpus pass. Patterns may be borrowed from `claude-video`, `video-lens`, and `video-summary` without importing their unrelated product surface.

## Testing Decisions

- Primary test seam is one end-to-end public skill invocation. Tests provide a fixed video fixture or deterministic extracted-source fixture, invoke the same entry point a user invokes, and assert only observable **Research Pack** behavior.
- A good test asserts outputs, evidence, coverage, status, and diagnostics. It does not assert private helper calls, prompt wording, internal class structure, or a specific extraction engine's private format.
- The end-to-end contract verifies canonical schema validity, full timeline accounting, material-claim citations, generated-view consistency, verifier outcome, and final run status.
- Golden fixtures annotate expected **Material Content Units** and source locations. Content-capture score 10 requires every material unit in the benchmark fixture to appear in canonical findings and the generated summary.
- Evidence-traceability score 10 requires every material claim to have at least one valid precise **Evidence Reference**, with correct claim role and evidence relation.
- Automation score 10 requires a clean one-command run to produce the full **Research Pack** without manual edits or frame selection.
- Failure-detection score 10 requires every injected material failure to produce partial or failed status, with zero **False Completeness** results across the benchmark suite.
- Unattended-trust score 10 requires independent verifier success, canonical validation, generated-view consistency, and no manual rescue.
- Benchmark corpus should include talk-only video, slide presentation, code or UI screencast, mixed speaker-plus-screen video, static scrolling, weak captions, no captions, multiple speakers, long video, and material content near the end.
- Failure injection covers truncated captions, wrong-language captions, timestamp drift, ASR failure, missing final windows, sparse scene frames, OCR failure, corrupt cache, duplicate evidence, unsupported source, and verifier disagreement.
- Tests verify a source assertion remains attributed unless external evidence exists.
- Tests verify external fact-check mode records primary-source references and clearly reports unverified or contradicted claims.
- Tests verify a useful but incomplete result is preserved as a **Partial Run** with exact blockers.
- Tests verify fatal extraction or minimum-coverage failure produces no misleading summary and ends as a **Failed Run**.
- Tests verify generated `summary.md` and `report.html` contain materially equivalent claims and status because both derive from canonical artifacts.
- Tests verify rerendering from unchanged canonical artifacts is deterministic.
- Tests verify a **Cold Rerun** remains distinct and does not silently inherit prior generated conclusions.
- Existing extractor output and the previously researched video provide prior art for fixture shape and evidence manifests, but handpicked frames cannot satisfy unattended-completeness acceptance.
- Engine trial compares current extraction with candidate extraction over the same five-to-ten-video corpus, measuring material-unit recall, transcript integrity, visual-window coverage, OCR usefulness, runtime, and cost.
- Acceptance requires all five quality areas to reach score 10 on supported benchmark fixtures. Any known false-complete case blocks release of the reusable skill.

## Out of Scope

- Universal support for every video platform, live stream, private video, DRM-protected source, or inaccessible source.
- Guaranteeing that every statement made by a video speaker is true.
- Mandatory external web research for every source assertion.
- Guessing speaker identities or repairing ambiguous attribution with unsupported assumptions.
- Producing a video-quality rating, creator reputation score, sentiment analysis, or recommendation algorithm.
- Building a hosted service, queue, database-backed library, browser UI, or collaborative review system in the first version.
- Replacing mature media download, ASR, OCR, or frame-extraction engines with locally rebuilt equivalents.
- Literal perfection outside the declared **Support Envelope**.
- Enterprise compliance, high-stakes medical, legal, or financial verification guarantees.

## Further Notes

Atomic claim/evidence schema enables verification and references, but does not by itself prove external truth. Its immediate value is preventing unsupported summary prose and preserving exact source traceability. Claim roles are essential: “the speaker claims X,” “the video visibly demonstrates X,” “the agent infers X,” and “external primary evidence supports X” are different statements.

Independent verification primarily protects against incomplete or unsupported summaries. Optional external fact checking addresses truth beyond source fidelity.

Reusable-engine research found no existing skill that supplies the complete assurance layer. Current recommendation:

- `mcp-video-analyzer`: trial only as extraction engine.
- `claude-video`, `video-lens`, and `video-summary`: borrow selected packaging, focused-rerun, report, and coverage patterns.
- `steipete/summarize` and `youtube-transcriber`: defer unless product scope broadens.

Decision remains provisional until local compatibility and benchmark testing passes.
