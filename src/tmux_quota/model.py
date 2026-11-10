"""Provider-independent measurements and a deterministic pace calculation."""

from dataclasses import dataclass
from datetime import datetime
import math


def number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class Window:
    label: str
    consumed: float | None
    duration: float
    resets_at: float | None
    observed_at: float | None
    last_known: bool = False

    def available(self, now: float, max_age: float) -> bool:
        return (
            self.consumed is not None
            and self.observed_at is not None
            and -60 <= now - self.observed_at <= max_age
            and (self.resets_at is None or self.resets_at > now)
        )

    def pace(self, now: float, max_age: float = 600) -> str:
        if (
            not self.available(now, max_age)
            or self.last_known
            or self.resets_at is None
            or self.duration <= 0
            or self.resets_at - now > self.duration + 60
        ):
            return "unknown"
        assert self.consumed is not None
        if self.consumed >= 100:
            return "red"
        # Grace floor: treat the first 2% of a period as 2% elapsed.
        elapsed = max(2, min(100, 100 * (1 - (self.resets_at - now) / self.duration)))
        ratio = self.consumed / elapsed
        if ratio <= 0.8:
            return "green"
        if ratio <= 1.1:
            return "blue"
        if ratio <= 1.4:
            return "amber"
        return "red"


@dataclass(frozen=True)
class Account:
    provider: str
    number: str
    label: str
    active: bool
    windows: tuple[Window, ...]
    identity: str | None = None
