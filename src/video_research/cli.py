"""One invocation, one research pack.

Exit codes mirror the run status so a caller can gate on them without parsing
output: 0 trusted-complete, 1 partial, 2 failed, 3 the tool itself broke.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapters import FixtureClaimExtractor, FixtureExtractionEngine, StructuralVerifier
from .run import RunStatus
from .skill import FIXTURE_ENVELOPE, research_video

EXIT_CODES = {
    RunStatus.TRUSTED_COMPLETE: 0,
    RunStatus.PARTIAL: 1,
    RunStatus.FAILED: 2,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-research",
        description=(
            "Produce an evidence-backed research pack from a source, with an honest "
            "trusted-complete, partial, or failed verdict."
        ),
    )
    parser.add_argument(
        "--fixture",
        required=True,
        type=Path,
        help=(
            "Deterministic extracted-source fixture to research. Live extraction "
            "engines are not part of this release."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory to write the research pack into. Omit to print the summary only.",
    )
    parser.add_argument(
        "--source-ref",
        default=None,
        help="Override the source reference recorded in the run (defaults to the fixture's own).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Pin the run id. Each run mints its own by default; a cold rerun must be distinct.",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="Pin the run timestamp, for reproducible output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.fixture.exists():
        print(f"fixture not found: {args.fixture}", file=sys.stderr)
        return 3

    engine = FixtureExtractionEngine(args.fixture)
    pack = research_video(
        args.source_ref or str(args.fixture),
        engine=engine,
        claim_extractor=FixtureClaimExtractor(args.fixture),
        verifier=StructuralVerifier(),
        envelope=FIXTURE_ENVELOPE,
        output_dir=args.out,
        run_id=args.run_id,
        created_at=args.created_at,
    )

    print(pack.summary_markdown)
    if args.out is not None:
        print(f"research pack written to {args.out}", file=sys.stderr)
    return EXIT_CODES[pack.status]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
