"""Per-match matchday data (series + moments), built once and cut at the replay clock.

Without tracking there is no shape or heat; without gold tables, Poisson win chance and heuristic xPass.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import OrderedDict
from typing import Any

import numpy as np

from footballiq.ball_flight import flight as ball_flight
from footballiq.matchday.flow import STEP_MS, FlowIndex, flow_series
from footballiq.matchday.moments import Moment, Physical, clock_minute, detect, heuristic_xpass
from footballiq.matchday.shape import ShapeIndex, match_id_for, player_roles
from footballiq.matchday.winprob import ModelWin, win_series
from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.replay.timeline import MatchTimeline

log = logging.getLogger(__name__)
HEAT_COLS, HEAT_ROWS = 21, 14
DEFAULT_COLORS = ({"primary": "#3d96d8", "secondary": "#ffffff", "ink": "#0d2440", "pattern": "solid"},
                  {"primary": "#e9475f", "secondary": "#ffffff", "ink": "#ffffff", "pattern": "solid"})


class MatchdayData:
    def __init__(self, tl: MatchTimeline, *, physical_rows=None, xpass=None, model_win: ModelWin | None = None):
        t0 = time.time()
        self.tl = tl
        self.flow_idx = FlowIndex(tl)
        self.flow = flow_series(self.flow_idx)
        self.times = [t for t, _ in self.flow]
        try:
            self.shape_idx = ShapeIndex(tl, dead=self.flow_idx.dead) if tl.tracking is not None else None
        except ValueError:
            self.shape_idx = None
        self.shapes = [(t, self.shape_idx.at(t)) for t in self.times] if self.shape_idx else None
        home, away = tl.team_ids
        self.scores = [(lambda s: (s[home]["goals"], s[away]["goals"]))(tl.stats_at(t)) for t in self.times]
        score_at = dict(zip(self.times, self.scores))
        self.win = win_series(tl, self.times, lambda t: score_at[t], model_win)
        self.physical = Physical(physical_rows, lambda team, shirt, pid: match_id_for(tl, team, shirt, pid))
        self.roles = player_roles(tl)
        self.xpass = xpass or {}
        shot_kmh = {}
        if tl.tracking is not None:
            for e in tl.events:
                if e.type == "Shot" and not e.is_shootout:
                    try:
                        f = ball_flight(tl.tracking, e, e.team_id == home, e.match_elapsed_ms + 3_000)
                        if f.get("available") and f.get("speed_kmh"):
                            shot_kmh[e.event_id] = float(f["speed_kmh"])
                    except Exception:  # noqa: BLE001 - one odd shot must not sink the match
                        log.debug("ball flight failed for %s", e.event_id, exc_info=True)
        self.moments: list[Moment] = detect(tl, self.flow, self.shapes, self.physical, self.xpass, shot_kmh, self.roles)
        self.moment_t = np.array([m.t_ms for m in self.moments], dtype=np.int64)
        log.info("matchday %s: %d points, %d moments, shape=%s, physical=%s in %.1fs", tl.match.canonical_match_id,
                 len(self.flow), len(self.moments), self.shape_idx is not None, bool(self.physical), time.time() - t0)

    # ------------------------------------------------------------------ cuts at the replay clock
    def series(self, to_ms: int) -> dict[str, Any]:
        k = int(np.searchsorted(np.asarray(self.times), to_ms, side="right"))
        pts = []
        for i in range(k):
            t, flow = self.flow[i]
            pts.append({"t_ms": t, "clock": clock_minute(self.tl, t), "score": list(self.scores[i]), "win": self.win[i],
                        "flow": flow, "shape": self.shapes[i][1] if self.shapes else [None, None]})
        return {"step_ms": STEP_MS, "points": pts}

    def moments_until(self, to_ms: int) -> list[dict[str, Any]]:
        k = int(np.searchsorted(self.moment_t, to_ms, side="right"))
        return [m.to_dict() for m in self.moments[:k]]


class MatchdayService:
    def __init__(self, tactical=None, predictions=None, max_cached: int = 4):
        """tactical / predictions: zero-arg callables returning the stores (or raising when unavailable)."""
        self._tactical, self._predictions = tactical, predictions
        self._cache: OrderedDict[str, MatchdayData] = OrderedDict()
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self.max_cached = max_cached

    def _optional(self, fn, label: str):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - Fabric gold tables are optional inputs
            log.info("matchday: %s unavailable (%s)", label, exc)
            return None

    def data(self, tl: MatchTimeline) -> MatchdayData:
        mid = tl.match.canonical_match_id
        with self._lock:
            if mid in self._cache:
                self._cache.move_to_end(mid)
                return self._cache[mid]
            lock = self._locks.setdefault(mid, threading.Lock())
        with lock:   # single flight per match
            with self._lock:
                if mid in self._cache:
                    return self._cache[mid]
            tac = self._optional(self._tactical, "tactical store") if self._tactical else None
            pred = self._optional(self._predictions, "prediction store") if self._predictions else None
            physical = self._optional(lambda: tac.physical_index(mid), "physical") if tac and tl.tracking is not None else None
            xpass = self._optional(lambda: pred.xpass_by_event(mid), "xPass") if pred else None
            model = None
            if pred:
                s = self._optional(lambda: pred.series(mid, tl.match.duration_ms, step_ms=STEP_MS), "win model")
                if s:
                    model = ModelWin(s, *tl.team_ids)
            d = MatchdayData(tl, physical_rows=physical, xpass=xpass, model_win=model)
            with self._lock:
                self._cache[mid] = d
                while len(self._cache) > self.max_cached:
                    self._cache.popitem(last=False)
            return d


# ---------------------------------------------------------------------- meta + player focus
def _book():
    """Alias book when pseudonyms are on, else None, so real and fictional names never mix."""
    try:
        from footballiq.aliases import get_book
        book = get_book()
        return book if getattr(book, "enabled", False) else None
    except Exception:  # noqa: BLE001 - the alias layer is optional (pseudonyms off / not installed)
        return None


def _short(name: str, nickname: str | None = None) -> str:
    """Broadcast short name: nickname minus its first word, else the last name."""
    if nickname and len(nickname.split()) > 1:
        return " ".join(nickname.split()[1:])
    if nickname:
        return nickname
    parts = name.split()
    return parts[-1] if parts else name


def meta(tl: MatchTimeline, roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    m = tl.match
    book = _book()
    teams = []
    for k, t in enumerate((m.home, m.away)):
        a = book.team(t.team_id) if book else None
        teams.append({"team_id": t.team_id, "side": ("home", "away")[k], "name": t.name,
                      "short": getattr(a, "short", None) or t.name[:3].upper(),
                      "name_hi": getattr(a, "name_hi", None) or t.name, "short_hi": getattr(a, "short_hi", None) or t.name[:3].upper(),
                      "colors": getattr(a, "colors", None) or DEFAULT_COLORS[k]})
    side = {m.home.team_id: "home", m.away.team_id: "away"}
    players = []
    for p in m.players:
        a = book.player(p.player_id) if book else None
        r = roles.get(p.player_id, {})
        players.append({"player_id": p.player_id, "team_id": p.team_id, "side": side.get(p.team_id),
                        "name": p.name, "short": getattr(a, "short", None) or _short(p.name, p.nickname),
                        "name_hi": getattr(a, "name_hi", None) or p.name, "short_hi": getattr(a, "short_hi", None) or _short(p.name, p.nickname),
                        "number": p.jersey_number, "position": r.get("position"), "role": r.get("role", "MID"), "starter": p.starter})
    base = {1: 0, 2: 45, 3: 90, 4: 105, 5: 120}
    return {
        "match_id": m.canonical_match_id, "competition": m.competition, "stage": m.stage,
        "date": (m.kickoff_utc or m.kickoff_source or "")[:10] or None, "stadium": m.stadium,
        "home": teams[0], "away": teams[1],
        "periods": [{"period": p.period, "label": p.label, "start_ms": p.start_match_ms, "duration_ms": p.duration_ms,
                     "base_minute": base.get(p.period, 0)} for p in m.periods],
        "duration_ms": m.duration_ms, "players": players, "has_tracking": tl.tracking is not None,
        "tracking_hz": round(tl.tracking.hz) if tl.tracking is not None else None,
    }


TOUCH_TYPES = {"Pass", "Ball Receipt*", "Carry", "Shot", "Dribble", "Clearance", "Interception", "Ball Recovery", "Miscontrol"}
ACTION_TYPES = {"Pass", "Shot", "Carry", "Dribble", "Duel", "Interception", "Ball Recovery", "Clearance", "Block",
                "Foul Committed", "Foul Won", "Goal Keeper", "Miscontrol", "Dispossessed", "Pressure", "50/50"}


def player_focus(d: MatchdayData, player_id: str, at_ms: int) -> dict[str, Any] | None:
    from footballiq.players import _stints

    tl = d.tl
    if not any(p.player_id == player_id for p in tl.match.players):
        return None
    stint = _stints(tl, at_ms).get(player_id)
    minutes = round((stint[1] - stint[0]) / 60_000, 1) if stint else 0.0
    on_pitch = bool(stint) and stint[1] >= at_ms   # off == at_ms while still on
    evs = [e for e in tl.events_between(-1, at_ms) if not e.is_shootout and (e.player_id == player_id or e.recipient_id == player_id)]
    mine = [e for e in evs if e.player_id == player_id]
    home = tl.match.home.team_id
    passes = [e for e in mine if e.type == "Pass" and e.subtype != "Throw-in"]
    ok = [e for e in passes if e.outcome == "Complete"]

    def xp(e):
        v = d.xpass.get(e.event_id)
        if v is None and None not in (e.x_m, e.y_m, e.end_x_m, e.end_y_m):
            v = heuristic_xpass(e, e.team_id == home)
        return v

    diffs = [1 - v for v in (xp(e) for e in passes) if v is not None]
    shots = [e for e in mine if e.type == "Shot"]
    duels_won = sum(1 for e in mine if (e.type == "Duel" and e.outcome in ("Won", "Success In Play", "Success Out"))
                    or e.type in ("Interception", "Ball Recovery"))
    run = d.physical.at(player_id, at_ms) or {}
    names = {p.player_id: p.name for p in tl.match.players}
    actions = []
    for e in mine:
        if e.type not in ACTION_TYPES:
            continue
        detail = ""
        if e.type == "Pass" and None not in (e.x_m, e.end_x_m):
            v = xp(e)
            detail = f"-> {_short(names.get(e.recipient_id, '') or '')} · {round(math.hypot(e.end_x_m - e.x_m, e.end_y_m - e.y_m))} m" \
                     + (f" · {round(100 * (1 - v))}/100" if v is not None else "")
        elif e.type == "Shot":
            detail = f"{(e.provider_xg or 0):.2f} xG · {e.outcome or ''}"
        actions.append({"t_ms": e.match_elapsed_ms, "clock": clock_minute(tl, e.match_elapsed_ms), "type": e.type, "detail": detail,
                        "ok": None if e.type not in ("Pass", "Dribble", "Duel") else e.outcome in ("Complete", "Won", "Success In Play", "Success Out")})
    heat = None
    seen = d.shape_idx.seen.get(player_id) if d.shape_idx is not None else None
    if seen is not None:
        ts, xy = seen
        k = int(np.searchsorted(ts, at_ms, side="right"))
        xy = xy[:k]
        counts = np.zeros((HEAT_ROWS, HEAT_COLS), dtype=np.int64)
        if len(xy):
            ci = np.clip((xy[:, 0] / PITCH_LENGTH_M * HEAT_COLS).astype(int), 0, HEAT_COLS - 1)
            ri = np.clip((xy[:, 1] / PITCH_WIDTH_M * HEAT_ROWS).astype(int), 0, HEAT_ROWS - 1)
            np.add.at(counts, (ri, ci), 1)
        heat = {"cols": HEAT_COLS, "rows": HEAT_ROWS, "counts": counts.ravel().tolist()}
    return {
        "player_id": player_id, "on_pitch": on_pitch, "minutes": minutes,
        "dist_km": run.get("km"), "top_kmh": run.get("top_kmh"), "sprints": run.get("sprints"),
        "touches": sum(1 for e in mine if e.type in TOUCH_TYPES),
        "passes": len(passes), "passes_ok": len(ok), "pass_diff": round(100 * float(np.mean(diffs))) if diffs else None,
        "shots": len(shots), "xg": round(sum(e.provider_xg or 0 for e in shots), 2), "goals": sum(1 for e in shots if e.is_goal),
        "duels_won": duels_won, "heat": heat, "actions": actions[-60:],
    }
