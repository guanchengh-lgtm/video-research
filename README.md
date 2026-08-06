# Video Research

Evidence-backed video summaries for videos you want to understand without watching.

This project is currently specified, not yet implemented as a reusable skill. The intended workflow extracts transcript and visual evidence, builds a complete timestamped summary, verifies claim support and content coverage in a separate pass, and reports an honest `trusted-complete`, `partial`, or `failed` result.

See:

- [Product specification](docs/specs/video-summary-skill.md)
- [Domain language](CONTEXT.md)
- [Architecture decision](docs/adr/0001-structured-source-generated-research-views.md)
- [Reusable-tool research](research/github-video-summary-skills.md)

Downloaded video, transcript, frame, and generated run artifacts are intentionally excluded from Git.
