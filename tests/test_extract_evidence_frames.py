from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

TOOL_PATH = Path(__file__).parents[1] / "tools" / "extract_evidence_frames.py"


@pytest.fixture(scope="module")
def extractor():
    spec = importlib.util.spec_from_file_location("extract_evidence_frames", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scene_detection_failure_does_not_become_zero_timestamp(extractor, monkeypatch):
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "decode failed"),
    )

    with pytest.raises(extractor.FrameExtractionError, match="scene detection failed"):
        extractor.detect_scene_timestamps_ms(Path("broken.mp4"))


def test_successful_no_cut_detection_returns_empty_list(extractor, monkeypatch):
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "normal ffmpeg log"),
    )

    assert extractor.detect_scene_timestamps_ms(Path("static.mp4")) == []


def test_frame_extraction_requires_an_output_image(extractor, monkeypatch, tmp_path):
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    with pytest.raises(extractor.FrameExtractionError, match="produced no image"):
        extractor.extract_frame_ms(Path("video.mp4"), 500, tmp_path / "missing.jpg")


def test_interval_pipeline_records_provenance_and_unique_candidates(
    extractor, monkeypatch, tmp_path
):
    extracted_paths = []
    _stub_video_pipeline(
        extractor,
        monkeypatch,
        duration_ms=4_000,
        cuts_ms=[1_000, 1_800],
        extracted_paths=extracted_paths,
    )

    manifest = extractor.extract_evidence_frames(
        "https://youtu.be/QmPUp9ISuDw",
        tmp_path / "frames",
        work_root=tmp_path / "work",
    )

    assert manifest["manifest_version"] == 2
    assert manifest["config"]["version"] == "evidence-frame-v4"
    assert len(manifest["segments"]) == 3
    assert manifest["frames"]
    assert len(extracted_paths) == len(set(extracted_paths))
    manifest_dir = tmp_path / "frames"
    for frame in manifest["frames"]:
        assert isinstance(frame["boundary_ms"], int)
        assert isinstance(frame["timestamp_ms"], int)
        assert frame["boundary_ms"] <= frame["timestamp_ms"] < frame["segment_end_ms"]
        assert frame["settle_offset_ms"] == frame["timestamp_ms"] - frame["boundary_ms"]
        assert frame["features"]
        assert frame["selection_reason"]
        resolved = (manifest_dir / frame["path"]).resolve()
        assert resolved.is_file()
        assert resolved.parent == manifest_dir.resolve()


@pytest.mark.parametrize("out_name", ("frames", "custom_out"))
def test_manifest_frame_paths_resolve_relative_to_manifest(
    extractor, monkeypatch, tmp_path, out_name
):
    _stub_video_pipeline(
        extractor,
        monkeypatch,
        duration_ms=4_000,
        cuts_ms=[1_000],
        extracted_paths=[],
    )
    out_dir = tmp_path / out_name

    manifest = extractor.extract_evidence_frames(
        "https://youtu.be/QmPUp9ISuDw",
        out_dir,
        work_root=tmp_path / "work",
    )

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    assert manifest["frames"]
    for frame in manifest["frames"]:
        frame_path = (manifest_path.parent / frame["path"]).resolve()
        assert frame_path.is_file()
        assert frame_path.parent == out_dir.resolve()
        assert not str(frame["path"]).startswith("frames/")
    for segment in manifest["segments"]:
        selected_path = segment.get("selected_path")
        if selected_path is None:
            continue
        assert (manifest_path.parent / selected_path).resolve().is_file()


def test_no_scene_changes_still_probe_later_material(extractor, monkeypatch, tmp_path):
    extracted_paths = []
    _stub_video_pipeline(
        extractor,
        monkeypatch,
        duration_ms=31_000,
        cuts_ms=[],
        extracted_paths=extracted_paths,
    )

    manifest = extractor.extract_evidence_frames(
        "https://youtu.be/QmPUp9ISuDw",
        tmp_path / "frames",
        work_root=tmp_path / "work",
    )

    timestamps = {
        candidate["timestamp_ms"]
        for segment in manifest["segments"]
        for candidate in segment["candidates"]
    }
    assert 15_000 in timestamps
    assert 30_000 in timestamps


def test_failed_rerun_invalidates_previous_manifest(extractor, monkeypatch, tmp_path):
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text('{"complete": true}', encoding="utf-8")
    (out_dir / "old_scene.jpg").write_bytes(b"old")
    monkeypatch.setattr(extractor, "download_video", lambda *_args: None)
    monkeypatch.setattr(extractor, "probe_duration_ms", lambda _video: 4_000)

    def fail(_video):
        raise extractor.FrameExtractionError("decode failed")

    monkeypatch.setattr(extractor, "detect_scene_timestamps_ms", fail)

    with pytest.raises(extractor.FrameExtractionError, match="decode failed"):
        extractor.extract_evidence_frames(
            "https://youtu.be/QmPUp9ISuDw",
            out_dir,
            work_root=tmp_path / "work",
        )

    assert not manifest_path.exists()
    assert (out_dir / "old_scene.jpg").exists()


def test_cli_returns_failure_for_adapter_error(extractor, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise extractor.FrameExtractionError("ffmpeg unavailable")

    monkeypatch.setattr(extractor, "extract_evidence_frames", fail)

    assert extractor.main(["https://youtu.be/QmPUp9ISuDw"]) == 1
    assert "frame extraction failed: ffmpeg unavailable" in capsys.readouterr().err


def _stub_video_pipeline(
    extractor,
    monkeypatch,
    *,
    duration_ms: int,
    cuts_ms: list[int],
    extracted_paths: list[str],
) -> None:
    def download(_url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture video")

    def extract(_video, timestamp_ms, destination, width=1280):
        extracted_paths.append(destination.name)
        image = Image.new("RGB", (320, 180), (4, 7, 14))
        draw = ImageDraw.Draw(image)
        for x in range(10, 320, 20):
            draw.line((x, 15, x, 165), fill=(20, 160, 220), width=2)
        for y in range(20, 180, 20):
            draw.line((10, y, 310, y), fill=(230, 90, 30), width=2)
        draw.text((20, 20), f"chart {timestamp_ms}", fill="white")
        image.save(destination)

    monkeypatch.setattr(extractor, "download_video", download)
    monkeypatch.setattr(extractor, "probe_duration_ms", lambda _video: duration_ms)
    monkeypatch.setattr(extractor, "detect_scene_timestamps_ms", lambda _video: cuts_ms)
    monkeypatch.setattr(extractor, "extract_frame_ms", extract)
