from __future__ import annotations

import json
import operator
from pathlib import Path

import pytest

from video_research.frame_adapter import (
    FrameCandidate,
    FrameProbe,
    FrameSelectionConfig,
    PresentationSegment,
    analyze_frame,
    select_frame,
)
from video_research.timeline import VisualObservation

CORPUS = Path(__file__).parent / "fixtures" / "evidence_frames"
LABELS = json.loads((CORPUS / "labels.json").read_text(encoding="utf-8"))
KEEP = sorted(name for name, label in LABELS.items() if label["expected"] == "keep")
REJECT = sorted(name for name, label in LABELS.items() if label["expected"] == "reject")
SETTLED_EVIDENCE = "gex_0028_dark_colorful_chart.jpg"


@pytest.mark.parametrize("filename", sorted(LABELS))
def test_label_contract(filename):
    label = LABELS[filename]
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert features.eligible is (label["expected"] == "keep"), label["label"]
    assert features.rejection_reason == label.get("reason"), label["label"]


@pytest.mark.parametrize("filename", KEEP)
def test_keep_frame_is_selected_alone(filename):
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / filename),),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == filename
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize("filename", REJECT)
def test_rejected_stable_pair_loses_to_later_evidence(filename):
    selection = select_frame(
        PresentationSegment(0, 12_000),
        (
            FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / filename),
            FrameCandidate(FrameProbe(1_500, "post_cut"), CORPUS / filename),
            FrameCandidate(FrameProbe(8_000, "post_cut"), CORPUS / SETTLED_EVIDENCE),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == SETTLED_EVIDENCE
    assert selection.observation is VisualObservation.OBSERVED


FEATURE_BOUNDS = (
    ("gex_0028_dark_colorful_chart.jpg", "mean_saturation", operator.gt, 100),
    ("orb_0730_face_dominant.jpg", "largest_warm_component_fraction", operator.ge, 0.03),
    ("chart_with_webcam_pip.jpg", "largest_warm_component_fraction", operator.ge, 0.01),
    ("face_plus_vertical_bars.jpg", "largest_warm_component_fraction", operator.ge, 0.05),
    ("face_plus_ceiling_grid.jpg", "largest_warm_component_fraction", operator.ge, 0.01),
    ("gex_dark_chart_with_webcam_pip.jpg", "compact_face_fraction", operator.ge, 0.01),
    ("face_plus_barcode.jpg", "compact_face_fraction", operator.ge, 0.01),
    ("soft_orange_area_chart.jpg", "mean_saturation", operator.lt, 80),
    ("corporate_blue_area_chart.jpg", "mean_saturation", operator.lt, 80),
    ("face_plus_color_stalls.jpg", "compact_face_fraction", operator.ge, 0.01),
    *(
        (filename, "compact_face_fraction", operator.ge, 0.01)
        for filename in (
            "face_plus_busy_calendar.jpg",
            "face_plus_flowchart.jpg",
            "face_plus_pcb_traces.jpg",
            "face_plus_equalizer.jpg",
            "face_plus_kanban.jpg",
            "face_plus_keypad.jpg",
            "face_plus_panel_grid.jpg",
            "face_plus_org_chart.jpg",
            "face_plus_decision_tree.jpg",
            "face_plus_er_diagram.jpg",
            "face_plus_colorbar_schedule_board.jpg",
        )
    ),
    ("face_plus_arial_sprint_kanban.jpg", "compact_face_fraction", operator.ge, 0.01),
    ("face_plus_network_topology.jpg", "compact_face_fraction", operator.ge, 0.01),
    ("warm_heatmap_chart.jpg", "mean_saturation", operator.gt, 80),
    ("orange_area_chart.jpg", "mean_saturation", operator.gt, 60),
    ("compact_amber_heatmap.jpg", "largest_warm_component_fraction", operator.ge, 0.08),
    ("compact_amber_heatmap.jpg", "largest_warm_bbox_fraction", operator.le, 0.45),
    *(
        (filename, "largest_warm_bbox_fraction", operator.gt, 0.45)
        for filename in (
            "beige_text_slide_header.jpg",
            "beige_text_slide_letterbox.jpg",
            "beige_text_slide_rail.jpg",
            "orb_0652_closeup_talking_head.jpg",
        )
    ),
    ("orb_0652_closeup_talking_head.jpg", "largest_warm_component_occupancy", operator.ge, 0.45),
)


@pytest.mark.parametrize(
    ("filename", "feature", "compare", "bound"),
    FEATURE_BOUNDS,
    ids=[f"{name}-{feature}" for name, feature, _, _ in FEATURE_BOUNDS],
)
def test_feature_bound(filename, feature, compare, bound):
    value = getattr(analyze_frame(CORPUS / filename, FrameSelectionConfig()), feature)

    assert compare(value, bound), f"{filename} {feature}={value}"
