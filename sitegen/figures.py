"""Figures attached to a news story: typed numbers plus the geometry the templates draw.

Every value here is copied from the story's structured data; nothing is parsed out of prose.
"""

import math
from dataclasses import dataclass


def fmt(value: float) -> str:
    """30.0 -> "30", 30.3 -> "30.3": print a number the way the source wrote it."""
    return f"{value:g}"


@dataclass(frozen=True)
class Stat:
    label: str
    value: str
    unit: str = ""


@dataclass(frozen=True)
class Numbers:
    """A handful of headline numbers."""

    stats: tuple[Stat, ...]
    kind = "numbers"


@dataclass(frozen=True)
class CompareRow:
    label: str
    unit: str
    a: float
    b: float


@dataclass(frozen=True)
class Compare:
    """Trial arm against comparator, one row per measure."""

    arm_a: str
    arm_b: str
    rows: tuple[CompareRow, ...]
    kind = "compare"

    def width(self, row: CompareRow, value: float) -> float:
        """Bar length in percent of the track, zero-based.

        Rows in the same unit share one scale, so 12.8 months is drawn shorter than 30.3 months.
        A percentage is drawn against 100.
        """
        if row.unit == "%":
            return round(value, 1)
        top = max(max(r.a, r.b) for r in self.rows if r.unit == row.unit)
        return round(100 * value / top, 1)


@dataclass(frozen=True)
class Meter:
    label: str
    percent: float
    detail: str = ""


@dataclass(frozen=True)
class Meters:
    """Several proportions, one per named group, each against 100%."""

    rows: tuple[Meter, ...]
    kind = "meters"


_TICKS = (0.1, 0.25, 0.5, 1, 2, 4, 8)


@dataclass(frozen=True)
class Interval:
    """A ratio (HR, OR) with its confidence interval, drawn on a log scale around `reference`."""

    label: str
    point: float
    low: float
    high: float
    note: str = ""
    reference: float = 1.0
    kind = "interval"

    @property
    def _domain(self) -> tuple[float, float]:
        low = max(t for t in _TICKS if t <= min(self.low, self.reference))
        high = min(t for t in _TICKS if t >= max(self.high, self.reference))
        return low, high

    def x(self, value: float) -> float:
        """Horizontal position in percent."""
        low, high = self._domain
        return round(100 * (math.log(value) - math.log(low)) / (math.log(high) - math.log(low)), 1)

    @property
    def ticks(self) -> list[tuple[str, float]]:
        low, high = self._domain
        return [(fmt(t), self.x(t)) for t in _TICKS if low <= t <= high]


Figure = Numbers | Compare | Meters | Interval
