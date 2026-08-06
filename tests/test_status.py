"""The status decision, driven exhaustively.

The project's acceptance criterion is a negative: no run may be presented as
trusted-complete while a trust gate is unmet. Because status has exactly one
producer, that negative is a property of one pure function, and this module
proves it by enumerating every combination of its inputs rather than sampling
a few.
"""

from __future__ import annotations

import itertools

import pytest

from video_research.diagnostics import Diagnostic, DiagnosticCode, Severity
from video_research.gates import GateOutcome, GateResult
from video_research.ports import CheckOutcome, VerifierCheck, VerifierReport
from video_research.run import RunStatus
from video_research.status import REQUIRED_GATES, decide

INFO = Diagnostic(DiagnosticCode.DUPLICATE_EVIDENCE, "same span cited twice")
BLOCKER = Diagnostic(DiagnosticCode.WINDOW_UNOBSERVED, "nobody looked at 04:00-05:00")
FATAL = Diagnostic(DiagnosticCode.NO_USABLE_TRANSCRIPT, "no speech record at all")

PROBE_GATE = "G3"


def gates(outcome: GateOutcome = GateOutcome.PASS) -> tuple[GateResult, ...]:
    """A full slate of gates, with the probe gate set to ``outcome``."""
    return tuple(
        GateResult(
            gate_id,
            f"gate {gate_id}",
            outcome if gate_id == PROBE_GATE else GateOutcome.PASS,
            "detail",
        )
        for gate_id in sorted(REQUIRED_GATES)
    )


def report(outcome: CheckOutcome) -> VerifierReport:
    return VerifierReport((VerifierCheck("material_recall", outcome, "detail"),))


def test_all_clear_is_trusted_complete():
    decision = decide((), gates(), report(CheckOutcome.PASS))
    assert decision.status is RunStatus.TRUSTED_COMPLETE
    assert decision.trusted


def test_informational_diagnostics_do_not_change_status():
    decision = decide((INFO,), gates(), report(CheckOutcome.PASS))
    assert decision.status is RunStatus.TRUSTED_COMPLETE


def test_a_fatal_failure_outranks_everything_else():
    decision = decide((BLOCKER, FATAL), gates(), report(CheckOutcome.PASS))
    assert decision.status is RunStatus.FAILED
    assert decision.reasons == (FATAL.describe(),)


def test_a_completeness_blocker_forces_partial():
    decision = decide((BLOCKER,), gates(), report(CheckOutcome.PASS))
    assert decision.status is RunStatus.PARTIAL
    assert BLOCKER.describe() in decision.reasons


@pytest.mark.parametrize("outcome", [GateOutcome.FAIL, GateOutcome.UNVERIFIED])
def test_a_gate_that_did_not_pass_forces_partial(outcome):
    decision = decide((), gates(outcome), report(CheckOutcome.PASS))
    assert decision.status is RunStatus.PARTIAL


@pytest.mark.parametrize("outcome", [CheckOutcome.FAIL, CheckOutcome.UNVERIFIED])
def test_a_verifier_check_that_did_not_pass_forces_partial(outcome):
    decision = decide((), gates(), report(outcome))
    assert decision.status is RunStatus.PARTIAL


def test_manual_rescue_forces_partial():
    decision = decide((), gates(), report(CheckOutcome.PASS), manual_rescue=True)
    assert decision.status is RunStatus.PARTIAL
    assert "manual rescue" in " ".join(decision.reasons)


def test_verifier_disagreement_cannot_be_hidden():
    decision = decide((), gates(), report(CheckOutcome.FAIL))
    assert decision.status is RunStatus.PARTIAL
    assert any("material_recall" in reason for reason in decision.reasons)


def test_a_degraded_run_always_explains_itself():
    decision = decide((BLOCKER,), gates(GateOutcome.FAIL), report(CheckOutcome.FAIL))
    assert decision.status is RunStatus.PARTIAL
    assert len(decision.reasons) >= 3


def test_a_run_with_no_gates_at_all_is_not_complete():
    """A run nobody checked is a run nobody can vouch for."""
    decision = decide((), (), VerifierReport())
    assert decision.status is RunStatus.PARTIAL
    assert any("never reported" in reason for reason in decision.reasons)


@pytest.mark.parametrize("dropped", sorted(REQUIRED_GATES))
def test_dropping_any_single_gate_forbids_completeness(dropped):
    """A gate wired up later but never called degrades the run, silently widening nothing."""
    remaining = tuple(g for g in gates() if g.gate_id != dropped)
    decision = decide((), remaining, report(CheckOutcome.PASS))
    assert decision.status is RunStatus.PARTIAL
    assert any(dropped in reason for reason in decision.reasons)


def test_no_input_combination_yields_false_completeness():
    """Exhaustive: trusted-complete requires every single input to be clean."""
    diagnostic_sets = [(), (INFO,), (BLOCKER,), (FATAL,), (INFO, BLOCKER), (BLOCKER, FATAL)]
    combinations = itertools.product(
        diagnostic_sets, GateOutcome, CheckOutcome, [False, True]
    )

    for diagnostics, gate_outcome, check_outcome, rescue in combinations:
        decision = decide((*diagnostics,), gates(gate_outcome), report(check_outcome), rescue)

        clean = (
            all(d.severity is Severity.INFORMATIONAL for d in diagnostics)
            and gate_outcome is GateOutcome.PASS
            and check_outcome is CheckOutcome.PASS
            and not rescue
        )
        assert decision.trusted == clean, (
            f"diagnostics={[d.code.value for d in diagnostics]} gate={gate_outcome} "
            f"check={check_outcome} rescue={rescue} -> {decision.status}"
        )

        if any(d.severity is Severity.FATAL for d in diagnostics):
            assert decision.status is RunStatus.FAILED
        elif not clean:
            assert decision.status is RunStatus.PARTIAL
            assert decision.reasons, "a degraded run must say why"
