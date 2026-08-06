"""Shared fixtures.

Failure injection works by mutating a copy of the golden benchmark fixture and
writing it to a temporary path. The mutation is the injected failure, so every
injection test states its damage in one visible place instead of maintaining a
dozen near-identical fixture files that drift apart.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from video_research.adapters import (
    FixtureClaimExtractor,
    FixtureExtractionEngine,
    StructuralVerifier,
)
from video_research.run import ResearchPack
from video_research.skill import research_video

BENCHMARK = Path(__file__).parent / "fixtures" / "talk_benchmark.json"

#: Pinned so generated artifacts are byte-reproducible across runs.
PINNED_RUN_ID = "run-000000000001"
PINNED_CREATED_AT = "2026-08-06T00:00:00+00:00"


@pytest.fixture
def benchmark_payload() -> dict[str, Any]:
    return json.loads(BENCHMARK.read_text(encoding="utf-8"))


@pytest.fixture
def write_fixture(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    """Write a (possibly damaged) fixture payload and return its path."""
    counter = {"n": 0}

    def _write(payload: dict[str, Any]) -> Path:
        counter["n"] += 1
        path = tmp_path / f"injected_{counter['n']}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def run_fixture(tmp_path: Path) -> Callable[..., ResearchPack]:
    """Run the public entry point against a fixture path."""

    def _run(fixture_path: Path = BENCHMARK, *, out: Path | None = None, **kwargs: Any):
        return research_video(
            str(fixture_path),
            engine=FixtureExtractionEngine(fixture_path),
            claim_extractor=FixtureClaimExtractor(fixture_path),
            verifier=StructuralVerifier(),
            output_dir=out if out is not None else tmp_path / "pack",
            run_id=kwargs.pop("run_id", PINNED_RUN_ID),
            created_at=kwargs.pop("created_at", PINNED_CREATED_AT),
            **kwargs,
        )

    return _run
