from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from video_research.adapters import (
    FixtureClaimExtractor,
    FixtureExtractionEngine,
    StructuralVerifier,
)
from video_research.frame_adapter import (
    FrameCandidate,
    FrameFeatures,
    FrameProbe,
    FrameSelectionConfig,
    FrameSelectionExtractionAdapter,
    PresentationSegment,
    analyze_frame,
    build_presentation_segments,
    probes_for_segment,
    select_frame,
)
from video_research.run import RunStatus
from video_research.skill import research_video
from video_research.timeline import VisualObservation

CORPUS = Path(__file__).parent / "fixtures" / "evidence_frames"


def test_labeled_regression_corpus_enforces_evidence_quality_contract():
    labels = json.loads((CORPUS / "labels.json").read_text(encoding="utf-8"))
    config = FrameSelectionConfig()

    for filename, label in labels.items():
        features = analyze_frame(CORPUS / filename, config)
        expected = label["expected"] == "keep"
        assert features.eligible is expected, (
            f"{filename} ({label['label']}) expected {label['expected']}, "
            f"got {features.rejection_reason or 'keep'}"
        )


def test_dark_colorful_chart_is_not_rejected_by_saturation():
    features = analyze_frame(CORPUS / "gex_0028_dark_colorful_chart.jpg", FrameSelectionConfig())

    assert features.mean_saturation > 100
    assert features.eligible


