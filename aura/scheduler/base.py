"""Track-selection interface (ТЗ §3.6).

Phase 1 ships a repetition-aware random selector behind the same interface the
future bandit / ranker / RL backends will use, so the rest of the app is
already written against ``SchedulerBackend.select_next``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from ..library.manager import TrackInfo


@dataclass(slots=True)
class Context:
    """Everything the scheduler knows about "now".

    Phase 1 fills only ``time_of_day``; the Activity Monitor (phase 3) will
    populate process/activity/foreign-audio fields.
    """

    process_name: str | None = None
    activity_level: str = "unknown"  # idle | low | medium | high | unknown
    time_of_day: str = "day"  # morning | day | evening | night
    foreign_audio: bool = False
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.process_name or '-'}|{self.activity_level}|{self.time_of_day}"

    @staticmethod
    def from_clock(hour: int) -> "Context":
        return Context(time_of_day=time_of_day(hour))


def time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "day"
    if 18 <= hour < 23:
        return "evening"
    return "night"


class SchedulerBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def select_next(
        self, context: Context, candidates: list[TrackInfo], recent: list[str]
    ) -> TrackInfo | None:
        """Pick the next track. ``recent`` are track ids, oldest → newest."""
        raise NotImplementedError

    def report_result(self, track_id: str, rating: int | None) -> None:  # noqa: ARG002
        """Optional feedback hook (used by bandit/RL backends in later phases)."""


class RandomScheduler(SchedulerBackend):
    """Uniform pick with a recency penalty — good enough to smoke-test the app.

    score = 1 / (1 + times_in_recent) with a small jitter, so a track that just
    played is unlikely to repeat immediately but is never starved.
    """

    name = "random"

    def __init__(self, history: int = 8, rng: random.Random | None = None) -> None:
        self.history = max(1, history)
        self._rng = rng or random.Random()

    def select_next(
        self, context: Context, candidates: list[TrackInfo], recent: list[str]
    ) -> TrackInfo | None:  # noqa: ARG002 - context unused in phase 1
        if not candidates:
            return None
        weights = Counter(recent[-self.history :])
        scored: list[tuple[float, TrackInfo]] = []
        for track in candidates:
            penalty = 1.0 / (1.0 + weights.get(track.id, 0))
            jitter = self._rng.random() * 0.3
            scored.append((penalty + jitter, track))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]


class SchedulerFactory:
    """Registry so settings can switch backends without a restart (ТЗ §3.6)."""

    _builders: dict[str, type[SchedulerBackend]] = {"random": RandomScheduler}

    @classmethod
    def register(cls, name: str, builder: type[SchedulerBackend]) -> None:
        cls._builders[name] = builder

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls._builders)

    @classmethod
    def create(cls, name: str) -> SchedulerBackend:
        builder = cls._builders.get(name)
        if builder is None:
            builder = cls._builders["random"]
        return builder()
