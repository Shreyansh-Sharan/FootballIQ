"""Agent tools. ``at_ms`` is fixed per run by the server, so an agent cannot read past the replay clock.

A tool with no data source returns {"unavailable": reason} instead of raising.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from footballiq.aliases import get_book
from footballiq.buildup import goal_buildup
from footballiq.replay.timeline import MatchTimeline
from footballiq.shots import shot_rows
from footballiq.shots import summary as shot_summary

MAX_OUTPUT_CHARS = 12_000


def _fn(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


TOOL_SPECS: list[dict[str, Any]] = [
    _fn("get_match_context", "Competition, teams (ids, names), venue, replay clock, period and score at the replay clock, "
        "and which data sources this match has (events, 360 snapshots, tracking provider). Call this first."),
    _fn("get_match_stats", "Team statistics accumulated up to the replay clock: possession, shots, on target, xG (provider benchmark), "
        "passes and accuracy, corners, fouls, cards, tackles."),
    _fn("get_key_events", "Most recent key events up to the replay clock (goals, cards, substitutions, shots, corners, penalties, "
        "tactical shifts), newest first, with minute, team, player and event_id.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 40, "description": "How many events (default 15)."},
         "team_id": {"type": "string", "description": "Only this team's events (optional)."},
         "types": {"type": "array", "items": {"type": "string", "enum": ["goal", "card", "substitution", "shot", "corner", "penalty", "tactical_shift"]},
                   "description": "Only these kinds (optional)."}}),
    _fn("get_forecasts", "Model forecasts at the replay clock from the strict chronological models (trained only on matches before "
        "this one): win/draw/loss at the end of the phase, goal in the next 10', corner in 2', penalty in 5', expected goals left, "
        "with uncertainty bands and the top drivers. Also pre-match Elo and form."),
    _fn("get_shot_quality", "Shooting so far: per-team shots, accuracy, xG per shot (difficulty), big chances, average distance and "
        "goal angle, plus the most recent shots with distance, angle, zone, defenders in the shot cone, our xG and the benchmark xG.",
        {"last_n": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Recent shots to list (default 6)."}}),
    _fn("get_tactical_shape", "Shapes detected from tracking out of possession (smoothed formation per team and confirmed switches so "
        "far) and the latest completed tactical window per team: our possession vs the benchmark, width and depth in possession."),
    _fn("get_physical", "Physical output from tracking up to the replay clock: distance, high-speed running, sprints and top speed per "
        "player, top N per team.", {"top": {"type": "integer", "minimum": 1, "maximum": 11, "description": "Players per team (default 5)."}}),
    _fn("get_player_form", "Player form at the replay clock for one team (or both): impact index per 15' (recent vs earlier), flags "
        "(dip, fatigue, card_risk, in_form) with their reasons, key stats, role, and tournament form before this match.",
        {"team_id": {"type": "string", "description": "Team id from get_match_context (optional = both teams)."}}),
    _fn("get_substitution_options", "Ranked substitution options for a team at the replay clock: who to take off and who to bring on, "
        "each with the reasons (fatigue, performance dip, card risk, game state, bench player's tournament form).",
        {"team_id": {"type": "string"}}, ["team_id"]),
    _fn("get_best_player", "Best player on the pitch for a situation (penalty, corner, free_kick, counter, defend), ranked with reasons "
        "from this match and the tournament so far.",
        {"team_id": {"type": "string"},
         "situation": {"type": "string", "enum": ["penalty", "corner", "free_kick", "counter", "defend"]}}, ["team_id", "situation"]),
]

# Tools only the agent team uses. The Foundry agents get TOOL_SPECS (definitions.py), so adding a tool here leaves them as
# they are.
TEAM_TOOL_SPECS: list[dict[str, Any]] = [
    _fn("get_goal_buildup", "How a goal (or any shot) was made, up to the replay clock: how and where the conceding team lost the "
        "ball (or which restart or foul started it), each action of the move with pressure, the defending actions against it, "
        "and where the conceding team's players were when the ball was lost, at the last pass and at the shot (players "
        "goal-side of the ball vs attackers ahead of it, last-line height, nearest defender, keeper off the line). Defaults to "
        "the latest goal and lists every goal so far with its event_id.",
        {"event_id": {"type": "string", "description": "A goal or shot event_id from this tool or get_key_events (optional = "
                                                       "the latest goal)."}}),
]

_TYPE_TEST: dict[str, Callable[[Any], bool]] = {
    "goal": lambda e: e.is_goal or e.is_own_goal, "card": lambda e: bool(e.card), "substitution": lambda e: e.type == "Substitution",
    "shot": lambda e: e.type == "Shot", "corner": lambda e: e.subtype == "Corner", "penalty": lambda e: e.subtype == "Penalty",
    "tactical_shift": lambda e: e.type == "Tactical Shift",
}


def _minute(clock_label: str) -> str:
    """'67:30' -> "68'", '90+02:10' -> "90+3'" (scoreboard style)."""
    base, _, extra = clock_label.partition("+")
    if extra:
        m, _, s = extra.partition(":")
        return f"{base}+{int(m) + (1 if int(s or 0) or int(m) == 0 else 0)}'"
    m, _, s = clock_label.partition(":")
    return f"{int(m) + 1}'" if int(s or 0) or int(m) == 0 else f"{int(m)}'"


@dataclass
class MatchTools:
    """Executes tool calls for one run; the optional providers are Fabric stores."""

    timeline: MatchTimeline
    at_ms: int
    predictions: Callable[[str, int], dict[str, Any]] | None = None
    model_xg: Callable[[str, int], tuple[dict[str, dict[str, Any]], str | None]] | None = None
    tactical: Any = None
    coach: Any = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def match_id(self) -> str:
        return self.timeline.match.canonical_match_id

    def run(self, name: str, arguments: str | dict[str, Any] | None) -> str:
        """Run one tool call; returns JSON text and never raises."""
        args: dict[str, Any] = {}
        book = get_book()   # the model sees only public ids and fictional names
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else dict(arguments or {})
            if book.enabled:
                args = book.from_public(args)
            fn = getattr(self, f"tool_{name}", None)
            out = fn(**args) if fn else {"error": f"unknown tool {name!r}"}
        except Exception as exc:  # noqa: BLE001 - a broken tool must not break the run; the agent reports it
            out = {"unavailable": f"{type(exc).__name__}: {exc}"[:300]}
        if book.enabled:
            out = book.to_public(out, self.match_id)
        text = json.dumps(out, default=str, separators=(",", ":"))
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + '..."truncated"'
        self.calls.append({"name": name, "arguments": args, "ok": "unavailable" not in out and "error" not in out, "chars": len(text)})
        return text

    def tool_get_match_context(self) -> dict[str, Any]:
        m, st = self.timeline.match, self.timeline.state_at(self.at_ms)
        tr = self.timeline.tracking
        return {
            "match_id": self.match_id, "competition": m.competition, "season": m.season, "stage": m.stage,
            "date": m.kickoff_source[:10], "stadium": m.stadium,
            "home": {"team_id": m.home.team_id, "name": m.home.name}, "away": {"team_id": m.away.team_id, "name": m.away.name},
            "replay_clock": st["clock_label"], "minute": _minute(st["clock_label"]), "period": st["period_label"],
            "score": st["score"], "shootout": st["shootout"], "finished_at_this_clock": st["finished"],
            "data": {"events": True, "event_snapshots_360": bool(self.timeline.frames),
                     "tracking": None if tr is None else {"source": tr.source, "hz": tr.hz}},
            "note": "Everything you are given stops at the replay clock. You cannot know what happens later in this match.",
        }

    def tool_get_match_stats(self) -> dict[str, Any]:
        st = self.timeline.state_at(self.at_ms)
        keep = ("goals", "shots", "shots_on_target", "provider_xg", "possession_pct", "passes_attempted", "passes_completed",
                "pass_accuracy_pct", "corners", "fouls", "yellow_cards", "red_cards", "tackles", "tackles_won", "tackle_success_pct")
        return {"replay_clock": st["clock_label"],
                "teams": {tid: {k: v for k, v in s.items() if k in keep} for tid, s in st["stats"].items()},
                "source": "events up to the replay clock; provider_xg = the event provider's xG (provider benchmark)"}

    def tool_get_key_events(self, limit: int = 15, team_id: str | None = None, types: list[str] | None = None) -> dict[str, Any]:
        tests = [_TYPE_TEST[t] for t in (types or []) if t in _TYPE_TEST]
        out = []
        for e in reversed(self.timeline.events_between(-1, self.at_ms)):
            if e.is_shootout:
                continue
            if team_id and e.team_id != team_id:
                continue
            if tests and not any(t(e) for t in tests):
                continue
            if not tests and not (e.is_goal or e.is_own_goal or e.card or e.type in ("Shot", "Substitution", "Tactical Shift")
                                  or e.subtype in ("Corner", "Penalty")):
                continue
            out.append({"event_id": e.event_id, "minute": _minute(e.clock_label), "team_id": e.team_id, "player": e.player_name,
                        "type": "Goal" if e.is_goal else "Own goal" if e.is_own_goal else e.type, "detail": e.card or e.subtype,
                        "outcome": e.outcome, "xg_statsbomb": e.provider_xg,
                        **({"replaced_by": e.recipient_name} if e.type == "Substitution" else {}),
                        **({"formation": e.formation} if e.formation else {})})
            if len(out) >= max(1, min(40, int(limit))):
                break
        return {"replay_clock": self.timeline.clock_label_at(self.at_ms), "events": out}

    def tool_get_forecasts(self) -> dict[str, Any]:
        if self.predictions is None:
            return {"unavailable": "model forecasts need the Fabric source (nb_ml_score)"}
        p = self.predictions(self.match_id, self.at_ms)
        if p.get("feature_cutoff_ms") is None:
            return {"unavailable": "no forecast at this clock yet"}
        r4 = lambda v: None if v is None else round(v, 4)
        teams = {tid: {target: {"p": r4(f["probability"]), "band": [r4(f["low"]), r4(f["high"])] if f["low"] is not None else None,
                                "value": r4(f["value"]), "drivers": f["drivers"][:3]} for target, f in fs.items()}
                 for tid, fs in p["teams"].items()}
        return {"model_version": p["model_version"], "model_trained_on_data_before": p.get("model_cutoff"),
                "features_cut_at_ms": p["feature_cutoff_ms"], "phase": p["phase"], "phase_remaining_s": p["phase_remaining_s"],
                "draw_end_of_phase": r4((p.get("draw_phase") or {}).get("probability")), "teams": teams,
                "prematch_strength": p.get("prematch"),
                "how_to_read": "win_phase/draw = outcome at the end of the current phase (regulation or extra time); drivers are "
                               "LightGBM log-odds contributions (positive raises the forecast); band = 10th-90th bootstrap percentile."}

    def tool_get_shot_quality(self, last_n: int = 6) -> dict[str, Any]:
        model_xg, version = ({}, None)
        if self.model_xg is not None:
            try:
                model_xg, version = self.model_xg(self.match_id, self.at_ms)
            except Exception:  # noqa: BLE001 - provider xG still works
                model_xg, version = {}, None
        m = self.timeline.match
        frames = {f.event_id: f for f in self.timeline.frames}
        rows = shot_rows(self.timeline.events_between(-1, self.at_ms), frames, m.home.team_id, model_xg)
        keep = ("event_id", "clock_label", "team_id", "player_name", "type", "outcome", "play_pattern", "distance_m", "angle_deg",
                "zone", "xg", "xg_statsbomb", "difficulty", "under_pressure", "defenders_in_cone", "keeper_off_line_m")
        recent = [{k: s.get(k) for k in keep} for s in rows[-max(1, min(20, int(last_n))):]][::-1]
        return {"xg_model": version or "benchmark xG (our model not scored for this match)",
                "teams": shot_summary(rows, [m.home.team_id, m.away.team_id]), "recent_shots": recent}

    def tool_get_tactical_shape(self) -> dict[str, Any]:
        if self.tactical is None:
            return {"unavailable": "tactical tables need the Fabric source and tracking data"}
        forms = self.tactical.formations(self.match_id, self.at_ms)
        latest: dict[str, dict[str, Any]] = {}
        for s in forms.get("segments", []):
            latest[s["team_id"]] = {"formation": s["formation"], "confidence": s.get("confidence")}
        windows: dict[str, dict[str, Any]] = {}
        for w in self.tactical.timeline(self.match_id, self.at_ms):
            windows[w["team_id"]] = {k: w.get(k) for k in ("label", "formation", "declared_formation", "possession_pct",
                                                            "possession_pct_statsbomb", "width_in_possession_m", "depth_in_possession_m")}
        return {"method": forms.get("method"), "shape_now": latest, "switches_so_far": forms.get("switches", []),
                "latest_completed_window": windows,
                "note": "Shapes are detected from tracking out of possession, not the team sheet; windows open only after they end."}

    def tool_get_physical(self, top: int = 5) -> dict[str, Any]:
        if self.tactical is None:
            return {"unavailable": "physical metrics need the Fabric source and tracking data"}
        rows = self.tactical.physical(self.match_id, self.at_ms)
        out: dict[str, list[dict[str, Any]]] = {}
        for r in sorted(rows, key=lambda r: -r["distance_km"]):
            team = out.setdefault(r["team_id"], [])
            if len(team) < max(1, min(11, int(top))):
                team.append({k: r.get(k) for k in ("name", "position_group", "distance_km", "hsr_km", "sprint_km", "top_speed_kmh",
                                                   "minutes_tracked", "on_pitch")})
        return {"source": "tracking, summed over seconds up to the replay clock", "top_by_distance": out}

    def tool_get_goal_buildup(self, event_id: str | None = None) -> dict[str, Any]:
        out = goal_buildup(self.timeline, self.at_ms, event_id)
        if "goal" in out:
            out["goal"]["minute"] = _minute(out["goal"]["clock"])
        return out

    def _need_coach(self) -> Any:
        if self.coach is None:
            raise RuntimeError("player analytics are not available")
        return self.coach

    def tool_get_player_form(self, team_id: str | None = None) -> dict[str, Any]:
        data = self._need_coach().players(self.match_id, self.at_ms, team_id)
        keep = ("name", "role", "on_pitch", "minutes", "impact_per15", "recent_per15", "earlier_per15", "flags", "reasons", "booked")
        teams = {}
        for tid, players in data["teams"].items():
            teams[tid] = [{**{k: p.get(k) for k in keep},
                           "stats": {k: p["stats"].get(k) for k in ("goals", "shots", "xg", "pass_pct", "def_actions", "losses", "xt_added")},
                           "physical": p.get("physical"),
                           "tournament_before_today": {k: (p.get("history") or {}).get(k) for k in ("matches", "goals", "xg", "pens", "pen_goals")}}
                          for p in players if p.get("on_pitch") or p.get("minutes")]
        return {"replay_clock": data["replay_clock"], "teams": teams, "sources": data["sources"], "impact_note": data["impact_note"]}

    def tool_get_substitution_options(self, team_id: str) -> dict[str, Any]:
        return self._need_coach().substitutions(self.match_id, self.at_ms, team_id)

    def tool_get_best_player(self, team_id: str, situation: str) -> dict[str, Any]:
        return self._need_coach().best(self.match_id, self.at_ms, team_id, situation)
