"""Impure Evidence Frame selection behind the extraction port.

Scene changes are candidate triggers, not evidence timestamps.  This adapter
turns scene-bound Presentation Segments into bounded probes, scores the decoded
images, and either selects one settled frame with provenance or rejects the
segment explicitly.  It never decides run status; callers map a rejection to an
unobserved visual window and the existing gates fail closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from .ports import ExtractedSource, ExtractionEngine, ExtractionError
from .timeline import SourceSpan, SpanKind, TimeInterval, VisualObservation


@dataclass(frozen=True)
class FrameSelectionConfig:
    """Versioned, immutable frame-selection policy."""

    version: str = "evidence-frame-v4"
    probe_offsets_ms: tuple[int, ...] = (500, 1_000, 2_000)
    next_cut_guard_ms: int = 100
    periodic_interval_ms: int = 15_000
    analysis_size: tuple[int, int] = (160, 90)
    min_variance: float = 35.0
    min_edge_fraction: float = 0.02
    edge_threshold: int = 24
    strong_edge_threshold: int = 55
    face_component_min_fraction: float = 0.01
    face_component_max_bbox_fraction: float = 0.45
    face_component_min_occupancy: float = 0.40
    face_internal_edge_fraction: float = 0.08
    face_internal_variance: float = 250.0
    face_primary_mass_fraction: float = 0.08
    face_primary_largest_fraction: float = 0.12
    small_face_component_fraction: float = 0.01
    evidence_canvas_with_text_fraction: float = 0.28
    evidence_text_on_canvas_fraction: float = 0.045
    evidence_lowsat_strong_edge_fraction: float = 0.12
    evidence_highsat_strong_edge_fraction: float = 0.08
    evidence_canvas_with_structure_fraction: float = 0.40
    evidence_structure_edge_fraction: float = 0.08
    skin_max_saturation: float = 0.62
    mixed_face_score_penalty: float = 0.12
    face_primary_score_penalty: float = 0.25
    mixed_face_score_ceiling: float = 0.75
    stable_difference: float = 18.0

    def manifest(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PresentationSegment:
    """One scene-bound interval, in canonical integer milliseconds."""

    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("presentation segment must be a positive interval")


@dataclass(frozen=True)
class FrameProbe:
    timestamp_ms: int
    method: str


@dataclass(frozen=True)
class FrameFeatures:
    variance: float
    edge_fraction: float
    mean_saturation: float
    warm_fraction: float
    largest_warm_component_fraction: float
    largest_warm_bbox_fraction: float
    largest_warm_component_occupancy: float
    compact_face_fraction: float
    evidence_score: float
    eligible: bool
    rejection_reason: str | None = None

    def manifest(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FrameCandidate:
    probe: FrameProbe
    path: Path
    features: FrameFeatures | None = None
    stability_to_next: float | None = None


@dataclass(frozen=True)
class CandidateEvaluation:
    probe: FrameProbe
    path: Path
    features: FrameFeatures
    stability_to_next: float | None

    def manifest(self, segment: PresentationSegment) -> dict[str, object]:
        return {
            "boundary_ms": segment.start_ms,
            "segment_end_ms": segment.end_ms,
            "timestamp_ms": self.probe.timestamp_ms,
            "settle_offset_ms": self.probe.timestamp_ms - segment.start_ms,
            "candidate_method": self.probe.method,
            "path": self.path.name,
            "features": self.features.manifest(),
            "stability_to_next": self.stability_to_next,
        }


class FrameSelectionExtractionAdapter:
    """Apply frame-selection results at the public extraction boundary.

    The delegate still owns transcript and source extraction.  The provider
    returns one selection for each canonical coverage window, in timeline order;
    this adapter replaces the delegate's visual claims with only those frames
    the evidence-quality policy accepted.
    """

    def __init__(
        self,
        delegate: ExtractionEngine,
        selection_provider: Callable[[ExtractedSource], tuple[FrameSelection, ...]],
    ) -> None:
        self.delegate = delegate
        self.selection_provider = selection_provider

    def describe(self, source_ref: str):
        return self.delegate.describe(source_ref)

    def extract(self, source_ref: str) -> ExtractedSource:
        source = self.delegate.extract(source_ref)
        return apply_frame_selections(source, self.selection_provider(source))


def apply_frame_selections(
    source: ExtractedSource, selections: tuple[FrameSelection, ...]
) -> ExtractedSource:
    """Map accepted Evidence Frames into canonical visual coverage.

    A rejected Presentation Segment maps to ``UNOBSERVED``.  Cardinality and
    interval mismatches raise ``ExtractionError`` instead of preserving a stale
    visual observation from the delegate.
    """

    if len(selections) != len(source.windows):
        raise ExtractionError("frame selection count does not match canonical coverage windows")

    windows = []
    frames = []
    for window, selection in zip(source.windows, selections, strict=True):
        if (
            selection.segment.start_ms != window.interval.start_ms
            or selection.segment.end_ms != window.interval.end_ms
        ):
            raise ExtractionError(
                "frame selection interval does not match canonical coverage window"
            )
        windows.append(
            replace(
                window,
                visual=selection.observation,
                extraction_method=f"frame-selection:{selection.config_version}",
            )
        )
        if selection.selected is None:
            continue
        timestamp_ms = selection.selected.probe.timestamp_ms
        if not window.interval.contains(timestamp_ms):
            raise ExtractionError("selected frame falls outside its coverage window")
        frames.append(
            SourceSpan(
                kind=SpanKind.VISUAL,
                interval=TimeInterval(timestamp_ms, min(timestamp_ms + 1, window.interval.end_ms)),
                artifact_id=selection.selected.path.name,
                raw_timestamp=f"{timestamp_ms / 1_000:.3f}",
            )
        )

    return replace(source, windows=tuple(windows), frames=tuple(frames))


@dataclass(frozen=True)
class FrameSelection:
    segment: PresentationSegment
    selected: CandidateEvaluation | None
    evaluations: tuple[CandidateEvaluation, ...] = field(default_factory=tuple)
    reason: str = ""
    config_version: str = "evidence-frame-v4"

    @property
    def observation(self) -> VisualObservation:
        """A rejection is never allowed to masquerade as visual observation."""

        if self.selected is None:
            return VisualObservation.UNOBSERVED
        return VisualObservation.OBSERVED

    def manifest(self) -> dict[str, object]:
        return {
            "boundary_ms": self.segment.start_ms,
            "segment_end_ms": self.segment.end_ms,
            "selected_timestamp_ms": (
                self.selected.probe.timestamp_ms if self.selected is not None else None
            ),
            "reason": self.reason,
            "config_version": self.config_version,
            "candidates": [item.manifest(self.segment) for item in self.evaluations],
        }


def build_presentation_segments(
    scene_timestamps_ms: list[int] | tuple[int, ...], duration_ms: int
) -> tuple[PresentationSegment, ...]:
    """Partition the source at scene cuts without trusting input order."""

    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    cuts = sorted({cut for cut in scene_timestamps_ms if 0 < cut < duration_ms})
    boundaries = (0, *cuts, duration_ms)
    return tuple(PresentationSegment(start, end) for start, end in pairwise(boundaries))


def probes_for_segment(
    segment: PresentationSegment,
    config: FrameSelectionConfig,
    claim_timestamps_ms: tuple[int, ...] = (),
) -> tuple[FrameProbe, ...]:
    """Return bounded settle and periodic probes that never cross the segment."""

    latest = segment.end_ms - config.next_cut_guard_ms
    if latest <= segment.start_ms:
        midpoint = segment.start_ms + (segment.end_ms - segment.start_ms) // 2
        return (FrameProbe(midpoint, "short_segment_midpoint"),)

    probes: dict[int, str] = {}
    for offset in config.probe_offsets_ms:
        timestamp = segment.start_ms + offset
        if timestamp <= latest:
            probes[timestamp] = "post_cut"

    for timestamp in claim_timestamps_ms:
        if segment.start_ms < timestamp <= latest:
            probes[timestamp] = "claim_aligned"

    periodic = segment.start_ms + config.periodic_interval_ms
    while periodic <= latest:
        probes.setdefault(periodic, "periodic")
        periodic += config.periodic_interval_ms

    if not probes:
        midpoint = segment.start_ms + (segment.end_ms - segment.start_ms) // 2
        probes[min(midpoint, latest)] = "short_segment_midpoint"
    return tuple(FrameProbe(timestamp, probes[timestamp]) for timestamp in sorted(probes))


def analyze_frame(path: Path, config: FrameSelectionConfig) -> FrameFeatures:
    """Measure bounded full-frame evidence and face-proxy signals.

    Every eligible frame needs positive chart/slide/text/UI structure. Talking
    heads and non-evidence clutter are hard-dropped; mixed evidence-plus-PIP
    stays eligible with a face penalty so clean peers win when present.
    """

    with Image.open(path) as source:
        image = source.convert("RGB").resize(config.analysis_size)

    grayscale = image.convert("L")
    gray_values = list(grayscale.get_flattened_data())
    variance = float(ImageStat.Stat(grayscale).var[0])
    hsv = image.convert("HSV")
    saturation_channel = list(hsv.split()[1].get_flattened_data())
    saturation = float(sum(saturation_channel) / len(saturation_channel))
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    edge_values = list(edges.get_flattened_data())
    width, height = image.size
    frame_area = width * height
    interior_indexes = [y * width + x for y in range(1, height - 1) for x in range(1, width - 1)]
    edge_fraction = sum(
        edge_values[index] > config.edge_threshold for index in interior_indexes
    ) / len(interior_indexes)

    warm_mask = tuple(
        _is_skin_tone(pixel, config.skin_max_saturation) for pixel in image.get_flattened_data()
    )
    warm_fraction = sum(warm_mask) / len(warm_mask)
    face_regions = _face_like_regions(warm_mask, gray_values, edge_values, width, height, config)
    compact_face_regions = tuple(
        region
        for region in face_regions
        if region.bbox_fraction <= config.face_component_max_bbox_fraction
    )
    component_fraction, bbox_fraction, component_occupancy = _largest_region_stats(face_regions)
    face_mass = sum(region.fraction for region in face_regions)
    compact_face_fraction, _, _ = _largest_region_stats(compact_face_regions)
    face_mask = _region_bbox_mask(compact_face_regions, width, height, frame_area)
    face_primary = face_mass >= config.face_primary_mass_fraction or (
        face_mass > 0.0 and component_fraction >= config.face_primary_largest_fraction
    )
    has_face = face_mass >= config.small_face_component_fraction
    has_evidence = _has_evidence_structure(
        gray_values,
        edge_values,
        saturation_channel,
        warm_mask,
        face_mask,
        interior_indexes,
        width,
        face_primary,
        has_face,
        config,
    )
    blank_or_transition = variance < config.min_variance or edge_fraction < config.min_edge_fraction
    if blank_or_transition:
        rejection = "blank_or_transition"
    elif not has_evidence:
        rejection = "face_dominant" if has_face else "no_evidence"
    else:
        rejection = None

    structure = min(edge_fraction / 0.15, 1.0)
    contrast = min(variance / 3_000.0, 1.0)
    non_face = 1.0 - min(warm_fraction, 0.5)
    evidence_score = 0.55 * structure + 0.30 * contrast + 0.15 * non_face
    if rejection is None and has_face:
        if face_primary:
            evidence_score = (
                min(evidence_score, config.mixed_face_score_ceiling)
                - config.face_primary_score_penalty
            )
        else:
            evidence_score = (
                min(evidence_score, config.mixed_face_score_ceiling)
                - config.mixed_face_score_penalty
            )

    return FrameFeatures(
        variance=round(variance, 3),
        edge_fraction=round(edge_fraction, 6),
        mean_saturation=round(saturation, 3),
        warm_fraction=round(warm_fraction, 6),
        largest_warm_component_fraction=round(component_fraction, 6),
        largest_warm_bbox_fraction=round(bbox_fraction, 6),
        largest_warm_component_occupancy=round(component_occupancy, 6),
        compact_face_fraction=round(compact_face_fraction, 6),
        evidence_score=round(max(evidence_score, 0.0), 6),
        eligible=rejection is None,
        rejection_reason=rejection,
    )


def select_frame(
    segment: PresentationSegment,
    candidates: list[FrameCandidate] | tuple[FrameCandidate, ...],
    config: FrameSelectionConfig,
) -> FrameSelection:
    """Choose the earliest stable eligible frame, then best eligible fallback."""

    ordered = sorted(candidates, key=lambda candidate: candidate.probe.timestamp_ms)
    features = [
        candidate.features or analyze_frame(candidate.path, config) for candidate in ordered
    ]
    stability = [
        frame_difference(ordered[index].path, ordered[index + 1].path, config)
        for index in range(len(ordered) - 1)
    ]
    evaluations = tuple(
        CandidateEvaluation(
            probe=candidate.probe,
            path=candidate.path,
            features=features[index],
            stability_to_next=stability[index] if index < len(stability) else None,
        )
        for index, candidate in enumerate(ordered)
    )
    eligible = [item for item in evaluations if item.features.eligible]
    if not eligible:
        return FrameSelection(
            segment=segment,
            selected=None,
            evaluations=evaluations,
            reason="no_eligible_candidate",
            config_version=config.version,
        )

    clean = [
        item
        for item in eligible
        if item.features.compact_face_fraction < config.small_face_component_fraction
    ]
    preferred = clean or eligible
    preferred_ids = {id(item) for item in preferred}
    stable = [
        item
        for index, item in enumerate(evaluations[:-1])
        if id(item) in preferred_ids
        and id(evaluations[index + 1]) in preferred_ids
        and item.stability_to_next is not None
        and item.stability_to_next <= config.stable_difference
    ]
    if stable:
        selected = stable[0]
        reason = "earliest_stable_eligible"
    else:
        selected = max(
            preferred,
            key=lambda item: (item.features.evidence_score, -item.probe.timestamp_ms),
        )
        reason = "highest_quality_eligible"
    return FrameSelection(segment, selected, evaluations, reason, config.version)


def frame_difference(left: Path, right: Path, config: FrameSelectionConfig) -> float:
    """Mean grayscale difference on the same bounded grid."""

    with Image.open(left) as left_source, Image.open(right) as right_source:
        left_pixels = list(
            left_source.convert("L").resize(config.analysis_size).get_flattened_data()
        )
        right_pixels = list(
            right_source.convert("L").resize(config.analysis_size).get_flattened_data()
        )
    return round(
        sum(abs(a - b) for a, b in zip(left_pixels, right_pixels, strict=True)) / len(left_pixels),
        3,
    )


def _is_skin_tone(pixel: tuple[int, int, int], max_saturation: float = 0.62) -> bool:
    """RGB skin proxy that excludes hot chart/UI ink."""

    red, green, blue = pixel
    max_c = max(pixel)
    min_c = min(pixel)
    if max_c == 0:
        return False
    saturation = (max_c - min_c) / max_c
    return (
        red > 95
        and green > 40
        and blue > 20
        and max_c - min_c > 15
        and abs(red - green) > 15
        and red > green
        and red > blue
        and saturation <= max_saturation
    )


@dataclass(frozen=True)
class _FaceRegion:
    indexes: tuple[int, ...]
    fraction: float
    bbox_fraction: float
    occupancy: float
    min_x: int
    max_x: int
    min_y: int
    max_y: int


def _connected_components(mask: tuple[bool, ...], width: int, height: int) -> list[list[int]]:
    seen: set[int] = set()
    components: list[list[int]] = []
    for index, active in enumerate(mask):
        if not active or index in seen:
            continue
        component: list[int] = []
        pending = [index]
        seen.add(index)
        while pending:
            current = pending.pop()
            component.append(current)
            x = current % width
            y = current // width
            neighbors = (
                current - 1 if x else -1,
                current + 1 if x < width - 1 else -1,
                current - width if y else -1,
                current + width if y < height - 1 else -1,
            )
            for neighbor in neighbors:
                if neighbor >= 0 and mask[neighbor] and neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        components.append(component)
    return components


def _face_like_regions(
    warm_mask: tuple[bool, ...],
    gray_values: list[int],
    edge_values: list[int],
    width: int,
    height: int,
    config: FrameSelectionConfig,
) -> tuple[_FaceRegion, ...]:
    """Filled, textured warm regions that may be faces (compact or closeup)."""

    frame_area = width * height
    regions: list[_FaceRegion] = []
    for component in _connected_components(warm_mask, width, height):
        fraction = len(component) / frame_area
        if fraction < config.face_component_min_fraction:
            continue
        xs = [index % width for index in component]
        ys = [index // width for index in component]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bbox_area = (max_x - min_x + 1) * (max_y - min_y + 1)
        bbox_fraction = bbox_area / frame_area
        occupancy = len(component) / bbox_area
        if occupancy < config.face_component_min_occupancy:
            continue
        internal_edges = sum(
            edge_values[index] > config.edge_threshold for index in component
        ) / len(component)
        mean_gray = sum(gray_values[index] for index in component) / len(component)
        internal_variance = sum((gray_values[index] - mean_gray) ** 2 for index in component) / len(
            component
        )
        textured = (
            internal_edges >= config.face_internal_edge_fraction
            or internal_variance >= config.face_internal_variance
        )
        if not textured:
            continue
        bbox_w = max_x - min_x + 1
        bbox_h = max_y - min_y + 1
        aspect = bbox_w / max(bbox_h, 1)
        # Wide/tall chart bands and area strips are not face-like.
        if aspect >= 2.4 or aspect <= 0.35:
            continue
        regions.append(
            _FaceRegion(
                indexes=tuple(component),
                fraction=fraction,
                bbox_fraction=bbox_fraction,
                occupancy=occupancy,
                min_x=min_x,
                max_x=max_x,
                min_y=min_y,
                max_y=max_y,
            )
        )
    return tuple(sorted(regions, key=lambda region: region.fraction, reverse=True))


def _largest_region_stats(
    regions: tuple[_FaceRegion, ...],
) -> tuple[float, float, float]:
    if not regions:
        return 0.0, 0.0, 0.0
    largest = regions[0]
    return largest.fraction, largest.bbox_fraction, largest.occupancy


def _region_bbox_mask(
    regions: tuple[_FaceRegion, ...], width: int, height: int, frame_area: int
) -> list[bool]:
    mask = [False] * frame_area
    for region in regions:
        for y in range(region.min_y, region.max_y + 1):
            row = y * width
            for x in range(region.min_x, region.max_x + 1):
                mask[row + x] = True
    return mask


def _is_canvas_pixel(
    index: int,
    gray_values: list[int],
    edge_values: list[int],
    saturation_values: list[int],
    warm_mask: tuple[bool, ...],
    face_mask: list[bool],
) -> bool:
    """Flat non-face backdrop, including warm beige slide fills outside faces."""

    if face_mask[index] or edge_values[index] >= 12:
        return False
    if warm_mask[index]:
        return True
    gray = gray_values[index]
    return gray < 45 or gray > 210 or saturation_values[index] < 35


def _has_evidence_structure(
    gray_values: list[int],
    edge_values: list[int],
    saturation_values: list[int],
    warm_mask: tuple[bool, ...],
    face_mask: list[bool],
    interior_indexes: list[int],
    width: int,
    face_primary: bool,
    has_face: bool,
    config: FrameSelectionConfig,
) -> bool:
    """True when pixels show data-bearing chart/slide/text/UI organization.

    Generic geometry (blinds, bookshelves, panels, empty borders, static, bare
    grids) is not evidence. Positive glyph, label, or chart-ink organization is
    required. face_mask may suppress canvas/text only — never chart stroke runs.
    """

    frame_area = len(gray_values)
    height = frame_area // width
    canvas_fraction = (
        sum(
            _is_canvas_pixel(
                index,
                gray_values,
                edge_values,
                saturation_values,
                warm_mask,
                face_mask,
            )
            for index in range(frame_area)
        )
        / frame_area
    )
    highsat_strong = sum(
        edge_values[index] > config.strong_edge_threshold and saturation_values[index] >= 90
        for index in interior_indexes
    ) / len(interior_indexes)
    structure_edges = sum(
        edge_values[index] > config.strong_edge_threshold for index in interior_indexes
    ) / len(interior_indexes)
    (
        text_mass,
        text_components,
        text_rows,
        max_text_row,
        bar_width_cv,
        glyph_components,
    ) = _dark_text_stats(gray_values, saturation_values, face_mask, width, height)
    # Equal-width solid bar stacks (barcode/stripe sheets) are not glyph text.
    has_uniform_bar_sheet = (
        text_rows >= 5
        and max_text_row <= 1
        and glyph_components == 0
        and bar_width_cv <= 0.06
        and text_mass >= 0.08
    )
    has_glyph_label_structure = glyph_components >= 1 or max_text_row >= 2 or bar_width_cv >= 0.05
    # Chart/UI stroke runs ignore face_mask so corner PIP cannot erase ink.
    short_h_mass, short_h_runs, short_h_glyphs = _short_run_stats(
        edge_values,
        width,
        height,
        config.strong_edge_threshold,
        horizontal=True,
    )
    short_v_mass, short_v_runs, short_v_glyphs = _short_run_stats(
        edge_values,
        width,
        height,
        config.strong_edge_threshold,
        horizontal=False,
    )
    band_count = _structured_band_count(edge_values, width, height, config.strong_edge_threshold)
    color_panel_mass, color_panel_bbox, color_panel_count = _color_panel_stats(
        saturation_values, gray_values, width, height
    )
    series_columns, series_regularity = _column_series_stats(
        edge_values, width, height, config.strong_edge_threshold
    )
    long_h_mass, long_h_runs = _long_run_stats(
        edge_values,
        width,
        height,
        config.strong_edge_threshold,
        horizontal=True,
        min_length=28,
    )
    long_v_mass, long_v_runs = _long_run_stats(
        edge_values,
        width,
        height,
        config.strong_edge_threshold,
        horizontal=False,
        min_length=22,
    )
    h_glyph_fraction = (short_h_glyphs / short_h_runs) if short_h_runs else 0.0
    v_glyph_fraction = (short_v_glyphs / short_v_runs) if short_v_runs else 0.0
    stroke_mass = short_h_mass + short_v_mass
    sat_fraction = sum(saturation_values[index] >= 90 for index in interior_indexes) / len(
        interior_indexes
    )
    dark_theme = sum(gray_values[index] < 90 for index in range(frame_area)) / frame_area >= 0.45
    # Bars / multi-line baselines — not a lone title chip or day-number mass.
    has_text_organization = text_rows >= 1 and (
        max_text_row >= 4
        or text_rows >= 3
        or (text_mass >= 0.045 and text_components >= 3 and max_text_row >= 2)
    )
    # Stroke caps: dark themes with light axes produce denser edge mass.
    stroke_ink_cap = 0.20 if dark_theme else 0.12
    # Stroke/label ink only. Bare color tiles are not bidir/color-chart ink.
    has_stroke_ink = (
        short_h_glyphs >= 18
        and short_v_glyphs >= 12
        and h_glyph_fraction >= 0.30
        and v_glyph_fraction >= 0.30
        and stroke_mass <= stroke_ink_cap
    )
    # Real glyph ink only — solid bar-chip rows (gc==0) are not labels.
    has_real_glyphs = glyph_components >= 1
    has_label_ink = (
        text_mass >= 0.008
        and has_text_organization
        and has_glyph_label_structure
        and has_real_glyphs
        and not has_uniform_bar_sheet
    )
    has_panel_ink = color_panel_mass >= 0.10
    has_chart_ink = has_stroke_ink or has_label_ink or has_panel_ink
    # Small equal color tiles (launchpad/sticky/icon grids) — not grayscale
    # chart cells that only match the mass/bbox floors.
    has_color_tile_grid = (
        color_panel_count >= 6
        and color_panel_bbox <= 0.12
        and color_panel_mass >= 0.10
        and (highsat_strong >= 0.02 or sat_fraction >= 0.25)
    )

    # Semantic furniture: labels, axis pairs, or dense platform chart structure.
    # Bare outlines/maps/module grids without this are not data furniture.
    # Bar-chip rows without glyph components are not label furniture.
    has_label_furniture = has_label_ink or (
        text_mass >= 0.008 and text_components >= 3 and max_text_row >= 2 and has_real_glyphs
    )
    has_axis_lines = (
        long_h_mass >= 0.006 and long_v_mass >= 0.003 and long_h_runs >= 1 and long_v_runs >= 1
    ) or (long_h_runs >= 2 and long_v_runs >= 2 and long_h_mass >= 0.008 and long_v_mass >= 0.004)
    # Strong L-shaped axes (box/scatter furniture) — not QR finder edges.
    has_strong_axes = (
        long_h_mass >= 0.014 and long_v_mass >= 0.010 and long_h_runs >= 2 and long_v_runs >= 2
    )
    axis_stroke_cap = 0.20 if dark_theme else 0.12
    has_axis_furniture = (
        has_axis_lines
        and long_h_runs >= 2
        and long_v_runs >= 2
        and short_h_mass >= 0.010
        and short_v_mass >= 0.005
        and band_count >= 4
        and series_columns >= 8
        and stroke_mass <= axis_stroke_cap
    )
    has_platform_furniture = (
        has_stroke_ink
        and band_count >= 10
        and stroke_mass <= stroke_ink_cap
        and short_h_runs >= 40
        and short_v_runs >= 18
        and not has_color_tile_grid
        and (sat_fraction >= 0.40 or highsat_strong >= 0.015 or color_panel_mass >= 0.05)
    )
    has_dense_stroke_furniture = (
        has_stroke_ink
        and band_count >= 12
        and stroke_mass <= stroke_ink_cap
        and short_h_runs >= 50
        and short_v_runs >= 25
        and not has_color_tile_grid
    )
    # Dense/platform stroke density is not data furniture by itself. Require
    # series/axis/label organization (or colorful panel marks on a series grid).
    has_series_marks = (
        series_columns >= 18
        and series_regularity >= 0.40
        and (
            short_h_mass >= short_v_mass * 1.15
            or short_v_mass >= short_h_mass * 1.15
            or (series_columns >= 28 and series_regularity >= 0.55)
        )
    )
    platform_se_hi = 0.24 if dark_theme else 0.22
    # Mid-sat multi-color bodies without axes/labels are schedule-board chrome,
    # not platform chart ink (GEX/dark colorful stays via high sat).
    has_unlabeled_sparse_color = (
        0.02 <= sat_fraction <= 0.15
        and highsat_strong < 0.012
        and not has_strong_axes
        and not has_label_furniture
        and not has_real_glyphs
        and color_panel_mass < 0.10
    )
    # Platform marks need axes/labels, or stroke-platform series ink without
    # bulk unlabeled color-panel fills (choropleth/blob maps). Bare low-sat
    # axis geometry (card boards) is not enough — need strong axes, glyphs,
    # or high-sat platform ink (GEX).
    has_platform_data_marks = (
        (has_platform_furniture or has_dense_stroke_furniture)
        and has_series_marks
        and canvas_fraction >= 0.50
        and structure_edges <= platform_se_hi
        and has_stroke_ink
        and color_panel_mass < 0.15
        and short_h_runs >= 80
        and not has_unlabeled_sparse_color
        and (
            has_label_furniture
            or (sat_fraction >= 0.40 and highsat_strong >= 0.015)
            or (has_axis_lines and (has_strong_axes or has_real_glyphs or highsat_strong >= 0.015))
            or (
                band_count >= 12
                and series_columns >= 40
                and (has_real_glyphs or sat_fraction >= 0.40 or highsat_strong >= 0.015)
            )
        )
    )
    has_chart_furniture = has_label_furniture or has_axis_furniture
    has_data_furniture = has_chart_furniture or has_axis_lines or has_platform_data_marks
    # Node-box + connector diagrams (org/flow/ER) and kanban/card boards:
    # long box rules and/or multi-row bar-chip labels inside frames. Not pure
    # axis charts (no bar-chip text). Multi-column card chrome with text_mass=0
    # is blocked via platform/bidir furniture requiring real data marks.
    has_card_board_geometry = (
        not has_real_glyphs
        and glyph_components == 0
        and max_text_row >= 2
        and text_components >= 3
        and 0.008 <= text_mass < 0.06
        and series_regularity >= 0.40
        and band_count >= 8
        and long_h_mass >= 0.02
        and short_h_runs >= 40
        and short_v_runs >= 40
    )
    has_box_diagram_geometry = (
        not has_real_glyphs
        and text_mass < 0.14
        and (
            (long_h_runs >= 30 and long_h_mass >= 0.035)
            or (
                long_h_runs >= 12
                and long_h_mass >= 0.025
                and text_mass >= 0.008
                and has_text_organization
                and max_text_row >= 2
            )
            or has_card_board_geometry
        )
    )
    # Process/sticky card boards: discrete large color panels + box rules with
    # sparse series density. Stroke/color based so compact face masks cannot
    # unlock timeline/bar paths by erasing text-dependent box vetoes.
    has_process_card_geometry = (
        color_panel_count >= 3
        and color_panel_mass >= 0.12
        and 0.04 <= color_panel_bbox <= 0.16
        and long_h_runs >= 4
        and long_v_runs >= 6
        and long_v_mass >= long_h_mass * 0.70
        and series_columns <= 28
        and series_regularity <= 0.55
        and not has_real_glyphs
        and text_mass < 0.03
    )
    has_nondata_card_geometry = (
        has_box_diagram_geometry or has_card_board_geometry or has_process_card_geometry
    )

    # Glyph/label slides — multi-glyph or varied bar lines, not stripe sheets
    # or connector-heavy flow diagrams.
    has_slide_text = (
        text_mass >= 0.02
        and text_components >= 3
        and has_text_organization
        and text_rows >= 2
        and max_text_row >= 1
        and canvas_fraction >= 0.40
        and 0.05 <= structure_edges <= 0.25
        and stroke_mass <= 0.18
        and has_glyph_label_structure
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
        and not has_box_diagram_geometry
    )
    # Real-font multi-row bullet/agenda slides: text-line stroke organization
    # after downscale, without calendar grids, node-box chrome, or connectors.
    # Thresholds are semantic (line-like H strokes, moderate bands) rather than
    # a single fixture envelope.
    # Node-link / route diagrams produce stroke geometry without text lines:
    # sparse bands with dense short runs (no plot axes), dual long rules from
    # boxes/ovals, or extreme horizontal run walls from colored routes.
    has_node_link_geometry = (
        not has_real_glyphs
        and text_mass < 0.02
        and color_panel_mass < 0.12
        # Regular multi-card KPI chrome is not a node-link diagram.
        and not (
            series_columns >= 28
            and series_regularity >= 0.55
            and long_h_runs >= 3
            and long_v_runs >= 3
            and band_count >= 4
            and stroke_mass <= 0.06
        )
        and (
            (band_count <= 4 and short_h_runs >= 70 and not has_axis_lines)
            or (
                long_h_runs >= 2
                and long_v_runs >= 2
                and not has_strong_axes
                and series_regularity >= 0.55
                and series_columns <= 36
            )
            or (short_h_runs >= 150 and band_count <= 6 and not has_axis_lines)
        )
    )
    has_stroke_slide_geometry = (
        canvas_fraction >= 0.65
        and 0.018 <= structure_edges <= 0.14
        and 0.015 <= stroke_mass <= 0.075
        and short_h_runs >= 28
        and short_h_glyphs >= 22
        and h_glyph_fraction >= 0.62
        and 3 <= band_count <= 14
        and 10 <= series_columns <= 55
        # Text-line slides keep moderate column activity per band; link/node
        # scatter (incl. face-over-diagram) spikes columns without axes.
        and series_columns <= band_count * 6
        and series_regularity >= 0.40
        and color_panel_mass < 0.10
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
        and not has_box_diagram_geometry
        and not has_card_board_geometry
        and not has_node_link_geometry
        # Month grids: many bands, few active columns.
        and not (band_count >= 12 and series_columns <= 20)
        # Node/connector chrome: weak H-glyph text or long box rules.
        and not (long_h_runs >= 8 and h_glyph_fraction < 0.72)
        and not (
            short_v_runs >= 55
            and short_v_mass >= 0.022
            and long_h_runs >= 2
            and h_glyph_fraction < 0.72
        )
    )
    has_stroke_slide = has_stroke_slide_geometry and (
        (
            # Light slides: unsaturated canvas + horizontal text-line dominance.
            not dark_theme and sat_fraction < 0.25 and short_h_mass >= short_v_mass * 1.15
        )
        or (
            # Dark slides: navy fills are high-sat; reject shelf/wood long rules.
            dark_theme
            and long_h_runs < 5
            and long_h_mass < 0.02
            and band_count >= 4
            and short_h_runs >= 30
            and h_glyph_fraction >= 0.70
        )
    )
    has_organized_text = (
        text_mass >= 0.008
        and text_components >= 4
        and has_text_organization
        and canvas_fraction >= 0.18
        and 0.06 <= structure_edges <= 0.26
        and short_h_runs >= 35
        and short_v_runs >= 30
        and stroke_mass <= 0.18
        and max_text_row >= 2
        and has_glyph_label_structure
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
        and not has_box_diagram_geometry
    )
    has_content_slide = (
        text_mass >= 0.012
        and text_components >= 6
        and has_text_organization
        and canvas_fraction >= 0.15
        and 0.08 <= structure_edges <= 0.40
        and short_h_runs >= 80
        and short_v_runs >= 80
        and band_count >= 8
        and max_text_row >= 3
        and stroke_mass <= 0.20
        and has_glyph_label_structure
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
        and not has_box_diagram_geometry
    )
    # Tabular lattice + multi-cell glyph rows (not repetitive stripe ink).
    has_data_table = (
        text_mass >= 0.035
        and text_components >= 12
        and text_rows >= 4
        and max_text_row >= 3
        and glyph_components >= 4
        and canvas_fraction >= 0.28
        and 0.08 <= structure_edges <= 0.40
        and band_count >= 4
        and series_columns >= 24
        and series_regularity >= 0.50
        and long_h_runs >= 2
        and (long_v_runs >= 1 or series_columns >= 40)
        and stroke_mass <= 0.22
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
    )
    # Spreadsheet/grid UI with header/cell lattice (glyphs may merge when downscaled).
    has_spreadsheet_grid = (
        canvas_fraction >= 0.35
        and 0.10 <= structure_edges <= 0.36
        and text_mass >= 0.04
        and text_rows >= 4
        and text_components >= 8
        and max_text_row >= 3
        and band_count >= 6
        and series_columns >= 20
        and series_regularity >= 0.60
        and long_h_runs >= 4
        and long_v_runs >= 1
        and short_v_runs >= 40
        and short_h_runs >= 12
        and stroke_mass <= 0.18
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
    )
    # Real-font tables: header/cell lattice survives downscale as stroke geometry
    # when Arial glyphs vanish. Empty panel/card grids are denser or less regular
    # and lack header-fill + column organization.
    has_stroke_table = (
        canvas_fraction >= 0.50
        and 0.05 <= structure_edges <= 0.22
        and 0.025 <= stroke_mass <= 0.10
        and 5 <= band_count <= 16
        and short_v_runs >= 30
        and short_v_mass >= 0.008
        and color_panel_mass < 0.15
        and sat_fraction < 0.20
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_color_tile_grid
        and not has_box_diagram_geometry
        and not has_card_board_geometry
        and (
            (
                # Sparse H+V cell lattice with column activity from cell content.
                long_h_runs >= 3
                and long_v_runs >= 2
                and long_h_mass >= 0.012
                and long_v_mass >= 0.005
                and series_columns >= 26
                and series_regularity >= 0.55
                and 45 <= short_h_runs <= 100
            )
            or (
                # Colored header bar + multi-row body (desk P&L / spreadsheet UI).
                color_panel_mass >= 0.012
                and long_h_runs >= 2
                and long_h_mass >= 0.012
                and short_h_runs >= 80
                and short_v_runs >= 30
                and series_columns >= 20
                and series_regularity >= 0.40
                and band_count >= 5
            )
        )
    )
    # Bidir/color need labels, series/legend marks, platform data, or axes with
    # real data marks — not bare long H/V panel/keypad geometry alone.
    axis_bidir_stroke_cap = 0.18 if dark_theme else 0.10
    # Series-column regularity alone is card-grid chrome when almost all short
    # mass is horizontal box rules; require some vertical mark mass too.
    has_axis_data_marks = (
        text_mass >= 0.008
        or (
            has_series_marks
            and series_columns >= 32
            and series_regularity >= 0.50
            and short_v_mass >= short_h_mass * 0.40
        )
        or (color_panel_mass >= 0.08 and structure_edges <= 0.20)
    )
    has_bidir_semantic_furniture = (
        has_label_furniture
        or has_label_ink
        or has_platform_data_marks
        or (
            has_axis_furniture
            and has_stroke_ink
            and stroke_mass <= axis_bidir_stroke_cap
            and has_axis_data_marks
            and not has_box_diagram_geometry
            and not has_unlabeled_sparse_color
            and (
                has_strong_axes or has_real_glyphs or sat_fraction < 0.02 or highsat_strong >= 0.015
            )
        )
    )
    structure_hi = 0.30 if dark_theme else 0.22
    has_bidir_chart = (
        canvas_fraction >= 0.28
        and 0.06 <= structure_edges <= structure_hi
        and short_h_runs >= 40
        and short_v_runs >= 18
        and band_count >= 5
        and short_h_mass >= 0.018
        and short_v_mass >= 0.005
        and not face_primary
        and not has_color_tile_grid
        and not has_nondata_card_geometry
        and (has_stroke_ink or has_label_ink)
        and has_bidir_semantic_furniture
    )
    has_color_chart = (
        highsat_strong >= 0.03
        and canvas_fraction >= 0.25
        and 0.05 <= structure_edges <= structure_hi
        and short_h_runs >= 35
        and short_v_runs >= 20
        and band_count >= 4
        and not face_primary
        and not has_color_tile_grid
        and not has_nondata_card_geometry
        and has_chart_ink
        and has_bidir_semantic_furniture
        and (not has_face or color_panel_mass >= 0.08 or has_label_ink or color_panel_count >= 3)
    )
    # High-sat fills need furniture — bare LED/dot matrices are not charts.
    has_highsat_fill = (
        color_panel_mass >= 0.12
        and 0.08 <= color_panel_bbox <= 0.60
        and color_panel_count <= 4
        and highsat_strong >= 0.08
        and has_data_furniture
    )
    has_soft_area = (
        color_panel_mass >= 0.12
        and not face_primary
        and not has_process_card_geometry
        and (
            (color_panel_bbox <= 0.65 and color_panel_count <= 2 and has_chart_furniture)
            or (
                # Full-plot multi-band stacked area: horizontal bands + axes.
                # Bands may merge into one component after downscale.
                color_panel_mass >= 0.20
                and color_panel_count <= 8
                and color_panel_bbox <= 0.85
                and has_axis_lines
                and band_count >= 4
                and short_h_mass >= 0.012
                and short_h_mass >= short_v_mass * 1.3
                and not has_color_tile_grid
            )
        )
    )
    # Multi-block panels need labels plus real axes — not tile edges/title chips.
    has_multi_panel = (
        color_panel_count >= 4
        and color_panel_mass >= 0.08
        and color_panel_bbox <= 0.40
        and highsat_strong >= 0.015
        and has_label_furniture
        and has_axis_furniture
        and not face_primary
    )
    # Partition/treemap blocks need real glyph/legend/axes — not stripe bands.
    has_real_label_marks = glyph_components >= 1 or max_text_row >= 2
    has_partition_chart = (
        canvas_fraction >= 0.20
        and 0.04 <= structure_edges <= 0.22
        and color_panel_count >= 4
        and color_panel_mass >= 0.20
        and 0.08 <= color_panel_bbox <= 0.45
        and not face_primary
        and not has_color_tile_grid
        and (
            (has_label_furniture and has_real_label_marks)
            or (
                has_text_organization
                and max_text_row >= 2
                and text_components >= 4
                and has_glyph_label_structure
                and has_real_label_marks
            )
            or (
                has_axis_furniture
                and color_panel_count >= 4
                and has_real_label_marks
                and text_mass >= 0.008
            )
        )
    )
    has_color_panel = (
        canvas_fraction >= 0.25
        and 0.04 <= structure_edges <= 0.22
        and (has_highsat_fill or has_soft_area or has_multi_panel or has_partition_chart)
    )
    # Axis-aligned series: candles/bars (vertical-dominant) or multi-series
    # lines (horizontal-dominant) on a regular column grid — not maps/outlines.
    # Sparse color bodies need strong axes or real tick/glyph/legend marks;
    # a title plus unlabeled schedule bars is not series support.
    sparse_color_bodies = (
        0.008 <= sat_fraction <= 0.08
        and series_columns >= 30
        and series_regularity >= 0.55
        and (has_strong_axes or has_label_furniture or has_real_glyphs)
    )
    colored_edge_series = highsat_strong >= 0.012 and short_h_glyphs >= 6 and series_columns >= 10
    # Bar-chip rows alone are not series label support — need real glyphs.
    has_series_label_support = text_mass >= 0.004 and has_glyph_label_structure and has_real_glyphs
    has_vertical_series = (
        short_v_runs >= 35
        and short_v_mass >= 0.012
        and short_v_glyphs >= 20
        and v_glyph_fraction >= 0.50
        and short_h_runs >= 8
        and short_h_mass <= short_v_mass * 0.90
    )
    has_horizontal_series = (
        short_h_runs >= 50
        and short_h_mass >= 0.020
        and short_h_glyphs >= 50
        and h_glyph_fraction >= 0.70
        and short_v_runs >= 15
        and short_v_mass >= 0.0045
        and short_h_mass >= short_v_mass * 1.2
    )
    # Ordinary multi-series lines: L-axes + stroke series without dense columns.
    # Require plot-like axis/series semantics — not route maps or node-link frames.
    has_axis_series_ink = (
        has_axis_lines
        and has_stroke_ink
        and (has_horizontal_series or has_vertical_series)
        and series_columns >= 12
        and series_regularity >= 0.22
        and short_h_mass >= 0.012
        and band_count >= 2
        and long_h_runs >= 1
        and long_v_runs >= 1
        and not face_primary
        and not has_uniform_bar_sheet
        and not has_box_diagram_geometry
        and not has_card_board_geometry
        and not has_node_link_geometry
        and (
            has_real_glyphs
            or has_strong_axes
            or (
                # H-dominant series on a simple L-frame (ordinary line charts).
                has_horizontal_series
                and short_h_mass >= short_v_mass * 1.8
                and long_h_mass >= 0.008
                and long_v_mass >= 0.005
                and long_h_runs <= 5
                and long_v_runs <= 6
                and series_regularity <= 0.50
                and sat_fraction < 0.10
                and color_panel_mass < 0.08
            )
        )
    )
    has_series_support = (
        has_series_label_support
        or color_panel_mass >= 0.10
        or sparse_color_bodies
        or colored_edge_series
        or has_axis_series_ink
    )
    # Series charts need real marks — not box-border axis_lines alone.
    has_series_data_furniture = (
        has_chart_furniture
        or has_platform_data_marks
        or (
            has_axis_lines
            and series_columns >= 18
            and not has_box_diagram_geometry
            and (
                has_stroke_ink
                or (has_vertical_series and short_v_glyphs >= 40)
                or (has_horizontal_series and short_h_glyphs >= 40)
            )
        )
    )
    series_stroke_cap = 0.18 if dark_theme else 0.09
    series_se_hi = 0.28 if dark_theme else 0.18
    has_series_band_support = band_count >= 3 or (
        band_count >= 2 and has_axis_lines and has_horizontal_series
    )
    has_series_regularity_support = series_regularity >= 0.40 or (
        series_regularity >= 0.22 and has_axis_lines and has_stroke_ink and has_horizontal_series
    )
    has_series_chart = (
        canvas_fraction >= 0.45
        and 0.03 <= structure_edges <= series_se_hi
        and stroke_mass <= series_stroke_cap
        and has_series_band_support
        and not face_primary
        and not has_color_tile_grid
        and not has_nondata_card_geometry
        and not has_uniform_bar_sheet
        and series_columns >= 10
        and has_series_regularity_support
        and has_series_data_furniture
        and has_series_support
        and (has_vertical_series or has_horizontal_series)
    )
    # Box/whisker and sparse axis-mark charts: strong axes + mark/series ink that
    # dominates panel rules — not bare comic panels, card boards, or L-frames.
    long_axis_mass = long_h_mass + long_v_mass
    has_axis_mark_chart = (
        canvas_fraction >= 0.45
        and 0.05 <= structure_edges <= 0.22
        and has_strong_axes
        and not face_primary
        and not has_box_diagram_geometry
        and series_columns >= 24
        and series_regularity >= 0.45
        and short_v_runs >= 50
        and short_h_runs >= 40
        and short_h_glyphs >= 40
        and short_v_glyphs >= 50
        and 0.04 <= stroke_mass <= 0.15
        and stroke_mass >= long_axis_mass * 0.85
        and band_count >= 3
        and (
            (has_label_furniture and has_real_glyphs)
            or (
                # Axis-tied whisker/point marks — not multi-row card chrome
                # or unlabeled horizontal color-bar schedule boards.
                has_series_marks
                and series_columns >= 40
                and series_regularity >= 0.55
                and short_h_glyphs >= 60
                and short_v_glyphs >= 80
                and short_v_mass >= short_h_mass * 0.85
                and sat_fraction <= 0.05
                and max_text_row <= 1
                and text_mass < 0.02
            )
            or (
                has_stroke_ink
                and has_series_marks
                and series_columns >= 40
                and series_regularity >= 0.55
                and short_v_mass >= short_h_mass * 0.85
                and sat_fraction <= 0.05
                and max_text_row <= 1
                and (has_label_furniture or has_real_glyphs)
            )
        )
    )
    # Single-series bar/histogram: regular columns + axes/title, no V-dominance.
    # Dark dashboards with light axes may exceed light-canvas stroke/se caps.
    has_bar_bodies = (
        color_panel_mass >= 0.015
        or color_panel_count >= 3
        or (0.02 <= sat_fraction <= 0.30 and short_v_mass >= 0.010)
        or (dark_theme and short_v_mass >= 0.008 and short_v_runs >= 12 and series_columns >= 12)
    )
    bar_stroke_cap = 0.20 if dark_theme else 0.10
    bar_se_hi = 0.30 if dark_theme else 0.20
    # Multi-band funnel/treemap columns: organized vertical series + panels,
    # not furniture-free equalizer/spectrum bar walls.
    has_multiband_bar_partition = (
        color_panel_count >= 4
        and color_panel_mass >= 0.20
        and 0.06 <= color_panel_bbox <= 0.35
        and band_count >= 6
        and has_vertical_series
        and series_columns >= 40
        and series_regularity >= 0.55
        and short_v_glyphs >= 40
        and v_glyph_fraction >= 0.50
        and not has_color_tile_grid
    )
    # Waterfall/bridge: floating vertical bodies on strong axes even when
    # downscaled tick labels vanish and color panels merge.
    has_floating_bar_bridge = (
        has_strong_axes
        and (has_axis_lines or has_axis_furniture)
        and short_v_mass >= 0.012
        and short_v_runs >= 20
        and short_h_mass >= 0.012
        and short_v_mass >= short_h_mass * 0.95
        and series_columns >= 12
        and series_regularity >= 0.35
        and band_count >= 3
        and 0.025 <= sat_fraction <= 0.40
        and (
            color_panel_count >= 2
            or (color_panel_mass >= 0.02 and sat_fraction >= 0.05)
            or (short_v_mass >= 0.02 and series_columns >= 24 and not has_face)
        )
    )
    # Axis-bearing single-series bars: L/frame axes + regular color columns even
    # when real-font tick labels vanish after downscale.
    has_axis_color_bars = (
        has_axis_lines
        and has_bar_bodies
        and color_panel_count >= 3
        and color_panel_mass >= 0.04
        and series_columns >= 12
        and series_regularity >= 0.30
        and short_v_mass >= 0.008
        and short_v_runs >= 12
        and long_v_runs >= 2
        and long_h_mass >= 0.005
        and not has_card_board_geometry
        and not has_process_card_geometry
        # Large discrete cards are not thin bar columns.
        and not (
            color_panel_mass >= 0.18
            and color_panel_bbox >= 0.05
            and color_panel_count <= 8
            and series_columns < 28
            and long_v_runs >= 6
            and long_h_runs >= 4
        )
    )
    has_vertical_bar_histogram = (
        canvas_fraction >= 0.40
        and 0.04 <= structure_edges <= bar_se_hi
        and not face_primary
        and not has_color_tile_grid
        and series_columns >= 8
        and series_regularity >= 0.28
        and short_v_runs >= 12
        and short_v_mass >= 0.008
        and band_count >= 3
        and stroke_mass <= bar_stroke_cap
        and has_bar_bodies
        and not has_nondata_card_geometry
        and (
            has_label_furniture
            or has_multiband_bar_partition
            or has_floating_bar_bridge
            or has_axis_color_bars
            or (
                has_axis_furniture
                and (
                    # Title-only mass is not bar label furniture.
                    (text_mass >= 0.008 and has_real_glyphs and has_glyph_label_structure)
                    or (
                        color_panel_mass >= 0.05
                        and color_panel_count >= 3
                        and color_panel_bbox <= 0.05
                        and series_columns >= 18
                        and (has_strong_axes or has_label_furniture or has_real_glyphs)
                    )
                )
            )
        )
    )
    # Horizontal bullet/KPI rows: repeated aligned bars + category/value labels.
    has_labeled_horizontal_bars = (
        color_panel_count >= 3
        and color_panel_mass >= 0.04
        and color_panel_bbox <= 0.40
        and text_rows >= 3
        and text_components >= 4
        and (has_label_furniture or ((has_axis_lines or has_axis_furniture) and text_mass >= 0.008))
        and (
            has_glyph_label_structure
            or (text_rows >= 5 and max_text_row >= 1 and text_mass >= 0.02)
        )
    )
    # Gantt/timeline: axis frame + repeated horizontal bar bodies even when
    # category glyphs disappear after downscale. Process/sticky cards with
    # box borders are not timeline bars.
    has_timeline_bar_chart = (
        (has_axis_lines or has_axis_furniture or has_strong_axes)
        and long_h_mass >= 0.010
        and long_h_runs >= 2
        and short_h_mass >= 0.012
        and short_h_runs >= 18
        and series_columns >= 12
        and series_regularity >= 0.35
        and band_count >= 4
        and 0.02 <= sat_fraction <= 0.45
        and short_h_mass >= short_v_mass * 0.55
        and not has_process_card_geometry
        and not (
            # Discrete card walls: many long V rules, sparse series, fat panels.
            long_v_runs >= 6
            and color_panel_count >= 3
            and color_panel_mass >= 0.12
            and color_panel_bbox >= 0.04
            and series_columns < 35
            and not has_real_glyphs
        )
        and (
            color_panel_count >= 3
            or color_panel_mass >= 0.03
            or (sat_fraction >= 0.03 and long_h_runs >= 4)
        )
    )
    # Multi-segment horizontal stacked bars: axis frame + repeated color bodies
    # across category rows (glyphs often vanish after downscale).
    has_stacked_horizontal_color_bars = (
        canvas_fraction >= 0.45
        and 0.05 <= structure_edges <= bar_se_hi
        and has_axis_lines
        and color_panel_count >= 4
        and color_panel_mass >= 0.10
        and band_count >= 5
        and series_columns >= 12
        and long_h_runs >= 4
        and long_v_runs >= 1
        and long_h_mass >= 0.03
        and sat_fraction >= 0.08
        and short_h_mass >= 0.006
        and stroke_mass <= bar_stroke_cap
        and not face_primary
        and not has_color_tile_grid
        and not has_nondata_card_geometry
        and not has_node_link_geometry
    )
    has_horizontal_bar_chart = (
        canvas_fraction >= 0.40
        and 0.04 <= structure_edges <= bar_se_hi
        and not face_primary
        and not has_color_tile_grid
        and band_count >= 4
        and short_h_mass >= 0.006
        and stroke_mass <= bar_stroke_cap
        and not has_nondata_card_geometry
        and (
            has_labeled_horizontal_bars
            or has_timeline_bar_chart
            or has_stacked_horizontal_color_bars
        )
    )
    has_bar_histogram = has_vertical_bar_histogram or has_horizontal_bar_chart
    # 2x2 (or similar) small-multiple line panels: repeated local L-axes +
    # series stroke without single-panel density floors.
    has_small_multiples_chart = (
        canvas_fraction >= 0.55
        and 0.05 <= structure_edges <= 0.16
        and has_axis_lines
        and has_stroke_ink
        and long_h_runs >= 6
        and long_v_runs >= 3
        and long_h_mass >= 0.02
        and long_v_mass >= 0.005
        and band_count >= 3
        and 12 <= series_columns <= 40
        and series_regularity >= 0.35
        and stroke_mass <= 0.06
        and color_panel_mass < 0.10
        and sat_fraction < 0.15
        and short_h_runs >= 30
        and short_v_runs >= 15
        and not face_primary
        and not has_box_diagram_geometry
        and not has_card_board_geometry
        and not has_color_tile_grid
        and not has_uniform_bar_sheet
        and not has_node_link_geometry
    )
    # Labeled multi-band funnel/partition charts (warm fills may look face-like).
    has_labeled_band_chart = (
        canvas_fraction >= 0.35
        and 0.05 <= structure_edges <= 0.22
        and color_panel_count >= 4
        and color_panel_mass >= 0.20
        and 0.06 <= color_panel_bbox <= 0.35
        and has_label_furniture
        and has_real_label_marks
        and text_rows >= 2
        and band_count >= 6
        and not has_color_tile_grid
    )
    # Sparse but real glyph labels (titles/readouts) that fall below slide mass.
    has_sparse_glyph_labels = (
        glyph_components >= 4
        and text_components >= 4
        and max_text_row >= 4
        and text_mass >= 0.002
        and has_glyph_label_structure
    )
    has_ui_labels = has_label_furniture or has_sparse_glyph_labels
    # Radial/spider and gauge/readout charts: labels + stroke rings/spokes.
    has_radial_or_gauge_chart = (
        canvas_fraction >= 0.55
        and 0.03 <= structure_edges <= 0.20
        and has_ui_labels
        and has_real_label_marks
        and has_stroke_ink
        and stroke_mass <= 0.16
        and short_h_runs >= 25
        and short_v_runs >= 25
        and band_count >= 3
        and series_columns >= 20
        and not face_primary
        and not has_color_tile_grid
        and not has_box_diagram_geometry
    )
    # Real-font pie/donut: balanced H/V stroke around a compact color disk.
    # Legend chips may split the panel count; title glyphs often vanish.
    _radial_run_max = max(short_h_runs, short_v_runs, 1)
    has_radial_color_chart = (
        canvas_fraction >= 0.50
        and 0.03 <= structure_edges <= 0.16
        and color_panel_mass >= 0.10
        and (color_panel_count <= 4 or (color_panel_count <= 8 and color_panel_bbox >= 0.16))
        and 0.12 <= color_panel_bbox <= 0.60
        and has_stroke_ink
        and stroke_mass <= 0.12
        and short_h_runs >= 40
        and short_v_runs >= 40
        and abs(short_h_runs - short_v_runs) / _radial_run_max <= 0.40
        and h_glyph_fraction >= 0.50
        and v_glyph_fraction >= 0.50
        and sat_fraction >= 0.08
        and band_count >= 3
        and series_columns >= 18
        and not face_primary
        and not has_color_tile_grid
        and not has_nondata_card_geometry
        and not (long_h_runs >= 3 and long_v_runs >= 3)
        and not (long_h_mass >= 0.03 and long_v_mass >= 0.01)
    )
    # Labeled Sankey/flow partitions: multi-node color bodies + link strokes.
    # Downscale may merge nodes/ribbons into one wide color component.
    has_sankey_flow_chart = (
        canvas_fraction >= 0.40
        and 0.04 <= structure_edges <= 0.18
        and color_panel_mass >= 0.16
        and sat_fraction >= 0.10
        and has_stroke_ink
        and short_h_mass >= 0.015
        and short_h_mass >= short_v_mass * 1.15
        and short_h_runs >= 40
        and band_count >= 3
        and series_columns >= 12
        and stroke_mass <= 0.14
        and not face_primary
        and not has_color_tile_grid
        and not has_process_card_geometry
        and not has_node_link_geometry
        and not has_box_diagram_geometry
        and (
            (color_panel_count >= 2 and 0.08 <= color_panel_bbox <= 0.55)
            or (
                # Merged flow body: wide horizontal color mass + link strokes.
                color_panel_count <= 2
                and color_panel_bbox >= 0.30
                and short_h_mass >= short_v_mass * 1.8
                and short_h_runs >= 60
                and long_v_runs <= 4
            )
        )
        and (
            has_label_furniture
            or has_real_glyphs
            or text_mass >= 0.004
            or (
                short_h_glyphs >= 28
                and h_glyph_fraction >= 0.50
                and short_h_mass >= short_v_mass * 1.5
            )
        )
    )
    # Multi-card KPI / sparkline strips with titles and values.
    has_kpi_card_strip = (
        canvas_fraction >= 0.45
        and 0.04 <= structure_edges <= 0.30
        and long_h_runs >= 3
        and long_v_runs >= 3
        and series_columns >= 20
        and stroke_mass <= 0.18
        and not face_primary
        and not has_color_tile_grid
        and not has_process_card_geometry
        and not has_box_diagram_geometry
        and color_panel_mass < 0.12
        and (
            (
                has_ui_labels
                and has_real_label_marks
                and text_components >= 4
                and max_text_row >= 4
                and long_h_runs >= 6
                and long_v_runs >= 4
            )
            or (
                # Dark/real-font cards: chrome + sparkline strokes without thick
                # glyph mass after downscale.
                dark_theme
                and has_stroke_ink
                and short_h_runs >= 28
                and short_v_runs >= 28
                and series_regularity >= 0.45
                and band_count >= 3
                and sat_fraction >= 0.02
                and stroke_mass <= 0.08
            )
        )
    )
    # Labeled form/settings UI: field labels + value rows + input chrome.
    has_labeled_form_ui = (
        canvas_fraction >= 0.50
        and 0.04 <= structure_edges <= 0.28
        and has_ui_labels
        and has_real_label_marks
        and text_components >= 4
        and max_text_row >= 2
        and long_h_runs >= 3
        and stroke_mass <= 0.18
        and not face_primary
        and not has_color_tile_grid
        and not has_box_diagram_geometry
        and not has_uniform_bar_sheet
    )
    return (
        has_slide_text
        or has_stroke_slide
        or has_organized_text
        or has_content_slide
        or has_data_table
        or has_spreadsheet_grid
        or has_stroke_table
        or has_bidir_chart
        or has_color_chart
        or has_color_panel
        or has_series_chart
        or has_axis_mark_chart
        or has_bar_histogram
        or has_small_multiples_chart
        or has_labeled_band_chart
        or has_radial_or_gauge_chart
        or has_radial_color_chart
        or has_sankey_flow_chart
        or has_kpi_card_strip
        or has_labeled_form_ui
    )


def _long_run_stats(
    edge_values: list[int],
    width: int,
    height: int,
    threshold: int,
    *,
    horizontal: bool,
    min_length: int,
) -> tuple[float, int]:
    """Mass and count of long interior edge runs (axis/spine lines)."""

    total = 0
    runs = 0
    frame_area = width * height
    if horizontal:
        for y in range(2, height - 2):
            run = 0
            row = y * width
            for x in range(2, width - 2):
                if edge_values[row + x] > threshold:
                    run += 1
                else:
                    if run >= min_length:
                        total += run
                        runs += 1
                    run = 0
            if run >= min_length:
                total += run
                runs += 1
    else:
        for x in range(2, width - 2):
            run = 0
            for y in range(2, height - 2):
                if edge_values[y * width + x] > threshold:
                    run += 1
                else:
                    if run >= min_length:
                        total += run
                        runs += 1
                    run = 0
            if run >= min_length:
                total += run
                runs += 1
    return total / frame_area, runs


def _short_run_stats(
    edge_values: list[int],
    width: int,
    height: int,
    threshold: int,
    *,
    horizontal: bool,
    min_length: int = 3,
    max_length: int = 22,
    glyph_max_length: int = 8,
) -> tuple[float, int, int]:
    """Mass, count, and glyph-length count of short interior edge runs.

    Glyph-length runs (ticks, labels, UI strokes) are counted separately from
    medium grid-line runs so bare architectural grids do not count as charts.
    Face masks are intentionally not applied: chart ink under a PIP must remain.
    """

    total = 0
    runs = 0
    glyphs = 0
    frame_area = width * height
    if horizontal:
        for y in range(3, height - 3):
            run = 0
            row = y * width
            for x in range(3, width - 3):
                index = row + x
                if edge_values[index] > threshold:
                    run += 1
                else:
                    if min_length <= run <= max_length:
                        total += run
                        runs += 1
                        if run <= glyph_max_length:
                            glyphs += 1
                    run = 0
            if min_length <= run <= max_length:
                total += run
                runs += 1
                if run <= glyph_max_length:
                    glyphs += 1
    else:
        for x in range(3, width - 3):
            run = 0
            for y in range(3, height - 3):
                index = y * width + x
                if edge_values[index] > threshold:
                    run += 1
                else:
                    if min_length <= run <= max_length:
                        total += run
                        runs += 1
                        if run <= glyph_max_length:
                            glyphs += 1
                    run = 0
            if min_length <= run <= max_length:
                total += run
                runs += 1
                if run <= glyph_max_length:
                    glyphs += 1
    return total / frame_area, runs, glyphs


def _structured_band_count(edge_values: list[int], width: int, height: int, threshold: int) -> int:
    """Count separated horizontal bands of moderate edge density."""

    dense_rows: list[bool] = []
    for y in range(height):
        row = y * width
        density = sum(edge_values[row + x] > threshold for x in range(width)) / width
        dense_rows.append(0.05 <= density <= 0.55)
    bands = 0
    in_band = False
    for dense in dense_rows:
        if dense and not in_band:
            bands += 1
            in_band = True
        elif not dense:
            in_band = False
    return bands


def _color_panel_stats(
    saturation_values: list[int],
    gray_values: list[int],
    width: int,
    height: int,
) -> tuple[float, float, int]:
    """Compact saturated panel mass, largest bbox fraction, and panel count.

    Counts pie wedges, stacked-bar bodies, heatmaps, and area fills. Bright
    saturated ink (sat up to 255) is included so orange/blue chart fills are not
    clipped out of the skin-tone-adjacent mid-sat band.
    """

    frame_area = width * height
    mask = tuple(
        saturation_values[index] >= 70 and gray_values[index] > 35 for index in range(frame_area)
    )
    best_mass = 0.0
    best_bbox = 0.0
    total_mass = 0.0
    panel_count = 0
    for component in _connected_components(mask, width, height):
        mass = len(component) / frame_area
        if mass < 0.015:
            continue
        xs = [index % width for index in component]
        ys = [index // width for index in component]
        bbox_w = max(xs) - min(xs) + 1
        bbox_h = max(ys) - min(ys) + 1
        bbox_fraction = (bbox_w * bbox_h) / frame_area
        occupancy = len(component) / (bbox_w * bbox_h)
        if occupancy < 0.35 or bbox_fraction > 0.70:
            continue
        panel_count += 1
        total_mass += mass
        if mass > best_mass:
            best_mass = mass
            best_bbox = bbox_fraction
    # Prefer aggregate multi-panel mass when several compact blocks exist.
    report_mass = total_mass if panel_count >= 3 else best_mass
    return report_mass, best_bbox, panel_count


def _column_series_stats(
    edge_values: list[int], width: int, height: int, threshold: int
) -> tuple[int, float]:
    """Count active vertical stroke columns and spacing regularity.

    Candlestick/series charts place short vertical ink on a regular x grid.
    Scattered organic texture rarely keeps tight gap regularity.
    """

    columns: list[int] = []
    for x in range(3, width - 3):
        runs = 0
        run = 0
        mass = 0
        for y in range(3, height - 3):
            if edge_values[y * width + x] > threshold:
                run += 1
            else:
                if 3 <= run <= 22:
                    runs += 1
                    mass += run
                run = 0
        if 3 <= run <= 22:
            runs += 1
            mass += run
        if runs >= 1 and mass >= 3:
            columns.append(x)
    if len(columns) < 8:
        return len(columns), 0.0
    gaps = [columns[index + 1] - columns[index] for index in range(len(columns) - 1)]
    small_gaps = [gap for gap in gaps if 1 <= gap <= 10]
    if len(small_gaps) < 6:
        return len(columns), 0.0
    counts: dict[int, int] = {}
    for gap in small_gaps:
        counts[gap] = counts.get(gap, 0) + 1
    mode_gap = max(counts.items(), key=lambda item: item[1])[0]
    regular = sum(count for gap, count in counts.items() if abs(gap - mode_gap) <= 1)
    return len(columns), regular / len(small_gaps)


def _dark_text_stats(
    gray_values: list[int],
    saturation_values: list[int],
    face_mask: list[bool],
    width: int,
    height: int,
) -> tuple[float, int, int, int, float, int]:
    """Organized ink-on-canvas glyph/label stats (polarity-independent).

    Returns organized mass, component count, text-row count, largest row size,
    bar-width coefficient of variation, and glyph component count. Dark-on-light
    and light-on-dark bars/glyphs both count when they sit on a contrasting
    canvas surround. High-sat color stripe fills and organic blobs do not.
    """

    dark = _ink_text_stats_for_polarity(
        gray_values,
        saturation_values,
        face_mask,
        width,
        height,
        polarity="dark",
    )
    light = _ink_text_stats_for_polarity(
        gray_values,
        saturation_values,
        face_mask,
        width,
        height,
        polarity="light",
    )

    def _text_quality(
        stats: tuple[float, int, int, int, float, int],
    ) -> tuple[int, int, int, float]:
        mass, _components, rows, max_row, bar_cv, glyphs = stats
        structured = int(glyphs >= 1 or max_row >= 2 or bar_cv >= 0.05)
        return (structured, rows, max_row, mass)

    # Prefer glyph/varied-bar structure over uniform stripe sheets, then rows/mass.
    if _text_quality(light) > _text_quality(dark):
        return light
    return dark


def _ink_text_stats_for_polarity(
    gray_values: list[int],
    saturation_values: list[int],
    face_mask: list[bool],
    width: int,
    height: int,
    *,
    polarity: str,
) -> tuple[float, int, int, int, float, int]:
    """Organized glyph/label stats for one ink polarity."""

    frame_area = width * height
    if polarity == "dark":
        ink_mask = tuple(
            (not face_mask[index]) and gray_values[index] < 100 for index in range(frame_area)
        )
    else:
        ink_mask = tuple(
            (not face_mask[index]) and gray_values[index] > 155 for index in range(frame_area)
        )
    components: list[dict[str, float | int | bool]] = []
    for component in _connected_components(ink_mask, width, height):
        if len(component) < 5 or len(component) > frame_area * 0.15:
            continue
        xs = [index % width for index in component]
        ys = [index // width for index in component]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bbox_width = max_x - min_x + 1
        bbox_height = max_y - min_y + 1
        if bbox_width >= width * 0.7 and bbox_height <= 3:
            continue
        if bbox_height < 3 or bbox_width < 3:
            continue
        border_touch = sum(
            1
            for index in component
            if (index % width) < 2
            or (index % width) >= width - 2
            or (index // width) < 2
            or (index // width) >= height - 2
        ) / len(component)
        if border_touch > 0.45:
            continue
        aspect = max(bbox_width, bbox_height) / max(min(bbox_width, bbox_height), 1)
        occupancy = len(component) / (bbox_width * bbox_height)
        mean_sat = sum(saturation_values[index] for index in component) / len(component)
        # Horizontal baselines/underlines only — not saturated color stripe fills.
        is_bar = bbox_width >= 4.0 * max(bbox_height, 1) and bbox_height <= 14 and mean_sat <= 145
        is_glyph = (
            len(component) <= 70
            and bbox_height <= 12
            and bbox_width <= 16
            and occupancy <= 0.85
            and (aspect >= 1.15 or occupancy <= 0.70)
        )
        if not (is_bar or is_glyph):
            continue
        outside: list[int] = []
        for index in component:
            x = index % width
            y = index // width
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    neighbor = ny * width + nx
                    if not ink_mask[neighbor]:
                        outside.append(neighbor)
        outside = list(set(outside))
        if len(outside) < 3:
            continue
        mean_in = sum(gray_values[index] for index in component) / len(component)
        mean_out = sum(gray_values[index] for index in outside) / len(outside)
        if polarity == "dark":
            # Dark ink on a distinctly brighter canvas surround.
            if mean_out < 110 or mean_out < mean_in + 30:
                continue
        else:
            # Light ink on a distinctly darker canvas surround.
            if mean_out > 120 or mean_in < mean_out + 30:
                continue
        components.append(
            {
                "n": len(component),
                "cx": sum(xs) / len(xs),
                "cy": sum(ys) / len(ys),
                "bh": bbox_height,
                "bw": bbox_width,
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
                "bar": is_bar,
                "glyph": is_glyph and not is_bar,
            }
        )

    if not components:
        return 0.0, 0, 0, 0, 0.0, 0

    used: set[int] = set()
    organized_pixels = 0
    organized_components = 0
    organized_glyphs = 0
    bar_widths: list[float] = []
    rows = 0
    max_row = 0
    for index, component in enumerate(components):
        if index in used:
            continue
        row = [
            other
            for other, candidate in enumerate(components)
            if abs(float(candidate["cy"]) - float(component["cy"])) <= 6
        ]
        used.update(row)
        row_components = [components[other] for other in row]
        accepted = False
        if any(bool(item["bar"]) for item in row_components):
            accepted = True
        else:
            span_x = (
                max(int(item["max_x"]) for item in row_components)
                - min(int(item["min_x"]) for item in row_components)
                + 1
            )
            span_y = (
                max(int(item["max_y"]) for item in row_components)
                - min(int(item["min_y"]) for item in row_components)
                + 1
            )
            heights = [int(item["bh"]) for item in row_components]
            height_ok = max(heights) <= min(heights) + 4
            if (len(row_components) >= 4 and height_ok and span_x >= max(22, 3.0 * span_y)) or (
                len(row_components) >= 6 and height_ok and span_x >= 28 and span_x >= 2.2 * span_y
            ):
                accepted = True
        if accepted:
            rows += 1
            organized_pixels += sum(int(item["n"]) for item in row_components)
            organized_components += len(row_components)
            organized_glyphs += sum(1 for item in row_components if item["glyph"])
            bar_widths.extend(float(item["bw"]) for item in row_components if item["bar"])
            max_row = max(max_row, len(row_components))
    if len(bar_widths) >= 2:
        mean_width = sum(bar_widths) / len(bar_widths)
        variance = sum((width - mean_width) ** 2 for width in bar_widths) / len(bar_widths)
        bar_width_cv = (variance**0.5) / mean_width if mean_width > 0 else 0.0
    else:
        bar_width_cv = 0.0
    return (
        organized_pixels / frame_area,
        organized_components,
        rows,
        max_row,
        bar_width_cv,
        organized_glyphs,
    )
