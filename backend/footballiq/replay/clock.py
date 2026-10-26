"""Virtual match clock: ``current_ms`` bounds every computation; ``generation`` bumps on each seek."""

from __future__ import annotations

import time
from typing import Callable

ALLOWED_SPEEDS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)


class VirtualClock:
    def __init__(self, duration_ms: int, speed: float = 1.0, now: Callable[[], float] = time.monotonic):
        self.duration_ms = duration_ms
        self._now = now
        self._speed = speed
        self._anchor_ms = 0
        self._anchor_wall = now()
        self.paused = True
        self.generation = 0

    # -- reading -----------------------------------------------------------------
    @property
    def speed(self) -> float:
        return self._speed

    @property
    def current_ms(self) -> int:
        if self.paused:
            return self._anchor_ms
        elapsed = (self._now() - self._anchor_wall) * 1000.0 * self._speed
        return min(self.duration_ms, int(self._anchor_ms + elapsed))

    @property
    def finished(self) -> bool:
        return self.current_ms >= self.duration_ms

    # -- control -----------------------------------------------------------------
    def _rebase(self) -> None:
        self._anchor_ms = self.current_ms
        self._anchor_wall = self._now()

    def play(self) -> None:
        if self.paused:
            self._anchor_wall = self._now()
            self.paused = False

    def pause(self) -> None:
        if not self.paused:
            self._rebase()
            self.paused = True

    def set_speed(self, speed: float) -> None:
        if speed not in ALLOWED_SPEEDS:
            raise ValueError(f"speed must be one of {ALLOWED_SPEEDS}")
        self._rebase()
        self._speed = speed

    def seek(self, target_ms: int) -> int:
        self._anchor_ms = max(0, min(self.duration_ms, int(target_ms)))
        self._anchor_wall = self._now()
        self.generation += 1  # invalidate stale outputs
        return self.generation
