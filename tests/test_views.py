"""Generated views: equivalence, determinism, disclosure, and escaping."""

from __future__ import annotations

import re

from video_research.run import RunStatus
from video_research.store import read_pack
from video_research.views import render_report, render_summary


def test_both_views_report_the_same_status(run_fixture):
    pack = run_fixture()
    assert "Trusted-Complete Run" in pack.summary_markdown
    assert "Trusted-Complete Run" in pack.report_html


def test_both_views_carry_the_same_material_claims(run_fixture):
    pack = run_fixture()
    for claim in pack.ledger.material_claims():
        assert claim.claim_id in pack.summary_markdown
        assert claim.claim_id in pack.report_html
        assert claim.statement in pack.summary_markdown


def test_the_summary_leads_with_status_before_any_findings(run_fixture):
    pack = run_fixture()
    status_at = pack.summary_markdown.index("**Status:")
    claims_at = pack.summary_markdown.index("## Claims and evidence")
    assert status_at < claims_at


def test_a_partial_run_lists_every_blocker_up_front(benchmark_payload, write_fixture,
                                                    run_fixture):
    benchmark_payload["windows"][2]["visual"] = "unobserved"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert pack.status is RunStatus.PARTIAL
    blockers_at = pack.summary_markdown.index("## Completeness blockers")
    claims_at = pack.summary_markdown.index("## Claims and evidence")
    assert blockers_at < claims_at
    for reason in pack.run.status_reasons:
        assert reason in pack.summary_markdown


def test_a_failed_run_says_what_went_fatally_wrong(benchmark_payload, write_fixture,
                                                   run_fixture):
    benchmark_payload["extraction_error"] = "audio track is missing"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert "## Fatal research failures" in pack.summary_markdown
    assert "audio track is missing" in pack.summary_markdown


def test_claim_roles_are_never_flattened_into_plain_assertions(run_fixture):
    pack = run_fixture()
    assert "the speaker claims" in pack.summary_markdown
    assert "the video shows" in pack.summary_markdown


def test_qualifying_evidence_is_shown_not_dropped(run_fixture):
    """The summary must not cherry-pick only the evidence that supports a claim."""
    pack = run_fixture()
    assert "qualifies" in pack.summary_markdown
    assert "qualifies" in pack.report_html


def test_evidence_is_cited_by_timestamp(run_fixture):
    pack = run_fixture()
    assert re.search(r"speech \d\d:\d\d-\d\d:\d\d", pack.summary_markdown)
    assert re.search(r"visual \d\d:\d\d-\d\d:\d\d", pack.summary_markdown)


def test_rerendering_unchanged_canonical_artifacts_is_identical(run_fixture, tmp_path):
    out = tmp_path / "pack"
    pack = run_fixture(out=out)
    reloaded = read_pack(out)

    assert render_summary(reloaded) == pack.summary_markdown
    assert render_report(reloaded) == pack.report_html


def test_views_never_read_the_clock(run_fixture):
    """Every time-dependent value comes from the run record, so two renders match."""
    pack = run_fixture()
    assert render_summary(pack) == render_summary(pack)
    assert pack.run.created_at in pack.summary_markdown


def test_source_text_is_escaped_in_the_html_report(benchmark_payload, write_fixture,
                                                   run_fixture):
    """Transcripts, titles, and OCR text are attacker-controlled."""
    benchmark_payload["source"]["title"] = "<script>alert('xss')</script>"
    benchmark_payload["claims"][0]["statement"] = "closing </td></tr></table><img src=x onerror=1>"
    pack = run_fixture(write_fixture(benchmark_payload))

    assert "<script>alert" not in pack.report_html
    assert "&lt;script&gt;alert" in pack.report_html
    assert "<img src=x onerror=1>" not in pack.report_html


def test_external_reference_urls_are_escaped(benchmark_payload, write_fixture, run_fixture):
    benchmark_payload["claims"][0]["external"] = [
        {"url": '"><script>alert(1)</script>', "title": "primary source",
         "relation": "supports"}
    ]
    pack = run_fixture(write_fixture(benchmark_payload))

    assert "<script>alert(1)</script>" not in pack.report_html
    assert 'rel="nofollow noopener"' in pack.report_html


def test_the_summary_discloses_engine_identity_and_outbound_data(run_fixture):
    pack = run_fixture()
    assert "fixture 1.0.0" in pack.summary_markdown
    assert "outbound data: none" in pack.summary_markdown


def test_generated_views_say_they_are_generated(run_fixture):
    pack = run_fixture()
    assert "Do not edit by hand" in pack.summary_markdown
    assert "Do not edit by hand" in pack.report_html
