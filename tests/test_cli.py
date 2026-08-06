"""The one-command invocation."""

from __future__ import annotations

import pytest

from video_research.cli import main

from .conftest import BENCHMARK


def test_a_clean_run_exits_zero_and_prints_the_summary(tmp_path, capsys):
    code = main(["--fixture", str(BENCHMARK), "--out", str(tmp_path / "pack")])
    out = capsys.readouterr().out

    assert code == 0
    assert "Trusted-Complete Run" in out
    assert (tmp_path / "pack" / "run.json").exists()


def test_one_command_produces_the_whole_pack_without_manual_steps(tmp_path):
    main(["--fixture", str(BENCHMARK), "--out", str(tmp_path / "pack")])
    written = sorted(p.name for p in (tmp_path / "pack").iterdir())
    assert written == ["claims.json", "coverage.json", "report.html", "run.json", "summary.md"]


def test_a_partial_run_exits_one(tmp_path, benchmark_payload, write_fixture, capsys):
    benchmark_payload["windows"][2]["visual"] = "unobserved"
    code = main(["--fixture", str(write_fixture(benchmark_payload)), "--out", str(tmp_path / "p")])
    assert code == 1
    assert "Partial Run" in capsys.readouterr().out


def test_a_failed_run_exits_two(tmp_path, benchmark_payload, write_fixture, capsys):
    benchmark_payload["extraction_error"] = "no audio"
    code = main(["--fixture", str(write_fixture(benchmark_payload)), "--out", str(tmp_path / "p")])
    assert code == 2
    assert "Failed Run" in capsys.readouterr().out


def test_a_missing_fixture_is_an_actionable_error_not_a_crash(tmp_path, capsys):
    code = main(["--fixture", str(tmp_path / "nope.json")])
    assert code == 3
    assert "fixture not found" in capsys.readouterr().err


def test_the_fixture_argument_is_required(capsys):
    with pytest.raises(SystemExit):
        main([])


def test_provenance_can_be_pinned_for_reproducible_output(tmp_path, capsys):
    main(
        [
            "--fixture",
            str(BENCHMARK),
            "--run-id",
            "run-pinned",
            "--created-at",
            "2026-01-01T00:00:00+00:00",
        ]
    )
    out = capsys.readouterr().out
    assert "run-pinned" in out
    assert "2026-01-01T00:00:00+00:00" in out
