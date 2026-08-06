"""Generated human views of the canonical artifacts.

Both views are pure functions of a :class:`ResearchPack`. They author nothing:
every claim, status, and reason they show came from canonical data, which is
what keeps ``summary.md`` and ``report.html`` materially equivalent (ADR 0001).

Nothing here reads the clock. Every time-dependent value comes from the run
record, so re-rendering unchanged artifacts is byte-identical.

Transcript text, OCR text, and source titles are attacker-controlled. All of it
is escaped on the way into HTML.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from .claims import AtomicClaim, ClaimRole, EvidenceRelation
from .run import ResearchPack, RunStatus

_STATUS_HEADLINE = {
    RunStatus.TRUSTED_COMPLETE: "Trusted-Complete Run",
    RunStatus.PARTIAL: "Partial Run",
    RunStatus.FAILED: "Failed Run",
}

_STATUS_BLURB = {
    RunStatus.TRUSTED_COMPLETE: (
        "Every completeness gate and every independent verifier check passed "
        "inside the declared support envelope."
    ),
    RunStatus.PARTIAL: (
        "This research is useful but incomplete. Every blocker is listed below. "
        "Do not read it as full coverage of the source."
    ),
    RunStatus.FAILED: (
        "This run could not establish minimum source coverage. "
        "The findings below, if any, are not a summary of the video."
    ),
}

_ROLE_LABEL = {
    ClaimRole.SOURCE_ASSERTION: "the speaker claims",
    ClaimRole.VISUAL_DEMONSTRATION: "the video shows",
    ClaimRole.AGENT_INFERENCE: "inferred",
    ClaimRole.EXTERNAL_FACT: "checked against outside sources",
}

_RELATION_LABEL = {
    EvidenceRelation.SUPPORTS: "supports",
    EvidenceRelation.CONTRADICTS: "contradicts",
    EvidenceRelation.QUALIFIES: "qualifies",
}


def _claim_line(claim: AtomicClaim) -> str:
    marker = "**material**" if claim.material else "supporting"
    speaker = f" ({claim.speaker_label})" if claim.speaker_label else ""
    return f"{_ROLE_LABEL[claim.role]}{speaker} — {claim.statement} [{marker}]"


def _safe_external_url(url: str) -> str | None:
    """Return a linkable web URL, refusing active or ambiguous URI schemes."""
    if any(ord(character) < 0x20 for character in url):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _markdown_destination(value: str) -> str:
    return value.replace("\\", "%5C").replace("(", "%28").replace(")", "%29")


def render_summary(pack: ResearchPack) -> str:
    """Render ``summary.md`` from canonical data.

    The status and its reasons come first. A reader who stops after the first
    screen must already know how much of the video this covers.
    """
    run = pack.run
    out: list[str] = []

    out.append(f"# {run.source.title or run.source.source_ref}")
    out.append("")
    out.append(f"**Status: {_STATUS_HEADLINE[run.status]}**")
    out.append("")
    out.append(_STATUS_BLURB[run.status])
    out.append("")

    label = "Fatal research failures" if run.status is RunStatus.FAILED else "Completeness blockers"
    if run.status is not RunStatus.TRUSTED_COMPLETE:
        out.append(f"## {label}")
        out.append("")
        for reason in run.status_reasons:
            out.append(f"- {reason}")
        out.append("")

    out.append("## Coverage")
    out.append("")
    out.append(f"- Source runs {pack.coverage.duration_ms} ms")
    out.append(f"- Timeline partitioned into {len(pack.coverage.windows)} coverage window(s)")
    language = run.transcript_language or "unknown"
    out.append(f"- Transcript: {run.transcript_kind.value} ({language})")
    out.append(
        f"- Engine: {run.engine.name} {run.engine.version} (outbound data: "
        f"{run.engine.outbound_data})"
    )
    out.append("")

    material = pack.ledger.material_claims()
    out.append("## Claims and evidence")
    out.append("")
    if not material:
        out.append("_No material claims were established._")
        out.append("")
    for claim in material:
        out.append(f"### {claim.claim_id}")
        out.append("")
        out.append(_claim_line(claim))
        out.append("")
        for ref in pack.ledger.evidence_for(claim.claim_id):
            note = f" — {ref.note}" if ref.note else ""
            out.append(
                f"- {_RELATION_LABEL[ref.relation]}: {ref.span.label()}"
                f"{' `' + ref.span.artifact_id + '`' if ref.span.artifact_id else ''}{note}"
            )
        for ext in pack.ledger.external_for(claim.claim_id):
            safe_url = _safe_external_url(ext.url)
            if safe_url is None:
                out.append(
                    f"- {_RELATION_LABEL[ext.relation]} (external): "
                    f"{_markdown_text(ext.title)} (unsafe URL omitted)"
                )
            else:
                out.append(
                    f"- {_RELATION_LABEL[ext.relation]} (external): "
                    f"[{_markdown_text(ext.title)}]({_markdown_destination(safe_url)})"
                )
        out.append("")

    out.append("## Verification")
    out.append("")
    for gate in run.gates:
        out.append(f"- {gate.gate_id} {gate.name}: **{gate.outcome}** — {gate.detail}")
    for check in run.verifier_checks:
        out.append(f"- verifier `{check.name}`: **{check.outcome}** — {check.detail}")
    out.append("")

    if run.diagnostics:
        out.append("## Diagnostics")
        out.append("")
        for diagnostic in run.diagnostics:
            out.append(f"- [{diagnostic.severity.value}] {diagnostic.describe()}")
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        f"Run `{run.run_id}` started {run.created_at}, envelope `{run.envelope.envelope_id}`."
    )
    out.append("Generated from canonical artifacts. Do not edit by hand.")
    out.append("")
    return "\n".join(out)


def render_report(pack: ResearchPack) -> str:
    """Render ``report.html`` from the same canonical data as the summary."""
    run = pack.run
    e = escape

    rows: list[str] = []
    for claim in pack.ledger.material_claims():
        evidence = "".join(
            f"<li>{e(_RELATION_LABEL[ref.relation])}: {e(ref.span.label())}"
            f"{' <code>' + e(ref.span.artifact_id) + '</code>' if ref.span.artifact_id else ''}"
            f"</li>"
            for ref in pack.ledger.evidence_for(claim.claim_id)
        )
        for ext in pack.ledger.external_for(claim.claim_id):
            safe_url = _safe_external_url(ext.url)
            label = f"{e(_RELATION_LABEL[ext.relation])} (external): "
            if safe_url is None:
                evidence += f"<li>{label}{e(ext.title)} (unsafe URL omitted)</li>"
            else:
                evidence += (
                    f'<li>{label}<a href="{e(safe_url)}" '
                    f'rel="nofollow noopener">{e(ext.title)}</a></li>'
                )
        rows.append(
            f"<tr><td><code>{e(claim.claim_id)}</code></td>"
            f"<td>{e(_ROLE_LABEL[claim.role])}</td>"
            f"<td>{e(claim.statement)}</td>"
            f"<td><ul>{evidence or '<li>none</li>'}</ul></td></tr>"
        )

    reasons = "".join(f"<li>{e(reason)}</li>" for reason in run.status_reasons)
    gates = "".join(
        f"<tr><td>{e(g.gate_id)}</td><td>{e(g.name)}</td>"
        f"<td>{e(g.outcome)}</td><td>{e(g.detail)}</td></tr>"
        for g in run.gates
    )
    checks = "".join(
        f"<tr><td>verifier</td><td>{e(c.name)}</td><td>{e(c.outcome)}</td>"
        f"<td>{e(c.detail)}</td></tr>"
        for c in run.verifier_checks
    )
    diagnostics = "".join(
        f"<li>[{e(d.severity.value)}] {e(d.describe())}</li>" for d in run.diagnostics
    )

    title = e(run.source.title or run.source.source_ref)
    status = e(_STATUS_HEADLINE[run.status])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
 body {{ font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; }}
 .status {{ padding: .75rem 1rem; border-left: .25rem solid currentColor; }}
 .status-{run.status.value} {{ background: #f4f4f5; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border: 1px solid #ddd; padding: .4rem .6rem; text-align: left; vertical-align: top; }}
 ul {{ margin: 0; padding-left: 1.1rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="status status-{run.status.value}">
<strong>Status: {status}</strong>
<p>{e(_STATUS_BLURB[run.status])}</p>
{f"<ul>{reasons}</ul>" if reasons else ""}
</div>
<h2>Coverage</h2>
<ul>
<li>Source runs {pack.coverage.duration_ms} ms</li>
<li>{len(pack.coverage.windows)} coverage window(s)</li>
<li>Transcript: {e(run.transcript_kind.value)} ({e(run.transcript_language or "unknown")})</li>
<li>Engine: {e(run.engine.name)} {e(run.engine.version)}
    (outbound data: {e(run.engine.outbound_data)})</li>
</ul>
<h2>Claims and evidence</h2>
<table>
<tr><th>Claim</th><th>Role</th><th>Statement</th><th>Evidence</th></tr>
{"".join(rows) or "<tr><td colspan='4'>No material claims were established.</td></tr>"}
</table>
<h2>Verification</h2>
<table>
<tr><th>Gate</th><th>Name</th><th>Outcome</th><th>Detail</th></tr>
{gates}{checks}
</table>
{f"<h2>Diagnostics</h2><ul>{diagnostics}</ul>" if diagnostics else ""}
<hr>
<p>Run <code>{e(run.run_id)}</code> started {e(run.created_at)},
envelope <code>{e(run.envelope.envelope_id)}</code>.
Generated from canonical artifacts. Do not edit by hand.</p>
</body>
</html>
"""
