#!/usr/bin/env python3
"""Extract settled Evidence Frames from a video.

Scene changes are triggers, not evidence timestamps.  Consecutive cuts define
Presentation Segments; bounded post-cut and periodic probes are ranked inside
each segment.  Blank, talking-head, and face-dominant mixed frames are rejected.
Dark colorful charts remain eligible because saturation is recorded as a feature,
never used as a hard rejection.

Usage:
    python tools/extract_evidence_frames.py <youtube_url> [out_dir]

The versioned manifest records selected and rejected candidates, feature scores,
boundary and selected timestamps, settle offsets, reasons, and configuration.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from video_research.frame_adapter import (
    FrameCandidate,
    FrameProbe,
    FrameSelectionConfig,
    PresentationSegment,
    build_presentation_segments,
    probes_for_segment,
    select_frame,
)

SCENE_THRESHOLD = 0.15
DOWNLOAD_FORMAT = "bv*[height<=720]+ba/b[height<=720]"
MANIFEST_VERSION = 2


class FrameExtractionError(RuntimeError):
    """The impure frame adapter could not establish visual evidence."""


def extract_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if not match:
        raise FrameExtractionError(f"could not parse video id from: {url}")
    return match.group(1)


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def download_video(url: str, destination: Path) -> None:
    if destination.exists():
        return
    run(
        [
            "yt-dlp",
            "-f",
            DOWNLOAD_FORMAT,
            "--merge-output-format",
            "mp4",
            "-o",
            str(destination),
            url,
        ]
    )


def probe_duration_ms(video: Path) -> int:
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise FrameExtractionError(f"ffprobe failed: {_error_detail(process)}")
    try:
        duration_ms = round(float(process.stdout.strip()) * 1_000)
    except ValueError as exc:
        raise FrameExtractionError("ffprobe returned an invalid duration") from exc
    if duration_ms <= 0:
        raise FrameExtractionError("ffprobe returned a non-positive duration")
    return duration_ms


def detect_scene_timestamps_ms(video: Path) -> list[int]:
    """Return successful ffmpeg scene boundaries in integer milliseconds."""

    process = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video),
            "-vf",
            f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
            "-vsync",
            "vfr",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise FrameExtractionError(f"scene detection failed: {_error_detail(process)}")
    timestamps = []
    for line in process.stderr.splitlines():
        match = re.search(r"pts_time:([\d.]+)", line)
        if match:
            timestamps.append(round(float(match.group(1)) * 1_000))
    return timestamps


def detect_scene_timestamps(video: Path) -> list[float]:
    """Compatibility wrapper returning scene boundaries in seconds."""

    return [timestamp / 1_000 for timestamp in detect_scene_timestamps_ms(video)]


def extract_frame(video: Path, timestamp: float, destination: Path, width: int = 1280) -> None:
    """Compatibility entry point accepting seconds, as the original tool did."""

    extract_frame_ms(video, round(timestamp * 1_000), destination, width)


def extract_frame_ms(
    video: Path, timestamp_ms: int, destination: Path, width: int = 1280
) -> None:
    process = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp_ms / 1_000:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "2",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise FrameExtractionError(
            f"frame extraction failed at {timestamp_ms} ms: {_error_detail(process)}"
        )
    if not destination.exists() or destination.stat().st_size == 0:
        raise FrameExtractionError(f"frame extraction produced no image at {timestamp_ms} ms")


def extract_evidence_frames(
    url: str,
    out_dir: Path,
    *,
    work_root: Path | None = None,
    config: FrameSelectionConfig | None = None,
    claim_timestamps_ms: tuple[int, ...] = (),
) -> dict[str, object]:
    """Run one fail-closed selection pass and return its versioned manifest."""

    config = config or FrameSelectionConfig()
    video_id = extract_video_id(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    # The manifest is the publication boundary.  Invalidate it before touching
    # frame artifacts so a failed rerun cannot expose a stale successful pack.
    manifest_path.unlink(missing_ok=True)
    cache_root = work_root or Path(
        os.environ.get(
            "VIDEO_RESEARCH_FRAME_CACHE",
            Path.home() / ".cache" / "video_research" / "frames",
        )
    )
    work = cache_root / video_id
    work.mkdir(parents=True, exist_ok=True)
    video_path = work / "source_720p.mp4"
    candidate_dir = work / "scene_candidates"
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    candidate_dir.mkdir()

    download_video(url, video_path)
    duration_ms = probe_duration_ms(video_path)
    cuts_ms = detect_scene_timestamps_ms(video_path)
    segments = build_presentation_segments(cuts_ms, duration_ms)

    frame_records: list[dict[str, object]] = []
    segment_records: list[dict[str, object]] = []
    for segment_index, segment in enumerate(segments):
        candidates = _extract_segment_candidates(
            video_path,
            candidate_dir,
            segment_index,
            segment,
            config,
            claim_timestamps_ms,
        )
        selection = select_frame(segment, candidates, config)
        selection_record = selection.manifest()
        if selection.selected is not None:
            destination = _copy_selected(out_dir, selection.selected.path, selection.selected.probe)
            # Paths are relative to manifest.json (written beside the JPEG in out_dir).
            relative_path = destination.name
            selected_record = selection.selected.manifest(segment)
            selected_record.update(
                {
                    "path": relative_path,
                    "filename": destination.name,
                    "timestamp_s": selection.selected.probe.timestamp_ms / 1_000,
                    "mmss": fmt_mmss(selection.selected.probe.timestamp_ms),
                    "method": "interval_ranked",
                    "selection_reason": selection.reason,
                    "config_version": config.version,
                }
            )
            frame_records.append(selected_record)
            selection_record["selected_path"] = relative_path
        segment_records.append(selection_record)

    manifest: dict[str, object] = {
        "manifest_version": MANIFEST_VERSION,
        "complete": True,
        "video_id": video_id,
        "duration_ms": duration_ms,
        "config": config.manifest(),
        "frames": frame_records,
        "segments": segment_records,
    }
    _publish_manifest(manifest_path, manifest)
    return manifest


def fmt_mmss(timestamp_ms: int) -> str:
    seconds = timestamp_ms // 1_000
    return f"{seconds // 60:02d}:{seconds % 60:02d}.{timestamp_ms % 1_000:03d}"


def _extract_segment_candidates(
    video: Path,
    candidate_dir: Path,
    segment_index: int,
    segment: PresentationSegment,
    config: FrameSelectionConfig,
    claim_timestamps_ms: tuple[int, ...],
) -> list[FrameCandidate]:
    candidates = []
    probes = probes_for_segment(segment, config, claim_timestamps_ms)
    for probe_index, probe in enumerate(probes):
        destination = candidate_dir / (
            f"segment_{segment_index:04d}_probe_{probe_index:03d}_{probe.timestamp_ms:010d}.jpg"
        )
        extract_frame_ms(video, probe.timestamp_ms, destination)
        candidates.append(FrameCandidate(probe=probe, path=destination))
    return candidates


def _copy_selected(out_dir: Path, source: Path, probe: FrameProbe) -> Path:
    seconds = probe.timestamp_ms // 1_000
    stem = f"{seconds // 60:02d}{seconds % 60:02d}_{probe.timestamp_ms % 1_000:03d}_scene"
    destination = out_dir / f"{stem}.jpg"
    ordinal = 1
    while destination.exists():
        ordinal += 1
        destination = out_dir / f"{stem}_{ordinal}.jpg"
    shutil.copy(source, destination)
    return destination


def _publish_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Atomically publish the only artifact that declares a run complete."""

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".manifest-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(manifest, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _error_detail(process: subprocess.CompletedProcess) -> str:
    detail = (process.stderr or process.stdout or "unknown ffmpeg error").strip()
    return detail.splitlines()[-1] if detail else "unknown ffmpeg error"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print(__doc__)
        return 2

    url = arguments[0]
    try:
        video_id = extract_video_id(url)
        out_dir = Path(arguments[1]) if len(arguments) > 1 else Path.cwd() / video_id / "frames"
        manifest = extract_evidence_frames(url, out_dir)
    except (FrameExtractionError, OSError, subprocess.SubprocessError) as exc:
        print(f"frame extraction failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"kept {len(manifest['frames'])} Evidence Frames from "
        f"{len(manifest['segments'])} Presentation Segments"
    )
    print(f"manifest: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
