"""Event-time match timeline; ``state_at(t)`` uses only events at or before t, in O(log n).

Snapshots are precomputed per event, so play, seek and rewind give identical state for the same t.
"""

from __future__ import annotations

import bisect
import copy
from typing import TYPE_CHECKING, Any

from footballiq.ingest.statsbomb import clock_label
from footballiq.schema import PERIOD_LABELS, FreezeFrame, Match, MatchEvent

if TYPE_CHECKING:
    from footballiq.replay.tracking import TrackingTimeline

PASS_EXCLUDED_SUBTYPES = {"Throw-in"}
PASS_EXCLUDED_OUTCOMES = {"Unknown", "Injury Clearance"}
ON_TARGET = {"Goal", "Saved", "Saved To Post"}
TACKLE_WON = {"Won", "Success In Play", "Success Out"}
# how long a 360 snapshot stays on the pitch view
FREEZE_FRAME_TTL_MS = 4_000


def _empty_team_stats() -> dict[str, Any]:
    return {
        "goals": 0,
        "shootout_goals": 0,
        "shots": 0,
        "shots_on_target": 0,
        "provider_xg": 0.0,
        "passes_attempted": 0,
        "passes_completed": 0,
        "corners": 0,
        "fouls": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "tackles": 0,
        "tackles_won": 0,
        "possession_ms": 0,
    }


class MatchTimeline:
    def __init__(self, match: Match, events: list[MatchEvent], frames: list[FreezeFrame] | None = None,
                 tracking: "TrackingTimeline | None" = None):
        self.match = match
        self.tracking = tracking
        self.events = sorted(events, key=lambda e: (e.match_elapsed_ms, e.source_sequence))
        self.times = [e.match_elapsed_ms for e in self.events]
        self.frames = sorted(frames or [], key=lambda f: f.match_elapsed_ms)
        self.frame_times = [f.match_elapsed_ms for f in self.frames]
        self.team_ids = (match.home.team_id, match.away.team_id)
        self._snapshots = self._build_snapshots()

    # ------------------------------------------------------------------ precompute
    def _build_snapshots(self) -> list[dict[str, dict[str, Any]]]:
        stats = {tid: _empty_team_stats() for tid in self.team_ids}
        snaps: list[dict[str, dict[str, Any]]] = []
        for i, ev in enumerate(self.events):
            # event-based possession: gap since the previous event goes to its possession team
            if i > 0:
                prev = self.events[i - 1]
                if prev.period == ev.period and prev.period < 5 and prev.possession_team_id in stats:
                    stats[prev.possession_team_id]["possession_ms"] += ev.match_elapsed_ms - prev.match_elapsed_ms
            self._apply(stats, ev)
            snaps.append(copy.deepcopy(stats))
        return snaps

    def _apply(self, stats: dict[str, dict[str, Any]], ev: MatchEvent) -> None:
        s = stats.get(ev.team_id) if ev.team_id else None
        if s is None:
            return
        if ev.type == "Shot":
            if ev.is_shootout:
                if ev.is_goal:
                    s["shootout_goals"] += 1
                return
            s["shots"] += 1
            if ev.outcome in ON_TARGET:
                s["shots_on_target"] += 1
            if ev.is_goal:
                s["goals"] += 1
            if ev.provider_xg:
                s["provider_xg"] = round(s["provider_xg"] + ev.provider_xg, 4)
        elif ev.is_own_goal and not ev.is_shootout:
            s["goals"] += 1
        elif ev.type == "Pass":
            if ev.subtype == "Corner":
                s["corners"] += 1
            if ev.subtype not in PASS_EXCLUDED_SUBTYPES and ev.outcome not in PASS_EXCLUDED_OUTCOMES:
                s["passes_attempted"] += 1
                if ev.outcome == "Complete":
                    s["passes_completed"] += 1
        elif ev.type == "Foul Committed":
            s["fouls"] += 1
        elif ev.type == "Duel" and ev.subtype == "Tackle":
            s["tackles"] += 1
            if ev.outcome in TACKLE_WON:
                s["tackles_won"] += 1
        if ev.card in ("Yellow Card",):
            s["yellow_cards"] += 1
        elif ev.card in ("Red Card", "Second Yellow"):
            s["red_cards"] += 1

    # ------------------------------------------------------------------ queries
    def index_at(self, t_ms: int) -> int:
        """Number of events visible at replay time ``t_ms`` (inclusive)."""
        return bisect.bisect_right(self.times, t_ms)

    def events_between(self, from_ms: int, to_ms: int) -> list[MatchEvent]:
        """Events with from_ms < match_elapsed_ms <= to_ms."""
        lo = bisect.bisect_right(self.times, from_ms)
        hi = bisect.bisect_right(self.times, to_ms)
        return self.events[lo:hi]

    def period_at(self, t_ms: int) -> int:
        current = self.match.periods[0].period
        for p in self.match.periods:
            if t_ms >= p.start_match_ms:
                current = p.period
        return current

    def clock_label_at(self, t_ms: int) -> str:
        period = self.period_at(t_ms)
        start = next(p.start_match_ms for p in self.match.periods if p.period == period)
        return clock_label(period, max(0, t_ms - start))

    def stats_at(self, t_ms: int) -> dict[str, dict[str, Any]]:
        k = self.index_at(t_ms)
        if k == 0:
            stats = {tid: _empty_team_stats() for tid in self.team_ids}
        else:
            stats = copy.deepcopy(self._snapshots[k - 1])
            last = self.events[k - 1]
            if last.period < 5 and last.possession_team_id in stats and self.period_at(t_ms) == last.period:
                stats[last.possession_team_id]["possession_ms"] += t_ms - last.match_elapsed_ms
        total_poss = sum(s["possession_ms"] for s in stats.values())
        for s in stats.values():
            s["possession_pct"] = round(100 * s["possession_ms"] / total_poss, 1) if total_poss else None
            s["pass_accuracy_pct"] = round(100 * s["passes_completed"] / s["passes_attempted"], 1) if s["passes_attempted"] else None
            s["tackle_success_pct"] = round(100 * s["tackles_won"] / s["tackles"], 1) if s["tackles"] else None
        return stats

    def freeze_frame_at(self, t_ms: int) -> FreezeFrame | None:
        i = bisect.bisect_right(self.frame_times, t_ms)
        if i == 0:
            return None
        ff = self.frames[i - 1]
        return ff if t_ms - ff.match_elapsed_ms <= FREEZE_FRAME_TTL_MS else None

    def _ball_at(self, t_ms: int, last_located: MatchEvent | None) -> dict[str, Any] | None:
        tb = _tracking_ball(self.tracking, t_ms)
        if tb is not None:
            return tb
        if last_located is None:
            return None
        return {"x_m": last_located.end_x_m or last_located.x_m, "y_m": last_located.end_y_m or last_located.y_m,
                "observed": False, "source": "last_event_location"}

    def state_at(self, t_ms: int) -> dict[str, Any]:
        t_ms = max(0, min(int(t_ms), self.match.duration_ms))
        stats = self.stats_at(t_ms)
        home, away = self.team_ids
        period = self.period_at(t_ms)
        k = self.index_at(t_ms)
        last_located = next((e for e in reversed(self.events[:k]) if e.x_m is not None), None)
        return {
            "match_id": self.match.canonical_match_id,
            "replay_t_ms": t_ms,
            "period": period,
            "period_label": PERIOD_LABELS.get(period, str(period)),
            "clock_label": self.clock_label_at(t_ms),
            "score": {home: stats[home]["goals"], away: stats[away]["goals"]},
            "shootout": (
                {home: stats[home]["shootout_goals"], away: stats[away]["shootout_goals"]} if period >= 5 else None
            ),
            "stats": stats,
            "events_visible": k,
            "ball": self._ball_at(t_ms, last_located),
            "finished": t_ms >= self.match.duration_ms,
        }


