"""Common spatial schema for every position source, in the canonical frame with provenance flags.

An unknown observation state stays NULL; it never becomes an observed coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PROVIDERS = {
    "pff_fc": ("broadcast_cv", 29.97),
    "dfl_idsse": ("optical", 25.0),
    "skillcorner": ("broadcast_cv", 10.0),
    "statsbomb_360": ("event_snapshot", None),
}

POSITION_COLUMNS = [
    "source_provider", "tracking_method", "match_id", "period", "frame_num", "match_elapsed_ms", "team_id", "side",
    "jersey_num", "player_id", "x_m", "y_m", "speed_mps", "is_observed", "is_extrapolated", "confidence",
]
FRAME_COLUMNS = [
    "source_provider", "tracking_method", "match_id", "period", "frame_num", "match_elapsed_ms", "ball_x_m", "ball_y_m",
    "ball_z_m", "ball_is_observed", "ball_is_extrapolated", "ball_alive", "players_on_pitch", "players_observed",
    "coverage_score",
]


@dataclass(frozen=True)
class Flags:
    is_observed: bool | None
    is_extrapolated: bool | None


def pff_flags(visibility: str | None) -> Flags:
    """PFF: VISIBLE = seen on the broadcast, ESTIMATED = inferred off camera, anything else unknown."""
    if visibility == "VISIBLE":
        return Flags(True, False)
    if visibility == "ESTIMATED":
        return Flags(False, True)
    return Flags(None, None)


def skillcorner_flags(is_detected: bool | None) -> Flags:
    """SkillCorner: is_detected False means the position was extrapolated by SkillCorner."""
    if is_detected is None:
        return Flags(None, None)
    return Flags(bool(is_detected), not bool(is_detected))


def optical_flags(x: float | None, y: float | None) -> Flags:
    """Optical in-stadium tracking (DFL): a reported coordinate is a measurement; a missing one is unknown."""
    if x is None or y is None:
        return Flags(None, None)
    return Flags(True, False)


def statsbomb_360_flags() -> Flags:
    """360 freeze-frame positions are measured, for visible players at one instant."""
    return Flags(True, False)


def coverage(flags: Iterable[bool | None]) -> float | None:
    """Share of players observed in a frame; NULL when any player's state is unknown (never guessed)."""
    vals = list(flags)
    if not vals or any(v is None for v in vals):
        return None
    return round(sum(1 for v in vals if v) / len(vals), 3)
