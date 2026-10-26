"""Canonical pitch: 105 x 68 m, origin top-left, home attacks towards x = 105 in every period."""

from __future__ import annotations

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0

STATSBOMB_LENGTH = 120.0
STATSBOMB_WIDTH = 80.0


def statsbomb_to_canonical(
    loc: list[float] | None, acting_team_is_home: bool
) -> tuple[float, float] | None:
    """StatsBomb location (acting team attacks x = 120) to canonical metres; None stays None."""
    if loc is None or len(loc) < 2:
        return None
    x = loc[0] * PITCH_LENGTH_M / STATSBOMB_LENGTH
    y = loc[1] * PITCH_WIDTH_M / STATSBOMB_WIDTH
    if not acting_team_is_home:
        x = PITCH_LENGTH_M - x
        y = PITCH_WIDTH_M - y
    return round(x, 2), round(y, 2)
