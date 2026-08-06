"""The single producer of run status.

Nothing else in this project may decide whether a run is complete. Concentrating
the decision here is what makes "no false completeness" provable rather than
hoped for: the property is a claim about one pure function, and a test can drive
every combination of its inputs.

The function fails closed. ``TRUSTED_COMPLETE`` is the fall-through, reachable
only when every gate and every verifier check explicitly passed. A gate added
later and never wired up reports ``UNVERIFIED``, which lands the run partial
instead of silently waving it through.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Diagnostic, blockers, fatals
from .gates import GateOutcome, GateResult
from .ports import CheckOutcome, VerifierReport
from .run import RunStatus

#: Every gate that must have reported before a run may be called complete.
#: A gate missing from the evidence is treated exactly like a gate that failed,
#: so wiring up a new gate and forgetting to call it degrades the run instead of
#: silently widening what counts as trusted.
REQUIRED_GATES: frozenset[str] = frozenset({"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"})


@dataclass(frozen=True)
class StatusDecision:
    """The status and every reason that produced it."""

    status: RunStatus
    reasons: tuple[str, ...] = ()

    @property
    def trusted(self) -> bool:
        return self.status is RunStatus.TRUSTED_COMPLETE


def decide(
    diagnostics: tuple[Diagnostic, ...],
    gate_results: tuple[GateResult, ...],
    verifier: VerifierReport,
    manual_rescue: bool = False,
) -> StatusDecision:
    """Reduce the evidence about a run to exactly one status.

    A fatal research failure outranks everything: a run that could not establish
    minimum coverage is failed, not partial, even if other gates passed.
    """
    fatal = fatals(diagnostics)
    if fatal:
        return StatusDecision(RunStatus.FAILED, tuple(d.describe() for d in fatal))

    reasons: list[str] = [d.describe() for d in blockers(diagnostics)]

    missing = sorted(REQUIRED_GATES - {r.gate_id for r in gate_results})
    if missing:
        reasons.append(f"required gate(s) never reported: {', '.join(missing)}")

    for result in gate_results:
        if result.diagnostic is not None:
            # The gate already spoke through its diagnostic, which is listed above.
            # Repeating it here would make one problem look like two.
            continue
        if result.outcome is GateOutcome.FAIL:
            reasons.append(f"{result.gate_id} {result.name} failed: {result.detail}")
        elif result.outcome is GateOutcome.UNVERIFIED:
            reasons.append(f"{result.gate_id} {result.name} could not be verified: {result.detail}")

    if not verifier.checks:
        reasons.append("independent verifier reported no checks")
    for check in verifier.checks:
        if check.outcome is CheckOutcome.FAIL:
            reasons.append(f"verifier check {check.name!r} failed: {check.detail}")
        elif check.outcome is CheckOutcome.UNVERIFIED:
            reasons.append(f"verifier check {check.name!r} could not be verified: {check.detail}")

    if manual_rescue:
        reasons.append("the run required a manual rescue")

    if reasons:
        return StatusDecision(RunStatus.PARTIAL, _dedupe(reasons))

    return StatusDecision(
        RunStatus.TRUSTED_COMPLETE,
        (f"all {len(gate_results)} gates and {len(verifier.checks)} verifier checks passed",),
    )


def _dedupe(reasons: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for reason in reasons:
        seen.setdefault(reason, None)
    return tuple(seen)
