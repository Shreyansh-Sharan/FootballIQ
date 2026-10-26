"""Canonical schema shared by ingestion, the replay engine and the API.

Records keep provider ids and source coordinates; time is ``match_elapsed_ms`` on one clock across periods.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

PERIOD_LABELS = {1: "1st half", 2: "2nd half", 3: "Extra time 1", 4: "Extra time 2", 5: "Penalty shootout"}
# scoreboard start minute per period
PERIOD_BASE_MINUTE = {1: 0, 2: 45, 3: 90, 4: 105, 5: 120}


class Team(BaseModel):
    team_id: str
    name: str
    source_ids: dict[str, int | str]


class Player(BaseModel):
    player_id: str
    team_id: str
    name: str
    nickname: str | None = None
    jersey_number: int | None = None
    starter: bool = False
    source_ids: dict[str, int | str]


class Period(BaseModel):
    period: int
    label: str
    start_match_ms: int = Field(description="Start of the period on the canonical match clock")
    duration_ms: int


class Match(BaseModel):
    canonical_match_id: str
    competition: str
    season: str
    stage: str | None = None
    kickoff_utc: str | None = None
    kickoff_source: str = Field(description="Kick-off exactly as the provider reports it (timezone may be unspecified)")
    stadium: str | None = None
    referee: str | None = None
    home: Team
    away: Team
    periods: list[Period]
    duration_ms: int
    source_ids: dict[str, int | str]
    players: list[Player]
    # never exposed by replay endpoints (no spoilers)
    result: dict[str, Any]
    direction_convention: str = "home attacks left->right (x=0 -> x=105) in all periods"
    attribution: str | None = None


class MatchEvent(BaseModel):
    event_id: str
    match_id: str
    provider: str
    source_sequence: int
    period: int
    period_elapsed_ms: int
    match_elapsed_ms: int
    clock_label: str
    team_id: str | None
    team_name: str | None
    player_id: str | None = None
    player_name: str | None = None
    type: str
    subtype: str | None = None
    outcome: str | None = None
    x_m: float | None = None
    y_m: float | None = None
    end_x_m: float | None = None
    end_y_m: float | None = None
    source_location: list[float] | None = None
    possession: int | None = None
    possession_team_id: str | None = None
    play_pattern: str | None = None
    duration_ms: int | None = None
    under_pressure: bool = False
    # derived, so counters need not re-parse provider qualifiers
    is_goal: bool = False
    is_own_goal: bool = False
    is_shootout: bool = False
    provider_xg: float | None = None
    card: str | None = None
    recipient_id: str | None = None
    recipient_name: str | None = None
    related_events: list[str] = Field(default_factory=list)
    has_freeze_frame: bool = False
    observed: bool = True
    formation: str | None = None  # declared on Starting XI / Tactical Shift events


class FreezeFramePlayer(BaseModel):
    x_m: float
    y_m: float
    team_id: str
    teammate: bool
    actor: bool
    keeper: bool


class FreezeFrame(BaseModel):
    """StatsBomb 360 snapshot: discrete, event-linked; NOT continuous tracking."""

    event_id: str
    match_elapsed_ms: int
    players: list[FreezeFramePlayer]
    visible_area: list[list[float]] = Field(default_factory=list)
    source: str = "statsbomb_360"
    observed: bool = True
