# GitHub scan: reusable video-summary skills and engines

Checked: 2026-08-06

## Conclusion

Do not rebuild extraction core. Trial `mcp-video-analyzer` as extraction/runtime engine. Borrow focused-rerun and skill-packaging patterns from `claude-video`. Keep local work concentrated on assurance: support envelope, coverage manifest, atomic claim–evidence ledger, severity gates, independent verification, and trusted-complete/partial/failed status.

No inspected candidate supplies complete unattended-trust workflow.

## Candidate comparison

| Candidate | Strongest use | Reusable strengths | Missing for this project | Recommendation |
|---|---|---|---|---|
| [`mcp-video-analyzer`](https://github.com/guimatheus92/mcp-video-analyzer) | Extraction engine | Transcript, frames, OCR, metadata, annotated timeline, dense/static fallback, focused moment and burst extraction, dedup, warnings, caching, sidecars, unit/E2E/smoke tests; MIT | No coverage manifest, atomic claim roles, completeness gate, verifier, or layered research pack. Partial failures intentionally degrade to warnings. | Trial runtime |
| [`claude-video` `/watch`](https://github.com/bradautomates/claude-video) | Codex-ready skill UX | Native-caption/Whisper chain, scene/keyframe/uniform modes, transcript-cue frames, focused reruns, token budgets, preflight, bundled scripts and tests; MIT; `.codex-plugin` manifest | No OCR, machine-readable timeline, claim ledger, completeness verifier. Sparse by default for long videos. | Borrow skill packaging and rerun patterns |
| [`steipete/summarize`](https://github.com/steipete/summarize) | Mature general CLI | Stable JSON envelope, provider chain, transcript diagnostics, OCR/slides, cache, diarization options, many inputs, extensive tests; MIT | Generic summarizer, large product surface, Node 24+, no evidence assurance or independent verification | Use released CLI only if broad URL/file summarization becomes goal |
| [`video-lens`](https://github.com/kar2phi/video-lens) | Polished transcript report | Full-transcript rule, chapter outline, explicit partial-range disclosure, reusable HTML report; MIT | Transcript-centric; no general visual evidence, claim ledger, coverage gate, or verifier | Borrow report/presentation ideas |
| [`video-summary`](https://github.com/hych0317/skill-video-summary) | Long transcript coverage | Ten-minute chunk manifest, per-window evidence notes, coverage ledger, layered long-form output | Hardcoded private runtime paths, no license, ASR-only, no visual capture or verifier | Pattern borrow only |
| [`youtube-transcriber`](https://github.com/lifesized/youtube-transcriber) | Persistent transcript library | Local Whisper, optional diarization, queue, SQLite, duplicate detection, MCP/skill surfaces | AGPL-3.0; transcript-only for summary; service/UI complexity | Defer |

## Best composition

```text
mcp-video-analyzer
  -> transcript + frames + OCR + timeline + warnings

borrow from claude-video
  -> focused reruns + transcript-cue frames + token budgets + Codex skill UX

borrow from video-lens / video-summary
  -> layered report + long-form coverage ledger

add locally
  -> support-envelope validation
  -> coverage-window manifest
  -> atomic claim/evidence schema
  -> severity-based warning gate
  -> independent cold verifier
  -> trusted-complete / partial / failed status
  -> canonical structured output + generated summary/report views
```

Estimated avoided reinvention: roughly 70–80% of extraction/runtime work. Remaining 20–30% is project-defining assurance layer.

## Important integration risks

- `mcp-video-analyzer` merges timeline events within two seconds. Useful navigation; insufficient as exact evidence alignment without preserving raw source timestamps.
- Its scene fallback activates when scene extraction yields zero frames. It does not prove every static-scroll interval was captured. Local coverage windows still needed.
- Its graceful degradation should not map directly to `Trusted-Complete Run`; material warnings must become completeness blockers.
- `claude-video` default capped scans become sparse for long videos and require agent image reads, increasing context cost.
- `claude-video` first-run setup may install packages and write API-key configuration. Review scripts and sandbox before trial.
- `steipete/summarize` has broad capability but high dependency/product surface. Avoid forking.
- Smaller community skills often lack tests, licenses, timestamp preservation, or portable paths. Borrow patterns only.

## Trial acceptance gate

Before adopting any engine:

1. Pin exact version/commit.
2. Review dependency and outbound-data behavior.
3. Run same 5–10-video benchmark corpus against current extractor and candidate.
4. Measure material-content recall, transcript integrity, visual-window coverage, OCR usefulness, runtime, and cost.
5. Inject caption, Whisper, OCR, frame, cache, and late-video failures.
6. Confirm material warnings force `Partial Run` or `Failed Run`.
7. Confirm canonical structured artifacts can generate `summary.md` and `report.html` without separate authoring.

## Source coverage

- `mcp-video-analyzer`: **read partially** — portable skill, package manifest, frame extractor, OCR processor, annotated timeline, sidecar cache, test tree, E2E partial-result test, GitHub activity/license metadata.
- `claude-video`: **read partially** — full skill, Codex plugin manifest, repo/test tree, GitHub activity/license metadata.
- `steipete/summarize`: **read partially** — full skill, package manifest, repo/test tree, GitHub activity/license metadata.
- `video-lens`: **read partially** — skill and GitHub activity/license metadata.
- `video-summary`: **read fully for relevant skill contract** — full `SKILL.md`, GitHub activity/license metadata.
- `youtube-transcriber`: **read partially** — full Claude skill and GitHub activity/license metadata.
- Secondary evidence used for recommendation: none.
- Missing validation: local installation/sandbox review and benchmark corpus run.

## Decision

- `Decision Type: trial_only` — `mcp-video-analyzer` as engine.
- `Decision Type: pattern_borrow` — `claude-video`, `video-lens`, and `video-summary` patterns.
- `Decision Type: defer` — `steipete/summarize` and `youtube-transcriber` unless scope broadens.
- `Decision: provisional` until local compatibility and benchmark tests pass.