KEY_EVENT_TYPES = {"Starting XI", "Shot", "Substitution", "Own Goal For", "Half Start", "Half End", "Tactical Shift"}


def is_key_event(ev: MatchEvent) -> bool:
    """Events shown in the condensed feed and on the timeline."""
    return ev.is_goal or bool(ev.card) or ev.type in KEY_EVENT_TYPES or ev.subtype in ("Corner", "Penalty")


def _tracking_ball(tracking, t_ms: int) -> dict[str, Any] | None:
    f = tracking.latest_frame(t_ms, max_age_ms=1000) if tracking is not None else None
    if f is None or f[2] is None:
        return None
    bx, by, _bz, obs = f[2]
    return {"x_m": bx, "y_m": by, "observed": bool(obs), "source": "pff_tracking", "frame_num": f[1]}


def event_payload(ev: MatchEvent) -> dict[str, Any]:
    """Compact event representation for the UI / WebSocket."""
    return ev.model_dump(
        include={
            "event_id", "source_sequence", "period", "match_elapsed_ms", "clock_label", "team_id",
            "player_id", "player_name", "type", "subtype", "outcome", "x_m", "y_m", "end_x_m", "end_y_m",
            "is_goal", "is_own_goal", "is_shootout", "provider_xg", "card", "recipient_id", "recipient_name", "has_freeze_frame",
            "play_pattern", "possession_team_id", "formation", "under_pressure",
        }
    ) | {"is_key": is_key_event(ev)}
