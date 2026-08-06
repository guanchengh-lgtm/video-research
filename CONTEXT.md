# Video Research

Video Research produces trustworthy summaries of video sources while preserving the boundary between supported completeness and partial evidence.

## Language

**Support Envelope**:
The declared source conditions within which a run may claim trusted completeness.
_Avoid_: Universal support

**Trusted-Complete Run**:
A run inside the **Support Envelope** whose content capture, evidence traceability, automation, failure detection, and unattended-trust gates all pass.
_Avoid_: Perfect run, complete summary

**Partial Run**:
A run with useful output that cannot pass every trusted-completeness gate.
_Avoid_: Complete with warnings

**Failed Run**:
A run that cannot produce useful research output or establish minimum source coverage.
_Avoid_: Empty summary

**Speaker Attribution**:
The association of a source claim with either a source-established identity or a stable anonymous speaker label.
_Avoid_: Guessed identity

**Presentation Segment**:
A continuous source interval using one coherent way of presenting information.
_Avoid_: Whole-video format

**Validated Transcript**:
A timestamped speech record whose language, timing, speech coverage, and integrity are sufficient for research use.
_Avoid_: Available captions

**Fallback Transcript**:
A speech record derived from source audio when available captions cannot become a **Validated Transcript**.
_Avoid_: Best-effort captions

**Research Pack**:
The complete human-readable findings, structured claims, provenance, and source evidence produced by one run.
_Avoid_: Summary file

**Atomic Claim**:
One independently assessable assertion, demonstration, inference, or externally verified fact.
_Avoid_: Summary bullet

**Evidence Reference**:
A precise source location that supports, contradicts, or qualifies an **Atomic Claim**.
_Avoid_: General citation

**Source Assertion**:
An **Atomic Claim** made by a source speaker without any implication that it is true.
_Avoid_: Verified claim

**Visual Demonstration**:
An **Atomic Claim** describing an action or state directly observable in source visuals.
_Avoid_: Proof

**Agent Inference**:
An **Atomic Claim** derived from evidence but neither stated nor visibly demonstrated by the source.
_Avoid_: Source claim

**External Fact**:
An **Atomic Claim** assessed using evidence outside the source video.
_Avoid_: Video summary claim

**Evidence Relation**:
The declared way an **Evidence Reference** supports, contradicts, or qualifies an **Atomic Claim**.
_Avoid_: Citation proximity

**Coverage Window**:
A fixed source-timeline interval carrying an explicit speech and visual observation state.
_Avoid_: Sample timestamp

**Material Content Unit**:
An idea, demonstration, correction, caveat, numeric claim, or on-screen fact whose omission could change reader understanding or action.
_Avoid_: Highlight

**False Completeness**:
A run presented as trusted-complete despite an unmet trust gate or unobserved material evidence.
_Avoid_: Successful run with warnings

**Completeness Blocker**:
A detected condition that still permits a useful **Research Pack** but forbids trusted completeness.
_Avoid_: Warning

**Fatal Research Failure**:
A detected condition that prevents production of a useful **Research Pack**.
_Avoid_: Partial result

**Manual Rescue**:
A human correction, selection, or edit of intermediate research evidence required for a run to reach completion.
_Avoid_: Optional review

**Cold Rerun**:
An independent processing of the same source and configuration without reusing prior generated findings.
_Avoid_: Resume

## Relationships

- A run is evaluated against exactly one **Support Envelope**
- A run finishes as exactly one of **Trusted-Complete Run**, **Partial Run**, or **Failed Run**
- A **Partial Run** or **Failed Run** must never be presented as a **Trusted-Complete Run**
- A source contains one or more **Presentation Segments**
- A material claim involving multiple speakers requires reliable **Speaker Attribution**
- Failed caption validation requires a **Fallback Transcript**
- A run produces exactly one **Research Pack**
- A **Research Pack** contains zero or more **Atomic Claims**
- Every material **Atomic Claim** requires one or more **Evidence References**
- Every **Atomic Claim** has exactly one role: **Source Assertion**, **Visual Demonstration**, **Agent Inference**, or **External Fact**
- Every **Evidence Reference** has exactly one **Evidence Relation** to its **Atomic Claim**
- A source timeline is partitioned into contiguous **Coverage Windows**
- Every **Material Content Unit** must appear in a **Trusted-Complete Run**
- A **Completeness Blocker** produces a **Partial Run**
- A **Fatal Research Failure** produces a **Failed Run**
- **False Completeness** is never permitted
- A **Trusted-Complete Run** never depends on **Manual Rescue**
- A **Cold Rerun** creates a distinct run even when its source and configuration match an earlier run

## Example dialogue

> **Developer:** "Transcript coverage is complete, but the final four minutes have no visual evidence. Is this a **Trusted-Complete Run**?"
> **Domain expert:** "No. It may be a **Partial Run**; missing visual coverage prevents trusted completeness."

## Flagged ambiguities

- "10/10" could mean literal perfection or operational trust — resolved: it means a **Trusted-Complete Run** within an explicit **Support Envelope**.
- "Any speaker count" could imply guessed identities — resolved: speaker count has no fixed cap, but material attribution must remain reliable and identities must never be guessed.
- "Mixed format" could imply one whole-video classification — resolved: presentation mode is classified per **Presentation Segment**.
- "Captions available" could imply transcript trust — resolved: captions are candidate evidence until they become a **Validated Transcript**.
- "Content coverage" could mean periodic sampling alone — resolved: deterministic **Coverage Window** accounting and benchmark recall of **Material Content Units** are both required.
- "Demonstrated" could imply proven true — resolved: a **Visual Demonstration** records what appears in the video, while truth assessment belongs to a separate **External Fact**.
- "Warning" could hide degraded trust — resolved: only a condition proven harmless to every trust gate may remain a warning; otherwise it is a **Completeness Blocker** or **Fatal Research Failure**.
- "Automated" could mean only extraction is scripted — resolved: trusted automation covers the complete run and permits no **Manual Rescue**.
- "Reproducible" could require identical generative wording — resolved: rerender and resume preserve artifacts exactly, while a **Cold Rerun** must preserve evidence integrity and materially equivalent findings rather than identical prose.