def test_text_card_with_webcam_pip_stays_eligible():
    features = analyze_frame(CORPUS / "orb_0730_face_dominant.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.largest_warm_component_fraction >= 0.03


def test_chart_with_webcam_pip_stays_eligible():
    features = analyze_frame(CORPUS / "chart_with_webcam_pip.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.largest_warm_component_fraction >= 0.01


def test_pure_talking_head_is_hard_dropped():
    features = analyze_frame(CORPUS / "orb_0652_talking_head.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_studio_talking_head_without_data_is_hard_dropped():
    features = analyze_frame(CORPUS / "studio_talking_head.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_small_face_without_data_is_hard_dropped():
    features = analyze_frame(CORPUS / "small_face_no_data.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_beige_text_slide_stays_eligible():
    features = analyze_frame(CORPUS / "beige_text_slide.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None


def test_office_wall_clutter_without_data_is_rejected():
    features = analyze_frame(CORPUS / "office_wall_clutter.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "no_evidence"


def test_blinds_talking_head_is_hard_dropped():
    features = analyze_frame(CORPUS / "blinds_talking_head.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_brick_talking_head_is_hard_dropped():
    features = analyze_frame(CORPUS / "brick_talking_head.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_edge_dense_non_data_static_is_rejected():
    features = analyze_frame(CORPUS / "edge_dense_static.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "no_evidence"


@pytest.mark.parametrize(
    ("filename", "reason"),
    (
        ("bookshelf_talking_head.jpg", "face_dominant"),
        ("bookshelf_only.jpg", "no_evidence"),
        ("vertical_blinds.jpg", "no_evidence"),
        ("vertical_blinds_talking_head.jpg", "face_dominant"),
        ("office_panel_talking_head.jpg", "face_dominant"),
        ("empty_whiteboard.jpg", "no_evidence"),
        ("empty_ceiling_grid.jpg", "no_evidence"),
        ("face_plus_ceiling_grid.jpg", "face_dominant"),
        ("foliage_only.jpg", "no_evidence"),
        ("foliage_dense.jpg", "no_evidence"),
        ("city_night_windows.jpg", "no_evidence"),
        ("app_icon_grid.jpg", "no_evidence"),
        ("sticky_note_wall.jpg", "face_dominant"),
        ("traffic_light_board.jpg", "no_evidence"),
        ("launchpad_with_labels.jpg", "no_evidence"),
        ("titled_sticky_wall.jpg", "no_evidence"),
        ("calendar_month_grid.jpg", "no_evidence"),
        ("piano_keys_vertical.jpg", "no_evidence"),
        ("zebra_vertical_stripes.jpg", "no_evidence"),
        ("face_plus_vertical_bars.jpg", "face_dominant"),
        ("logo_wall.jpg", "no_evidence"),
        ("led_dot_matrix.jpg", "no_evidence"),
        ("simple_map_outline.jpg", "no_evidence"),
        ("qr_module_grid.jpg", "no_evidence"),
        ("code_editor_stack.jpg", "no_evidence"),
        ("comic_panel_storyboard.jpg", "no_evidence"),
        ("blueprint_grid.jpg", "no_evidence"),
        ("crossword_grid.jpg", "no_evidence"),
        ("face_plus_comic_panels.jpg", "face_dominant"),
        ("barcode_sheet.jpg", "no_evidence"),
        ("face_plus_barcode.jpg", "face_dominant"),
        ("solid_color_blocks.jpg", "no_evidence"),
        ("stripe_color_bands.jpg", "no_evidence"),
        ("color_stall_grid.jpg", "no_evidence"),
        ("face_plus_color_stalls.jpg", "face_dominant"),
        ("busy_calendar_events.jpg", "no_evidence"),
        ("process_flowchart.jpg", "no_evidence"),
        ("pcb_trace_board.jpg", "no_evidence"),
        ("face_plus_busy_calendar.jpg", "face_dominant"),
        ("face_plus_flowchart.jpg", "face_dominant"),
        ("face_plus_pcb_traces.jpg", "face_dominant"),
        ("equalizer_spectrum_wall.jpg", "no_evidence"),
        ("unlabeled_band_wall.jpg", "no_evidence"),
        ("face_plus_equalizer.jpg", "face_dominant"),
        ("kanban_card_board.jpg", "no_evidence"),
        ("dense_kanban_board.jpg", "no_evidence"),
        ("labeled_kanban_board.jpg", "no_evidence"),
        ("face_plus_kanban.jpg", "face_dominant"),
        ("unlabeled_color_regions.jpg", "no_evidence"),
        ("industrial_panel_grid.jpg", "no_evidence"),
        ("appliance_keypad_grid.jpg", "no_evidence"),
        ("face_plus_keypad.jpg", "face_dominant"),
        ("face_plus_panel_grid.jpg", "face_dominant"),
        ("org_chart_boxes.jpg", "no_evidence"),
        ("decision_tree_boxes.jpg", "no_evidence"),
        ("er_entity_boxes.jpg", "no_evidence"),
        ("er_entity_dense.jpg", "no_evidence"),
        ("face_plus_org_chart.jpg", "face_dominant"),
        ("face_plus_decision_tree.jpg", "face_dominant"),
        ("face_plus_er_diagram.jpg", "face_dominant"),
    ),
)
def test_structured_non_data_backgrounds_are_rejected(filename, reason):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == reason


@pytest.mark.parametrize(
    ("filename", "reason"),
    (
        ("piano_keys_vertical.jpg", "no_evidence"),
        ("zebra_vertical_stripes.jpg", "no_evidence"),
    ),
)
def test_vertical_bar_strips_are_not_slide_text(filename, reason):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == reason


def test_face_plus_vertical_bars_talking_head_is_hard_dropped():
    features = analyze_frame(
        CORPUS / "face_plus_vertical_bars.jpg", FrameSelectionConfig()
    )

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"
    assert features.largest_warm_component_fraction >= 0.05


def test_empty_architectural_grid_is_not_chart_evidence():
    features = analyze_frame(CORPUS / "empty_ceiling_grid.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "no_evidence"


def test_face_plus_empty_grid_talking_head_is_hard_dropped():
    features = analyze_frame(
        CORPUS / "face_plus_ceiling_grid.jpg", FrameSelectionConfig()
    )

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"
    assert features.largest_warm_component_fraction >= 0.01


def test_gex_dark_chart_with_ordinary_webcam_pip_stays_eligible():
    features = analyze_frame(
        CORPUS / "gex_dark_chart_with_webcam_pip.jpg", FrameSelectionConfig()
    )

    assert features.eligible
    assert features.rejection_reason is None
    assert features.compact_face_fraction >= 0.01


def test_face_plus_barcode_talking_head_is_hard_dropped():
    features = analyze_frame(CORPUS / "face_plus_barcode.jpg", FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"
    assert features.compact_face_fraction >= 0.01


def test_full_plot_stacked_area_is_selectable_alone():
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"),
                CORPUS / "stacked_area_full_plot.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == "stacked_area_full_plot.jpg"
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    ("filename", "reason"),
    (
        ("foliage_only.jpg", "no_evidence"),
        ("foliage_dense.jpg", "no_evidence"),
        ("city_night_windows.jpg", "no_evidence"),
    ),
)
def test_non_data_organic_and_window_scenes_are_rejected(filename, reason):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == reason


@pytest.mark.parametrize(
    "filename",
    ("thin_candlestick_chart.jpg", "dark_candlestick_chart.jpg"),
)
def test_thin_candlestick_charts_stay_eligible(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None


@pytest.mark.parametrize(
    "filename",
    (
        "line_chart_multi_series.jpg",
        "pie_donut_chart.jpg",
        "stacked_bar_chart.jpg",
        "soft_orange_area_chart.jpg",
        "corporate_blue_area_chart.jpg",
        "simple_blue_histogram.jpg",
        "finance_volume_histogram.jpg",
        "box_whisker_chart.jpg",
        "labeled_treemap.jpg",
        "sparse_scatter_chart.jpg",
        "dense_numeric_table.jpg",
        "spreadsheet_grid.jpg",
        "funnel_chart.jpg",
        "stacked_area_full_plot.jpg",
        "dark_dashboard_bar.jpg",
        "light_dashboard_bar.jpg",
        "dark_multi_card_dashboard.jpg",
        "horizontal_bullet_kpi.jpg",
        "radar_spider_chart.jpg",
        "gauge_readout_chart.jpg",
        "kpi_sparkline_cards.jpg",
        "labeled_form_ui.jpg",
    ),
)
def test_ordinary_axis_aligned_charts_stay_eligible(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None


@pytest.mark.parametrize(
    "filename",
    (
        "app_icon_grid.jpg",
        "sticky_note_wall.jpg",
        "traffic_light_board.jpg",
        "launchpad_with_labels.jpg",
        "titled_sticky_wall.jpg",
        "calendar_month_grid.jpg",
        "solid_color_blocks.jpg",
        "barcode_sheet.jpg",
        "stripe_color_bands.jpg",
        "color_stall_grid.jpg",
    ),
)
def test_multicolor_tile_boards_without_chart_furniture_are_rejected(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason in {"no_evidence", "face_dominant"}


@pytest.mark.parametrize(
    "filename",
    ("soft_orange_area_chart.jpg", "corporate_blue_area_chart.jpg"),
)
def test_soft_mid_sat_area_charts_with_furniture_stay_eligible(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.mean_saturation < 80


@pytest.mark.parametrize(
    "filename",
    (
        "line_chart_multi_series.jpg",
        "pie_donut_chart.jpg",
        "stacked_bar_chart.jpg",
        "dark_theme_text_slide.jpg",
        "light_theme_text_slide.jpg",
        "soft_orange_area_chart.jpg",
        "corporate_blue_area_chart.jpg",
        "simple_blue_histogram.jpg",
        "finance_volume_histogram.jpg",
        "box_whisker_chart.jpg",
        "labeled_treemap.jpg",
        "sparse_scatter_chart.jpg",
        "dense_numeric_table.jpg",
        "spreadsheet_grid.jpg",
        "funnel_chart.jpg",
        "stacked_area_full_plot.jpg",
        "dark_dashboard_bar.jpg",
        "light_dashboard_bar.jpg",
        "dark_multi_card_dashboard.jpg",
        "horizontal_bullet_kpi.jpg",
        "radar_spider_chart.jpg",
        "gauge_readout_chart.jpg",
        "kpi_sparkline_cards.jpg",
        "labeled_form_ui.jpg",
    ),
)
def test_ordinary_chart_and_dark_slide_solos_are_observed(filename):
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / filename),),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == filename
    assert selection.observation is VisualObservation.OBSERVED


def test_dark_and_light_theme_text_slides_both_stay_eligible():
    config = FrameSelectionConfig()
    dark = analyze_frame(CORPUS / "dark_theme_text_slide.jpg", config)
    light = analyze_frame(CORPUS / "light_theme_text_slide.jpg", config)

    assert dark.eligible
    assert light.eligible
    assert dark.rejection_reason is None
    assert light.rejection_reason is None


def test_dark_and_light_theme_twins_are_both_selectable_evidence():
    selection = select_frame(
        PresentationSegment(0, 10_000),
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"),
                CORPUS / "dark_theme_text_slide.jpg",
            ),
            FrameCandidate(
                FrameProbe(2_000, "post_cut"),
                CORPUS / "light_theme_text_slide.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name in {
        "dark_theme_text_slide.jpg",
        "light_theme_text_slide.jpg",
    }
    assert selection.observation is VisualObservation.OBSERVED


def test_dark_and_light_dashboard_bar_twins_both_stay_eligible():
    config = FrameSelectionConfig()
    dark = analyze_frame(CORPUS / "dark_dashboard_bar.jpg", config)
    light = analyze_frame(CORPUS / "light_dashboard_bar.jpg", config)

    assert dark.eligible
    assert light.eligible
    assert dark.rejection_reason is None
    assert light.rejection_reason is None


def test_dark_and_light_dashboard_bar_twins_are_both_selectable_evidence():
    selection = select_frame(
        PresentationSegment(0, 10_000),
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"),
                CORPUS / "dark_dashboard_bar.jpg",
            ),
            FrameCandidate(
                FrameProbe(2_000, "post_cut"),
                CORPUS / "light_dashboard_bar.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name in {
        "dark_dashboard_bar.jpg",
        "light_dashboard_bar.jpg",
    }
    assert selection.observation is VisualObservation.OBSERVED


def test_face_plus_color_stalls_talking_head_is_hard_dropped():
    features = analyze_frame(
        CORPUS / "face_plus_color_stalls.jpg", FrameSelectionConfig()
    )

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"
    assert features.compact_face_fraction >= 0.01


@pytest.mark.parametrize(
    "filename",
    (
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
    ),
)
def test_face_plus_dense_nongraph_backgrounds_are_hard_dropped(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "face_dominant"
    assert features.compact_face_fraction >= 0.01


def test_horizontal_bullet_kpi_is_selectable_alone():
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"),
                CORPUS / "horizontal_bullet_kpi.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == "horizontal_bullet_kpi.jpg"
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    "filename",
    (
        "waterfall_bridge_chart.jpg",
        "gantt_timeline_chart.jpg",
    ),
)
def test_waterfall_and_gantt_charts_are_selectable_alone(filename):
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / filename),),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == filename
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    "filename",
    (
        "radar_spider_chart.jpg",
        "gauge_readout_chart.jpg",
        "kpi_sparkline_cards.jpg",
        "labeled_form_ui.jpg",
    ),
)
def test_labeled_radial_kpi_and_form_frames_are_selectable_alone(filename):
    selection = select_frame(
        PresentationSegment(0, 5_000),
        (FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / filename),),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == filename
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    "filename",
    (
        "equalizer_spectrum_wall.jpg",
        "unlabeled_band_wall.jpg",
        "kanban_card_board.jpg",
        "dense_kanban_board.jpg",
        "labeled_kanban_board.jpg",
        "unlabeled_color_regions.jpg",
        "industrial_panel_grid.jpg",
        "appliance_keypad_grid.jpg",
    ),
)
def test_furniture_free_bar_and_ui_chrome_are_rejected(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "no_evidence"


@pytest.mark.parametrize(
    "filename",
    (
        "org_chart_boxes.jpg",
        "decision_tree_boxes.jpg",
        "er_entity_boxes.jpg",
        "er_entity_dense.jpg",
    ),
)
def test_node_box_connector_diagrams_are_not_chart_evidence(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "no_evidence"


@pytest.mark.parametrize(
    "distractor_name",
    (
        "busy_calendar_events.jpg",
        "process_flowchart.jpg",
        "pcb_trace_board.jpg",
        "equalizer_spectrum_wall.jpg",
        "unlabeled_band_wall.jpg",
        "kanban_card_board.jpg",
        "dense_kanban_board.jpg",
        "labeled_kanban_board.jpg",
        "unlabeled_color_regions.jpg",
        "industrial_panel_grid.jpg",
        "appliance_keypad_grid.jpg",
        "org_chart_boxes.jpg",
        "decision_tree_boxes.jpg",
        "er_entity_boxes.jpg",
        "er_entity_dense.jpg",
    ),
)
def test_dense_nongraph_stable_pair_loses_to_later_settled_chart(distractor_name):
    selection = select_frame(
        PresentationSegment(0, 12_000),
        (
            FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / distractor_name),
            FrameCandidate(FrameProbe(1_500, "post_cut"), CORPUS / distractor_name),
            FrameCandidate(
                FrameProbe(8_000, "post_cut"),
                CORPUS / "gex_0028_dark_colorful_chart.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == "gex_0028_dark_colorful_chart.jpg"
    assert selection.observation is VisualObservation.OBSERVED


def test_warm_heatmap_chart_stays_eligible():
    features = analyze_frame(CORPUS / "warm_heatmap_chart.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.mean_saturation > 80


def test_orange_area_chart_stays_eligible():
    features = analyze_frame(CORPUS / "orange_area_chart.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.mean_saturation > 60


def test_compact_medium_sat_amber_heatmap_stays_eligible_despite_face_proxy():
    features = analyze_frame(CORPUS / "compact_amber_heatmap.jpg", FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.largest_warm_component_fraction >= 0.08
    assert features.largest_warm_bbox_fraction <= 0.45


@pytest.mark.parametrize(
    "filename",
    (
        "beige_text_slide_header.jpg",
        "beige_text_slide_letterbox.jpg",
        "beige_text_slide_rail.jpg",
    ),
)
def test_beige_text_slide_layouts_stay_eligible(filename):
    features = analyze_frame(CORPUS / filename, FrameSelectionConfig())

    assert features.eligible
    assert features.rejection_reason is None
    assert features.largest_warm_bbox_fraction > 0.45


def test_closeup_talking_head_cannot_escape_face_dominance_bbox_limit():
    features = analyze_frame(
        CORPUS / "orb_0652_closeup_talking_head.jpg", FrameSelectionConfig()
    )

    assert features.largest_warm_bbox_fraction > 0.45
    assert features.largest_warm_component_occupancy >= 0.45
    assert not features.eligible
    assert features.rejection_reason == "face_dominant"


def test_settled_slide_wins_over_boundary_talking_head():
    config = FrameSelectionConfig()
    segment = PresentationSegment(412_000, 416_000)
    candidates = (
        FrameCandidate(FrameProbe(412_000, "boundary"), CORPUS / "orb_0652_talking_head.jpg"),
        FrameCandidate(FrameProbe(414_000, "post_cut"), CORPUS / "orb_0654_settled_slide.jpg"),
    )

    selection = select_frame(segment, candidates, config)

    assert selection.selected is not None
    assert selection.selected.probe.timestamp_ms == 414_000
    assert selection.observation is VisualObservation.OBSERVED
    assert selection.manifest()["selected_timestamp_ms"] == 414_000


def test_clean_slide_beats_text_card_with_webcam_pip():
    config = FrameSelectionConfig()
    segment = PresentationSegment(450_000, 455_000)
    candidates = (
        FrameCandidate(
            FrameProbe(450_500, "post_cut"), CORPUS / "orb_0730_face_dominant.jpg"
        ),
        FrameCandidate(
            FrameProbe(452_000, "post_cut"), CORPUS / "orb_0654_settled_slide.jpg"
        ),
    )

    selection = select_frame(segment, candidates, config)

    assert selection.selected is not None
    assert selection.selected.path.name == "orb_0654_settled_slide.jpg"


def test_mixed_chart_pip_is_selectable_when_it_is_the_only_evidence():
    segment = PresentationSegment(28_000, 32_000)
    selection = select_frame(
        segment,
        (
            FrameCandidate(
                FrameProbe(28_500, "post_cut"), CORPUS / "chart_with_webcam_pip.jpg"
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == "chart_with_webcam_pip.jpg"
    assert selection.observation is VisualObservation.OBSERVED


def test_gex_dark_chart_with_webcam_pip_is_selectable_alone():
    segment = PresentationSegment(28_000, 32_000)
    selection = select_frame(
        segment,
        (
            FrameCandidate(
                FrameProbe(28_500, "post_cut"),
                CORPUS / "gex_dark_chart_with_webcam_pip.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == "gex_dark_chart_with_webcam_pip.jpg"
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    "evidence_name",
    (
        "beige_text_slide_header.jpg",
        "volatility_0058_bright_slide.jpg",
        "chart_with_webcam_pip.jpg",
        "warm_heatmap_chart.jpg",
        "orange_area_chart.jpg",
        "compact_amber_heatmap.jpg",
        "orb_0730_face_dominant.jpg",
        "line_chart_multi_series.jpg",
        "pie_donut_chart.jpg",
        "stacked_bar_chart.jpg",
        "dark_theme_text_slide.jpg",
        "light_theme_text_slide.jpg",
        "soft_orange_area_chart.jpg",
        "corporate_blue_area_chart.jpg",
        "simple_blue_histogram.jpg",
        "finance_volume_histogram.jpg",
        "box_whisker_chart.jpg",
        "labeled_treemap.jpg",
        "sparse_scatter_chart.jpg",
        "dense_numeric_table.jpg",
        "spreadsheet_grid.jpg",
        "funnel_chart.jpg",
        "stacked_area_full_plot.jpg",
        "waterfall_bridge_chart.jpg",
        "gantt_timeline_chart.jpg",
    ),
)
def test_non_evidence_office_clutter_loses_to_settled_evidence(evidence_name):
    segment = PresentationSegment(0, 10_000)
    selection = select_frame(
        segment,
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"), CORPUS / "office_wall_clutter.jpg"
            ),
            FrameCandidate(FrameProbe(2_000, "post_cut"), CORPUS / evidence_name),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == evidence_name
    assert selection.observation is VisualObservation.OBSERVED


@pytest.mark.parametrize(
    "distractor_name",
    (
        "blinds_talking_head.jpg",
        "brick_talking_head.jpg",
        "edge_dense_static.jpg",
        "bookshelf_talking_head.jpg",
        "bookshelf_only.jpg",
        "vertical_blinds.jpg",
        "vertical_blinds_talking_head.jpg",
        "office_panel_talking_head.jpg",
        "empty_whiteboard.jpg",
        "empty_ceiling_grid.jpg",
        "face_plus_ceiling_grid.jpg",
        "foliage_only.jpg",
        "foliage_dense.jpg",
        "city_night_windows.jpg",
        "app_icon_grid.jpg",
        "sticky_note_wall.jpg",
        "traffic_light_board.jpg",
        "launchpad_with_labels.jpg",
        "titled_sticky_wall.jpg",
        "calendar_month_grid.jpg",
        "piano_keys_vertical.jpg",
        "zebra_vertical_stripes.jpg",
        "face_plus_vertical_bars.jpg",
        "logo_wall.jpg",
        "led_dot_matrix.jpg",
        "simple_map_outline.jpg",
        "qr_module_grid.jpg",
        "code_editor_stack.jpg",
        "comic_panel_storyboard.jpg",
        "blueprint_grid.jpg",
        "crossword_grid.jpg",
        "face_plus_comic_panels.jpg",
        "barcode_sheet.jpg",
        "face_plus_barcode.jpg",
        "solid_color_blocks.jpg",
        "stripe_color_bands.jpg",
        "color_stall_grid.jpg",
        "face_plus_color_stalls.jpg",
        "busy_calendar_events.jpg",
        "process_flowchart.jpg",
        "pcb_trace_board.jpg",
        "face_plus_busy_calendar.jpg",
        "face_plus_flowchart.jpg",
        "face_plus_pcb_traces.jpg",
        "equalizer_spectrum_wall.jpg",
        "unlabeled_band_wall.jpg",
        "face_plus_equalizer.jpg",
        "kanban_card_board.jpg",
        "dense_kanban_board.jpg",
        "labeled_kanban_board.jpg",
        "face_plus_kanban.jpg",
        "unlabeled_color_regions.jpg",
        "industrial_panel_grid.jpg",
        "appliance_keypad_grid.jpg",
        "face_plus_keypad.jpg",
        "face_plus_panel_grid.jpg",
        "org_chart_boxes.jpg",
        "decision_tree_boxes.jpg",
        "er_entity_boxes.jpg",
        "er_entity_dense.jpg",
        "face_plus_org_chart.jpg",
        "face_plus_decision_tree.jpg",
        "face_plus_er_diagram.jpg",
    ),
)
@pytest.mark.parametrize(
    "evidence_name",
    (
        "gex_0028_dark_colorful_chart.jpg",
        "beige_text_slide.jpg",
        "beige_text_slide_header.jpg",
        "chart_with_webcam_pip.jpg",
        "gex_dark_chart_with_webcam_pip.jpg",
        "volatility_0058_bright_slide.jpg",
        "thin_candlestick_chart.jpg",
        "line_chart_multi_series.jpg",
        "pie_donut_chart.jpg",
        "stacked_bar_chart.jpg",
        "dark_theme_text_slide.jpg",
        "soft_orange_area_chart.jpg",
        "corporate_blue_area_chart.jpg",
        "simple_blue_histogram.jpg",
        "finance_volume_histogram.jpg",
        "box_whisker_chart.jpg",
        "labeled_treemap.jpg",
        "sparse_scatter_chart.jpg",
        "dense_numeric_table.jpg",
        "spreadsheet_grid.jpg",
        "funnel_chart.jpg",
        "stacked_area_full_plot.jpg",
        "dark_dashboard_bar.jpg",
        "light_dashboard_bar.jpg",
        "dark_multi_card_dashboard.jpg",
        "horizontal_bullet_kpi.jpg",
        "radar_spider_chart.jpg",
        "gauge_readout_chart.jpg",
        "kpi_sparkline_cards.jpg",
        "labeled_form_ui.jpg",
        "waterfall_bridge_chart.jpg",
        "gantt_timeline_chart.jpg",
    ),
)
def test_structured_background_non_data_loses_to_settled_evidence(
    distractor_name, evidence_name
):
    segment = PresentationSegment(0, 10_000)
    selection = select_frame(
        segment,
        (
            FrameCandidate(FrameProbe(500, "post_cut"), CORPUS / distractor_name),
            FrameCandidate(FrameProbe(2_000, "post_cut"), CORPUS / evidence_name),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is not None
    assert selection.selected.path.name == evidence_name
    assert selection.observation is VisualObservation.OBSERVED


def test_clean_preference_ignores_noncompact_warm_slide_fill(tmp_path):
    """Clean preference uses compact face/PIP mass, not non-compact warm fills."""

    pip = tmp_path / "pip.png"
    slide = tmp_path / "slide.png"
    Image.new("RGB", (32, 32), "navy").save(pip)
    Image.new("RGB", (32, 32), "white").save(slide)
    selection = select_frame(
        PresentationSegment(0, 2_000),
        (
            FrameCandidate(
                FrameProbe(500, "post_cut"),
                pip,
                features=_eligible_features(0.95, warm_component=0.02, compact_face=0.02),
            ),
            FrameCandidate(
                FrameProbe(1_000, "post_cut"),
                slide,
                # Large warm fill (beige slide) but no compact face/PIP mass.
                features=_eligible_features(0.70, warm_component=0.70, compact_face=0.0),
            ),
        ),
        replace(FrameSelectionConfig(), stable_difference=1_000.0),
    )

    assert selection.selected is not None
    assert selection.selected.path == slide


def test_all_rejected_candidates_leave_visual_unobserved():
    segment = PresentationSegment(412_000, 415_000)
    selection = select_frame(
        segment,
        (
            FrameCandidate(
                FrameProbe(412_500, "post_cut"), CORPUS / "orb_0652_talking_head.jpg"
            ),
            FrameCandidate(
                FrameProbe(413_000, "post_cut"),
                CORPUS / "orb_0652_closeup_talking_head.jpg",
            ),
        ),
        FrameSelectionConfig(),
    )

    assert selection.selected is None
    assert selection.reason == "no_eligible_candidate"
    assert selection.observation is VisualObservation.UNOBSERVED


def test_rejected_corpus_frame_degrades_public_run_to_partial(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "talk_benchmark.json"
    delegate = FixtureExtractionEngine(fixture)

    def selections(source):
        accepted = CORPUS / "orb_0654_settled_slide.jpg"
        rejected = CORPUS / "orb_0652_talking_head.jpg"
        results = []
        for index, window in enumerate(source.windows):
            segment = PresentationSegment(window.interval.start_ms, window.interval.end_ms)
            path = rejected if index == len(source.windows) - 1 else accepted
            results.append(
                select_frame(
                    segment,
                    (FrameCandidate(FrameProbe(segment.start_ms + 500, "post_cut"), path),),
                    FrameSelectionConfig(),
                )
            )
        return tuple(results)

    engine = FrameSelectionExtractionAdapter(delegate, selections)
    extracted = engine.extract(str(fixture))
    pack = research_video(
        str(fixture),
        engine=engine,
        claim_extractor=FixtureClaimExtractor(fixture),
        verifier=StructuralVerifier(),
        output_dir=tmp_path / "pack",
        run_id="run-frame-selection",
        created_at="2026-08-19T00:00:00+00:00",
    )

    assert pack.status is RunStatus.PARTIAL
    assert all(frame.interval.start_ms < 450_000 for frame in extracted.frames)
    assert pack.coverage.windows[-1].visual is VisualObservation.UNOBSERVED
    assert any(record.gate_id == "G4" and record.outcome == "fail" for record in pack.run.gates)


def test_scene_cuts_form_contiguous_presentation_segments():
    segments = build_presentation_segments([1_800, 1_000, 1_800], 4_000)

    assert segments == (
        PresentationSegment(0, 1_000),
        PresentationSegment(1_000, 1_800),
        PresentationSegment(1_800, 4_000),
    )


def test_rapid_cut_uses_midpoint_without_crossing_next_segment():
    segment = PresentationSegment(1_000, 1_400)

    probes = probes_for_segment(segment, FrameSelectionConfig())

    assert probes == (FrameProbe(1_200, "short_segment_midpoint"),)
    assert all(segment.start_ms <= probe.timestamp_ms < segment.end_ms for probe in probes)


def test_no_cut_segment_gets_periodic_probes_for_later_visuals():
    (segment,) = build_presentation_segments([], 46_000)

    timestamps = [
        probe.timestamp_ms for probe in probes_for_segment(segment, FrameSelectionConfig())
    ]

    assert timestamps[:3] == [500, 1_000, 2_000]
    assert 15_000 in timestamps
    assert 30_000 in timestamps
    assert 45_000 in timestamps


def test_claim_aligned_probe_stays_inside_its_presentation_segment():
    segment = PresentationSegment(10_000, 12_000)

    probes = probes_for_segment(segment, FrameSelectionConfig(), (9_000, 11_250, 12_500))

    assert FrameProbe(11_250, "claim_aligned") in probes
    assert all(segment.start_ms < probe.timestamp_ms < segment.end_ms for probe in probes)


def test_never_stable_animation_chooses_best_eligible_without_hanging(tmp_path):
    paths = []
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        path = tmp_path / f"moving-{index}.png"
        Image.new("RGB", (32, 32), color).save(path)
        paths.append(path)
    scores = (0.4, 0.9, 0.6)
    candidates = tuple(
        FrameCandidate(
            FrameProbe((index + 1) * 500, "post_cut"),
            path,
            features=_eligible_features(score),
        )
        for index, (path, score) in enumerate(zip(paths, scores, strict=True))
    )
    config = replace(FrameSelectionConfig(), stable_difference=0.0)

    selection = select_frame(PresentationSegment(0, 3_000), candidates, config)

    assert selection.selected is not None
    assert selection.selected.probe.timestamp_ms == 1_000
    assert selection.reason == "highest_quality_eligible"


def test_clean_candidate_beats_small_face_pip_even_when_pip_is_earlier(tmp_path):
    pip = tmp_path / "pip.png"
    clean = tmp_path / "clean.png"
    Image.new("RGB", (32, 32), "navy").save(pip)
    Image.new("RGB", (32, 32), "white").save(clean)
    candidates = (
        FrameCandidate(
            FrameProbe(500, "post_cut"),
            pip,
            features=_eligible_features(0.95, warm_component=0.02),
        ),
        FrameCandidate(
            FrameProbe(1_000, "post_cut"), clean, features=_eligible_features(0.70)
        ),
    )
    config = replace(FrameSelectionConfig(), stable_difference=1_000.0)

    selection = select_frame(PresentationSegment(0, 2_000), candidates, config)

    assert selection.selected is not None
    assert selection.selected.path == clean


def test_blank_frame_is_rejected(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 180), (2, 2, 2)).save(blank)

    features = analyze_frame(blank, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "blank_or_transition"


@pytest.mark.parametrize("kind", ["fade", "blur"])
def test_fade_and_blur_are_rejected_as_transitions(tmp_path, kind):
    path = tmp_path / f"{kind}.png"
    if kind == "fade":
        image = Image.new("RGB", (320, 180), (80, 80, 80))
    else:
        image = Image.new("RGB", (320, 180), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 40, 220, 140), fill="white")
        image = image.filter(ImageFilter.GaussianBlur(40))
    image.save(path)

    features = analyze_frame(path, FrameSelectionConfig())

    assert not features.eligible
    assert features.rejection_reason == "blank_or_transition"


def test_invalid_duration_is_rejected():
    with pytest.raises(ValueError, match="duration_ms must be positive"):
        build_presentation_segments([], 0)


def _eligible_features(
    score: float, warm_component: float = 0.0, compact_face: float | None = None
) -> FrameFeatures:
    pip = warm_component if compact_face is None else compact_face
    return FrameFeatures(
        variance=100.0,
        edge_fraction=0.1,
        mean_saturation=50.0,
        warm_fraction=0.0,
        largest_warm_component_fraction=warm_component,
        largest_warm_bbox_fraction=warm_component,
        largest_warm_component_occupancy=1.0 if warm_component else 0.0,
        compact_face_fraction=pip,
        evidence_score=score,
        eligible=True,
    )
