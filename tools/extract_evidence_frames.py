#!/usr/bin/env python3
"""
Scene-change evidence frame extractor for video_evidence research.

Method:
  1. Download the video at 720p (cheap, sharp enough for code/UI text).
  2. ffmpeg scene detection (default threshold 0.30) -> candidate timestamps.
  3. Extract one frame per scene at HQ JPEG quality.
  4. Drop "talking-head only" frames using a brightness heuristic on the
     left half of the frame: screencast/UI content is dominated by dark
     editor/browser pixels; warm bookshelf/face shots are not.
  5. Emit frames + manifest.json.

Use this as the default method for new video_evidence runs. The previous
"hand-pick timestamps from transcript hypotheses" approach misses any
on-screen evidence the transcript does not foreshadow.

Usage:
    python extract_evidence_frames.py <youtube_url> [out_dir]

If out_dir is omitted, defaults to:
    /Users/stanley/Projects/video-research/<video_id>/frames/

Tunables (edit constants below if needed):
    SCENE_THRESHOLD     - lower => more candidate frames
    DARK_PIXEL_VALUE    - what counts as "editor-dark" (0-255 grayscale)
    DARK_PIXEL_FRACTION - min fraction of left-half pixels that must be
                          dark for a frame to count as screen content
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

SCENE_THRESHOLD = 0.15
MAX_LEFT_SATURATION = 35  # 0-255; bookshelf+skin > 60, editor/browser < 25
DOWNLOAD_FORMAT = "bv*[height<=720]+ba/b[height<=720]"


def extract_video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise SystemExit(f"could not parse video id from: {url}")
    return m.group(1)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def download_video(url: str, dst: Path) -> None:
    if dst.exists():
        return
    run([
        "yt-dlp", "-f", DOWNLOAD_FORMAT,
        "--merge-output-format", "mp4",
        "-o", str(dst), url,
    ])


def detect_scene_timestamps(video: Path) -> list[float]:
    """Return list of seconds where a scene change occurs."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(video),
            "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
            "-vsync", "vfr", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    times: list[float] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            times.append(float(m.group(1)))
    return times


def extract_frame(video: Path, ts: float, dst: Path, width: int = 1280) -> None:
    run([
        "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", f"scale={width}:-2",
        "-q:v", "2", str(dst),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_screen_content(img_path: Path) -> bool:
    """True if the LEFT half of the image is low-saturation (editor/browser).

    Screencast UI is nearly grayscale; talking-head shots (warm bookshelf
    wood, lamp glow, skin tones) have high saturation. The speaker PIP
    typically sits in the right half during screen-shares, so sampling
    the left half avoids it.
    """
    img = Image.open(img_path).convert("HSV")
    w, h = img.size
    left = img.crop((0, 0, w // 2, h))
    sat_band = left.split()[1]  # S channel, 0-255
    pixels = list(sat_band.getdata())
    mean_sat = sum(pixels) / len(pixels)
    return mean_sat <= MAX_LEFT_SATURATION


def fmt_mmss(ts: float) -> str:
    s = int(ts)
    return f"{s // 60:02d}{s % 60:02d}"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    url = sys.argv[1]
    vid = extract_video_id(url)
    default_out = Path(f"/Users/stanley/Projects/video-research/{vid}/frames")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else default_out
    out_dir.mkdir(parents=True, exist_ok=True)

    work = Path(f"/Users/stanley/.cache/claudetube_runs/{vid}")
    work.mkdir(parents=True, exist_ok=True)
    video_path = work / "source_720p.mp4"
    cand_dir = work / "scene_candidates"
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir()

    print(f"[1/4] downloading {vid} (720p)...")
    download_video(url, video_path)

    print("[2/4] detecting scene changes...")
    times = detect_scene_timestamps(video_path)
    if not times:
        times = [0.0]
    print(f"      {len(times)} candidate scenes")

    print("[3/4] extracting candidate frames...")
    candidates: list[tuple[float, Path]] = []
    for ts in times:
        cand = cand_dir / f"cand_{fmt_mmss(ts)}.jpg"
        extract_frame(video_path, ts, cand)
        candidates.append((ts, cand))

    print("[4/4] filtering talking-head-only frames...")
    manifest: list[dict] = []
    kept = 0
    for ts, cand in candidates:
        if not is_screen_content(cand):
            continue
        kept += 1
        mmss = fmt_mmss(ts)
        dst = out_dir / f"{mmss}_scene.jpg"
        # if multiple scenes share an mmss bucket, suffix with index
        n = 1
        while dst.exists():
            n += 1
            dst = out_dir / f"{mmss}_scene_{n}.jpg"
        shutil.copy(cand, dst)
        manifest.append({
            "timestamp_s": round(ts, 3),
            "mmss": f"{ts // 60:02.0f}:{ts % 60:05.2f}",
            "path": f"frames/{dst.name}",
            "method": "scene_change_filtered",
        })
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nkept {kept} screen-content frames out of {len(candidates)} scene candidates")
    print(f"output: {out_dir}")
    print(f"manifest: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
