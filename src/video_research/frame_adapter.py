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

    version: str = "evidence-frame-v3"
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
        raise ExtractionError(
            "frame selection count does not match canonical coverage windows"
        )

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
    config_version: str = "evidence-frame-v3"

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
    interior_indexes = [
        y * width + x
        for y in range(1, height - 1)
        for x in range(1, width - 1)
    ]
    edge_fraction = (
        sum(edge_values[index] > config.edge_threshold for index in interior_indexes)
        / len(interior_indexes)
    )

    warm_mask = tuple(
        _is_skin_tone(pixel, config.skin_max_saturation)
        for pixel in image.get_flattened_data()
    )
    warm_fraction = sum(warm_mask) / len(warm_mask)
    face_regions = _face_like_regions(
        warm_mask, gray_values, edge_values, width, height, config
    )
    compact_face_regions = tuple(
        region
        for region in face_regions
        if region.bbox_fraction <= config.face_component_max_bbox_fraction
    )
    component_fraction, bbox_fraction, component_occupancy = _largest_region_stats(
        face_regions
    )
    face_mass = sum(region.fraction for region in face_regions)
    face_mask = _region_bbox_mask(compact_face_regions, width, height, frame_area)
    has_evidence = _has_evidence_structure(
        gray_values,
        edge_values,
        saturation_channel,
        warm_mask,
        face_mask,
        interior_indexes,
        width,
        config,
    )
    face_primary = (
        face_mass >= config.face_primary_mass_fraction
        or (
            face_mass > 0.0
            and component_fraction >= config.face_primary_largest_fraction
        )
    )
    has_face = face_mass >= config.small_face_component_fraction
    blank_or_transition = (
        variance < config.min_variance or edge_fraction < config.min_edge_fraction
    )
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
        if item.features.largest_warm_component_fraction
        < config.small_face_component_fraction
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
        sum(abs(a - b) for a, b in zip(left_pixels, right_pixels, strict=True))
        / len(left_pixels),
        3,
    )


def _is_skin_tone(
    pixel: tuple[int, int, int], max_saturation: float = 0.62
) -> bool:
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
        internal_variance = sum(
            (gray_values[index] - mean_gray) ** 2 for index in component
        ) / len(component)
        textured = (
            internal_edges >= config.face_internal_edge_fraction
            or internal_variance >= config.face_internal_variance
        )
        if not textured:
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
    config: FrameSelectionConfig,
) -> bool:
    """True when non-face pixels look like a chart, slide, numbers, or labeled UI.

    Empty canvas alone is not evidence. Positive text/chart/UI structure is required.
    """

    frame_area = len(gray_values)
    canvas_pixels = sum(
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
    canvas_fraction = canvas_pixels / frame_area

    text_on_canvas = 0
    height = frame_area // width
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            index = row + x
            if face_mask[index] or warm_mask[index] or edge_values[index] <= 48:
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = (y + dy) * width + (x + dx)
                if _is_canvas_pixel(
                    neighbor,
                    gray_values,
                    edge_values,
                    saturation_values,
                    warm_mask,
                    face_mask,
                ):
                    text_on_canvas += 1
                    break
    text_fraction = text_on_canvas / frame_area

    lowsat_strong = sum(
        edge_values[index] > config.strong_edge_threshold
        and saturation_values[index] < 90
        for index in interior_indexes
    ) / len(interior_indexes)
    highsat_strong = sum(
        edge_values[index] > config.strong_edge_threshold
        and saturation_values[index] >= 90
        for index in interior_indexes
    ) / len(interior_indexes)
    structure_edges = sum(
        edge_values[index] > config.strong_edge_threshold
        for index in interior_indexes
    ) / len(interior_indexes)

    return (
        (
            canvas_fraction >= config.evidence_canvas_with_text_fraction
            and text_fraction >= config.evidence_text_on_canvas_fraction
        )
        or lowsat_strong >= config.evidence_lowsat_strong_edge_fraction
        or highsat_strong >= config.evidence_highsat_strong_edge_fraction
        or (
            canvas_fraction >= config.evidence_canvas_with_structure_fraction
            and structure_edges >= config.evidence_structure_edge_fraction
        )
    )
