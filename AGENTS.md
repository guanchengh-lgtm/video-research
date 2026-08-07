# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

## Build and test

```bash
pip install -e ".[dev]"    # Python 3.11+; the core package has no dependencies
pytest
ruff check .
```

## The one rule that matters

Run status has exactly one producer: `video_research.status.decide`. Nothing else
may decide whether a run is complete. It fails closed — `UNVERIFIED` is not a pass,
and a gate in `REQUIRED_GATES` that never reported degrades the run. If you add a
gate, add its id to `REQUIRED_GATES`, or it will silently not be enforced.

The acceptance criterion of this project is a negative: no run may be presented as
trusted-complete while a trust gate is unmet. `tests/test_status.py` proves it
exhaustively and `tests/test_failure_injection.py` proves it end to end. A change
that makes either weaker is a change to the product, not a refactor.

## Layering

`adapters` → `ports` → core (`timeline`, `claims`, `diagnostics`, `run`, `gates`,
`status`) → `views`. The core is pure: no I/O, no model calls, nothing
engine-specific. Anything impure enters through a Protocol in `ports.py`.
Rationale and what is deliberately deferred:
[`docs/plans/0001-assurance-core-implementation.md`](docs/plans/0001-assurance-core-implementation.md).

## Sharp edges

- **Timestamps are integer milliseconds.** A float timeline makes the coverage
  partition check report gaps that do not exist. Raw engine timestamps are kept as
  strings on `SourceSpan.raw_timestamp` for navigation only, never for arithmetic.
- **Diagnostic severity is looked up from `SEVERITY`, never passed in.** A caller
  that could choose its own severity would eventually demote a blocker to a warning.
- **Views must not read the clock or a dict's insertion order.** Every
  time-dependent value comes from the run record; re-rendering unchanged canonical
  artifacts must be byte-identical, and `tests/test_views.py` checks it.
- **All source-derived text is attacker-controlled** — transcripts, OCR, titles,
  external URLs. `views.render_report` escapes text and only linkifies `http`/
  `https` external references. Do not interpolate raw source text into HTML.
- **Canonical artifacts are versioned.** Bumping a shape means bumping
  `store.SCHEMA_VERSION` and widening `SUPPORTED_SCHEMA_VERSIONS`. Unknown versions
  are refused on read, never half-parsed.
- **Declared material units live once on the coverage manifest.**
  `coverage.json` → `material_units` is the recall oracle; G6 and the structural
  verifier both re-read it. Window `material_unit_ids` only locate units on the
  timeline.
- **Failure injection mutates a copy of `tests/fixtures/talk_benchmark.json`.**
  Changing that fixture changes every injection test. If a test needs different
  source material, add a fixture rather than editing the golden one.

## Domain language is binding

`CONTEXT.md` defines the vocabulary and the type names track it one for one.
Changing a domain term (a claim role, a status, an evidence relation) is a product
decision — raise it against `CONTEXT.md` rather than diverging in code.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
