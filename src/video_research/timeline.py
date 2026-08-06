"""Source-timeline types: intervals, spans, coverage windows, material units.

Timestamps are integer milliseconds throughout. A float timeline makes the
partition check in :class:`CoverageManifest` report sub-nanosecond gaps that do
not exist, so the one arithmetic the completeness guarantee rests on would be
wrong. Raw engine timestamps are preserved verbatim on :class:`SourceSpan` for
evidence navigation; they are never used for arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import pairwise

Millis = int


@dataclass(frozen=True, order=True)
class TimeInterval:
    """A half-open interval ``[start_ms, end_ms)`` on the source timeline."""

    start_ms: Millis
    end_ms: Millis

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError(f"interval starts before the source: {self.start_ms}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"interval is empty or reversed: [{self.start_ms}, {self.end_ms})")

    @property
    def duration_ms(self) -> Millis:
        return self.end_ms - self.start_ms

    def contains(self, at_ms: Millis) -> bool:
        return self.start_ms <= at_ms < self.end_ms

    def within(self, outer: TimeInterval) -> bool:
        return self.start_ms >= outer.start_ms and self.end_ms <= outer.end_ms

    def label(self) -> str:
        return f"{_mmss(self.start_ms)}-{_mmss(self.end_ms)}"


def _mmss(at_ms: Millis) -> str:
    total = at_ms // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


class SpanKind(Enum):
    """What kind of source material an evidence location points at."""

    SPEECH = "speech"
    VISUAL = "visual"
    OCR = "ocr"


@dataclass(frozen=True)
class SourceSpan:
    """A precise, typed location in the source.

    A bare timestamp cannot distinguish "the speaker said this over these eleven
    seconds" from "this frame shows the error", so evidence carries a kind, an
    interval, and the identity of the artifact it was read from.
    """

    kind: SpanKind
    interval: TimeInterval
    artifact_id: str | None = None
    artifact_digest: str | None = None
    raw_timestamp: str | None = None

    def label(self) -> str:
        return f"{self.kind.value} {self.interval.label()}"


class SpeechCoverage(Enum):
    """What is known about speech in a :class:`CoverageWindow`."""

    CAPTURED = "captured"
    SILENCE_CONFIRMED = "silence_confirmed"
    UNOBSERVED = "unobserved"


class VisualObservation(Enum):
    """What is known about visuals in a :class:`CoverageWindow`.

    ``STATIC_CONFIRMED`` means the window was sampled and found unchanging, which
    is a positive observation. It is not the same as ``UNOBSERVED``, which is the
    absence of any look at all and blocks trusted completeness.
    """

    OBSERVED = "observed"
    STATIC_CONFIRMED = "static_confirmed"
    UNOBSERVED = "unobserved"


@dataclass(frozen=True)
class MaterialContentUnit:
    """An idea, demonstration, correction, caveat, number, or on-screen fact
    whose omission could change reader understanding or action."""

    unit_id: str
    description: str
    interval: TimeInterval


@dataclass(frozen=True)
class CoverageWindow:
    """One contiguous interval of the source with an explicit observation state."""

    interval: TimeInterval
    speech: SpeechCoverage
    visual: VisualObservation
    extraction_method: str
    material_unit_ids: tuple[str, ...] = ()

    @property
    def observed(self) -> bool:
        return (
            self.speech is not SpeechCoverage.UNOBSERVED
            and self.visual is not VisualObservation.UNOBSERVED
        )


@dataclass(frozen=True)
class CoverageManifest:
    """The partition of the whole source timeline into coverage windows."""

    duration_ms: Millis
    windows: tuple[CoverageWindow, ...] = field(default_factory=tuple)

    @property
    def timeline(self) -> TimeInterval:
        return TimeInterval(0, self.duration_ms)

    def partition_defects(self) -> tuple[str, ...]:
        """Describe every way the windows fail to tile ``[0, duration)`` exactly.

        Returns an empty tuple when the partition is exact. Each defect names the
        offending interval so a partial run can report where it stopped knowing.
        """
        if self.duration_ms <= 0:
            return ("source duration is not positive",)
        if not self.windows:
            return ("no coverage windows",)

        defects: list[str] = []
        ordered = sorted(self.windows, key=lambda w: w.interval)
        if tuple(ordered) != tuple(self.windows):
            defects.append("windows are not in timeline order")

        first = ordered[0].interval
        if first.start_ms != 0:
            defects.append(f"timeline starts uncovered before {_mmss(first.start_ms)}")

        for earlier, later in pairwise(ordered):
            if later.interval.start_ms > earlier.interval.end_ms:
                defects.append(
                    f"gap {_mmss(earlier.interval.end_ms)}-{_mmss(later.interval.start_ms)}"
                )
            elif later.interval.start_ms < earlier.interval.end_ms:
                defects.append(
                    f"overlap {_mmss(later.interval.start_ms)}-{_mmss(earlier.interval.end_ms)}"
                )

        last = ordered[-1].interval
        if last.end_ms < self.duration_ms:
            defects.append(f"tail uncovered {_mmss(last.end_ms)}-{_mmss(self.duration_ms)}")
        elif last.end_ms > self.duration_ms:
            defects.append(f"coverage runs past the source end at {_mmss(self.duration_ms)}")

        return tuple(defects)

    def unobserved_windows(self) -> tuple[CoverageWindow, ...]:
        return tuple(w for w in self.windows if not w.observed)

    def declared_unit_ids(self) -> frozenset[str]:
        return frozenset(uid for w in self.windows for uid in w.material_unit_ids)
