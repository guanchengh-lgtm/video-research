# Video Research

Evidence-backed video summaries for videos you want to understand without
watching. Every material claim cites a timestamped source location, and every
run ends with an honest verdict rather than a polished one.

## Status

The assurance core is implemented and tested. Live video ingestion is not.

A run today reads a **deterministic extracted-source fixture**, builds the
canonical claim ledger and coverage manifest, runs the completeness gates and an
independent verifier, and generates `summary.md` and `report.html`. Replacing
the fixture with a real extraction engine means writing one adapter against
`ExtractionEngine`; the assurance layer does not change. See
[the implementation plan](docs/plans/0001-assurance-core-implementation.md) for
what is deferred and why.

## Install

```bash
pip install -e ".[dev]"
```

Python 3.11 or newer. The core has no dependencies.

## Use

```bash
video-research --fixture tests/fixtures/talk_benchmark.json --out ./pack
```

Exit code is the verdict: `0` trusted-complete, `1` partial, `2` failed, `3` the
tool itself broke.

```python
from video_research import research_video
from video_research.adapters import (
    FixtureClaimExtractor, FixtureExtractionEngine, StructuralVerifier,
)

pack = research_video(
    "fixture://talk-benchmark",
    engine=FixtureExtractionEngine("tests/fixtures/talk_benchmark.json"),
    claim_extractor=FixtureClaimExtractor("tests/fixtures/talk_benchmark.json"),
    verifier=StructuralVerifier(),
    output_dir="./pack",
)
print(pack.status, pack.run.status_reasons)
```

## What one run produces

A **Research Pack**: three canonical artifacts plus two generated views.

| File | Layer |
|------|-------|
| `run.json` | canonical — provenance, envelope, gates, verifier checks, diagnostics, status |
| `coverage.json` | canonical — observed timeline windows and the material-unit oracle |
| `claims.json` | canonical — atomic claims, roles, evidence edges |
| `summary.md` | generated view |
| `report.html` | generated view |

The views are pure functions of the canonical artifacts and are regenerated, not
authored ([ADR 0001](docs/adr/0001-structured-source-generated-research-views.md)).
Editing them by hand does not change what the run found.

## The verdict

Each run ends as exactly one of:

- **Trusted-Complete Run** — every gate and every verifier check passed inside
  the declared **Support Envelope**.
- **Partial Run** — useful research, with every blocker named.
- **Failed Run** — minimum source coverage could not be established.

Status has one producer, `video_research.status.decide`, and it fails closed. A
check that could not be decided reports `UNVERIFIED`, which is not a pass, so a
run nobody could verify lands partial instead of falsely complete. A gate that
is never wired up degrades the run rather than silently widening what counts as
trusted.

This is why an arbitrary video cannot reach trusted-complete today: without
declared material content units there is no oracle for material recall, so that
gate abstains and the run is partial. That is the honest answer, not a gap.

## Develop

```bash
pytest         # 166 tests
ruff check .
```

The primary test seam is the public entry point. Tests assert observable
research-pack behaviour — artifacts, evidence, coverage, status, diagnostics —
not internal structure. `tests/test_failure_injection.py` damages a copy of the
golden fixture sixteen different ways and asserts no injected material failure
ever produces a trusted-complete run.

## Read next

- [Product specification](docs/specs/video-summary-skill.md)
- [Implementation plan and engineering decisions](docs/plans/0001-assurance-core-implementation.md)
- [Domain language](CONTEXT.md)
- [Architecture decision](docs/adr/0001-structured-source-generated-research-views.md)
- [Reusable-tool research](research/github-video-summary-skills.md)

Downloaded video, transcript, frame, and generated run artifacts are
intentionally excluded from Git.
