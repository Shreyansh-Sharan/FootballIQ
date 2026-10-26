"""Perspective-UI moments, detected once per match from data up to each t; the client renders them.

Keys in ``f`` are the template placeholders listed in docs/MATCHDAY_API.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from footballiq.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from footballiq.replay.timeline import MatchTimeline
from footballiq.matchday.winprob import poisson_at

CHANCE_XG = 0.18
ROCKET_KMH = 100.0
PASS_MIN_M = 22.0
PASS_START_RECORD = 0.42
PASS_COOLDOWN_MS = 480_000
SPRINT_START_KMH = 30.0
SPRINT_STEP_KMH = 0.3
SPRINT_AFTER_MS = 180_000
SPRINT_COOLDOWN_MS = 300_000     # one "fastest so far" per 5', unless the record moves by 1 km/h
PASS_MIN_FORWARD_M = 10.0
PASS_MIN_END_HEIGHT_M = 60.0
SET_PIECES = {"Corner", "Free Kick", "Throw-in", "Goal Kick", "Kick Off", "Penalty"}
CARD = {"Yellow Card": "yellow", "Second Yellow": "second_yellow", "Red Card": "red"}


@dataclass
class Moment:
    t_ms: int
    kind: str
    side: int | None
    imp: float
    f: dict[str, Any]
    variant: str | None = None
    player_id: str | None = None
    player2_id: str | None = None
    team_id: str | None = None
    clock: str = ""
    id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "t_ms": self.t_ms, "clock": self.clock, "kind": self.kind, "variant": self.variant,
                "side": self.side, "team_id": self.team_id, "player_id": self.player_id, "player2_id": self.player2_id,
                "imp": round(self.imp, 3), "f": self.f}


def clock_minute(tl: MatchTimeline, t_ms: int) -> str:
    """'57′', '45+2′', '105+1′', 'PEN' from the canonical clock."""
    period = tl.period_at(t_ms)
    if period >= 5:
        return "PEN"
    p = next((x for x in tl.match.periods if x.period == period), None)
    base = {1: 0, 2: 45, 3: 90, 4: 105}.get(period, 0)
    length = {1: 45, 2: 45, 3: 15, 4: 15}.get(period, 45)
    elapsed = int((t_ms - (p.start_match_ms if p else 0)) // 60_000)
    return f"{base + length}+{elapsed - length + 1}′" if elapsed >= length else f"{base + elapsed + 1}′"


def _sig(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def heuristic_xpass(e, home: bool) -> float:
    """Fallback completion probability: longer, more forward, pressured or into the box is harder."""
    length = math.hypot(e.end_x_m - e.x_m, e.end_y_m - e.y_m)
    fwd = (e.end_x_m - e.x_m) if home else (e.x_m - e.end_x_m)
    end_h = e.end_x_m if home else PITCH_LENGTH_M - e.end_x_m
    in_box = end_h >= PITCH_LENGTH_M - 16.5 and abs(e.end_y_m - PITCH_WIDTH_M / 2) <= 20.16
    return _sig(3.6 - 0.045 * length - 0.9 * max(0.0, fwd) / 28 - 0.8 * bool(e.under_pressure) - 0.7 * in_box)


class Physical:
    """Per-second running from gold_player_metrics_1s; empty without it."""

    def __init__(self, rows: list[dict[str, Any]] | None, id_for=None):
        """id_for(team_id, jersey, tracking player_id) -> match player id."""
        self.by_player: dict[str, dict[str, Any]] = {}
        for r in rows or []:
            if not r.get("player_id"):
                continue
            pid = id_for(r.get("team_id"), r.get("jersey_num"), r["player_id"]) if id_for else r["player_id"]
            sec = np.asarray(r["second"], dtype=np.int64)
            dist = np.diff(np.concatenate([[0.0], np.asarray(r["cum_dist"], dtype=np.float64)]))
            fast = dist >= 7.0          # metres in one second = m/s
            starts = sec[1:][fast[1:] & fast[:-1] & ~np.concatenate([[False], fast[:-2]])] if len(sec) > 2 else np.empty(0, np.int64)
            self.by_player[pid] = {"sec": sec, "cum_dist": np.asarray(r["cum_dist"], dtype=np.float64),
                                              "cum_top": np.asarray(r["cum_top"], dtype=np.float64), "sprint_starts": starts,
                                              "team_id": r.get("team_id")}

    def __bool__(self) -> bool:
        return bool(self.by_player)

    def at(self, player_id: str | None, t_ms: int) -> dict[str, float] | None:
        p = self.by_player.get(player_id or "")
        if p is None:
            return None
        k = int(np.searchsorted(p["sec"], t_ms // 1000, side="right"))
        if k == 0:
            return {"km": 0.0, "top_kmh": 0.0, "sprints": 0}
        return {"km": round(float(p["cum_dist"][k - 1]) / 1000, 2), "top_kmh": round(float(p["cum_top"][k - 1]) * 3.6, 1),
                "sprints": int(np.searchsorted(p["sprint_starts"], t_ms // 1000, side="right"))}


def detect(tl: MatchTimeline, flow: list[tuple[int, dict]] | None = None, shapes: list[tuple[int, list]] | None = None,
           physical: Physical | None = None, xpass: dict[str, float] | None = None,
           shot_kmh: dict[str, float] | None = None, roles: dict[str, dict[str, Any]] | None = None) -> list[Moment]:
    home, away = tl.team_ids
    side = {home: 0, away: 1}
    physical = physical or Physical(None)
    xpass = xpass or {}
    shot_kmh = shot_kmh or {}
    roles = roles or {}
    out: list[Moment] = []
    score = [0, 0]
    txg = [0.0, 0.0]
    events = [e for e in tl.events if e.period <= 4 and not e.is_shootout]
    og_scorer: dict[int, str] = {}
    for e in events:
        if e.type == "Own Goal Against" and e.player_id:
            og_scorer[e.match_elapsed_ms] = e.player_id

    def wc(sc, t, k):
        p = poisson_at(tl, t, tuple(sc))
        return None if p is None else round(100 * (p[0] if k == 0 else p[2]))

    best_x, last_pass = PASS_START_RECORD, -10**12
    last_completed: dict[str, Any] = {}      # team -> last completed pass: the assist if it found the scorer
    for e in events:
        k = side.get(e.team_id)
        t = e.match_elapsed_ms
        if k is None:
            continue
        goal_x = PITCH_LENGTH_M if k == 0 else 0.0
        if e.type == "Pass" and e.outcome == "Complete":
            last_completed[e.team_id] = e
        if e.type == "Shot":
            xg = e.provider_xg or 0.0
            txg[k] += xg
            dist = round(math.hypot(goal_x - e.x_m, PITCH_WIDTH_M / 2 - e.y_m)) if e.x_m is not None else None
            spd = shot_kmh.get(e.event_id)
            if e.is_goal:
                before = list(score)
                score[k] += 1
                out.append(Moment(t, "goal", k, min(1.0, 0.6 + abs((wc(score, t, k) or 0) - (wc(before, t, k) or 0)) / 100),
                                  {"xg": round(xg, 2), "spd": round(spd) if spd else None, "dist": dist, "sa": score[0], "sb": score[1],
                                   "pen": e.subtype == "Penalty", "own_goal": False, "wcB": wc(before, t, k), "wcA": wc(score, t, k)},
                                  player_id=e.player_id, team_id=e.team_id, player2_id=_assist(last_completed.get(e.team_id), e)))
            elif xg >= CHANCE_XG:
                out.append(Moment(t, "chance", k, min(0.9, 0.25 + xg),
                                  {"xg": round(xg, 2), "spd": round(spd) if spd else None, "dist": dist, "txg": round(txg[k], 2)},
                                  player_id=e.player_id, team_id=e.team_id))
            elif spd and spd >= ROCKET_KMH:
                out.append(Moment(t, "speed", k, 0.3, {"spd": round(spd), "dist": dist, "xg": round(xg, 2)},
                                  variant="rocket", player_id=e.player_id, team_id=e.team_id))
        elif e.is_own_goal:
            before = list(score)
            score[k] += 1
            out.append(Moment(t, "goal", k, min(1.0, 0.6 + abs((wc(score, t, k) or 0) - (wc(before, t, k) or 0)) / 100),
                              {"xg": None, "spd": None, "dist": None, "sa": score[0], "sb": score[1], "pen": False, "own_goal": True,
                               "wcB": wc(before, t, k), "wcA": wc(score, t, k)}, player_id=og_scorer.get(t), team_id=e.team_id))
        if e.card in CARD:
            fouls = sum(1 for x in events if x.type == "Foul Committed" and x.team_id == e.team_id and t - 600_000 < x.match_elapsed_ms <= t)
            out.append(Moment(t, "card", k, 0.6 if CARD[e.card] != "yellow" else 0.28, {"card": CARD[e.card], "fouls": fouls},
                              player_id=e.player_id, team_id=e.team_id))
        elif e.type == "Substitution":
            off = physical.at(e.player_id, t) or {}
            out.append(Moment(t, "sub", k, 0.22, {"behind": score[k] < score[1 - k], "km": off.get("km"), "sprints": off.get("sprints")},
                              player_id=e.recipient_id, player2_id=e.player_id, team_id=e.team_id))
        elif (e.type == "Pass" and e.outcome == "Complete" and e.subtype not in SET_PIECES and e.recipient_id
              and None not in (e.x_m, e.y_m, e.end_x_m, e.end_y_m)):
            length = math.hypot(e.end_x_m - e.x_m, e.end_y_m - e.y_m)
            fwd = (e.end_x_m - e.x_m) if k == 0 else (e.x_m - e.end_x_m)
            end_h = e.end_x_m if k == 0 else PITCH_LENGTH_M - e.end_x_m
            # line-breaking pass into the attacking half, not from the goalkeeper
            if (length >= PASS_MIN_M and fwd >= PASS_MIN_FORWARD_M and end_h >= PASS_MIN_END_HEIGHT_M
                    and roles.get(e.player_id, {}).get("role") != "GK" and t - last_pass > PASS_COOLDOWN_MS):
                xp = xpass.get(e.event_id)
                xp = heuristic_xpass(e, k == 0) if xp is None else xp
                if xp < best_x:
                    best_x, last_pass = xp, t
                    out.append(Moment(t, "pass", k, 0.32, {"pdist": round(length), "diff": round(100 * (1 - xp)), "xpp": round(100 * xp)},
                                      player_id=e.player_id, player2_id=e.recipient_id, team_id=e.team_id))

    out += _flow_moments(flow or [], tl)
    out += _shape_moments(shapes or [], flow or [], tl)
    if physical:
        out += _physical_moments(physical, tl, side)
    out.sort(key=lambda m: (m.t_ms, m.kind))
    for i, m in enumerate(out):
        m.id = f"mo-{i + 1:04d}"
        m.clock = clock_minute(tl, m.t_ms)
        if m.side is not None and m.team_id is None:
            m.team_id = tl.team_ids[m.side]
    return out


def _assist(p, shot) -> str | None:
    """The pass that found the scorer in the last 15 s (not for penalties)."""
    if p is None or shot.subtype == "Penalty" or p.recipient_id != shot.player_id or shot.match_elapsed_ms - p.match_elapsed_ms > 15_000:
        return None
    return p.player_id


def _cooldown():
    last: dict[str, int] = {}

    def ready(key: str, t: int, gap: int) -> bool:
        if key in last and t - last[key] < gap:
            return False
        last[key] = t
        return True
    return ready


def _flow_moments(flow: list[tuple[int, dict]], tl: MatchTimeline) -> list[Moment]:
    out, ready = [], _cooldown()
    for i in range(2, len(flow)):
        t, w = flow[i]
        p, pp = flow[i - 1][1], flow[i - 2][1]
        if t < 300_000:
            continue
        if w["chaos"] >= 70 and p["chaos"] < 70 and ready("chaos", t, 420_000):
            c = w["comp"]
            out.append(Moment(t, "flow", None, 0.42, {"chaos": w["chaos"], "tov": round(c["turnovers"], 1), "tr": round(c["transitions"], 1),
                                                       "du": round(c["duels"], 1), "lb": round(100 * c["long_share"]), "seq": round(c["avg_seq"], 1)},
                              variant="chaos"))
        for k in (0, 1):
            if w["control"][k] >= 70 and w["control"][1 - k] <= 48 and w["chaos"] <= 50 and ready(f"ctl{k}", t, 540_000):
                out.append(Moment(t, "flow", k, 0.38, {"ctrl": w["control"][k], "poss": round(100 * w["poss_share"][k]),
                                                        "acc": round(100 * (w["pass_acc"][k] or 0))}, variant="control"))
        if w["pattern"] == p["pattern"] != pp["pattern"] and w["pattern"] != "balanced" and ready("rh", t, 300_000):
            out.append(Moment(t, "flow", w["siege_team"] if w["pattern"] == "siege" else None, 0.3,
                              {"pattern": w["pattern"], "tempo": w["tempo"], "bip": round(100 * w["bip"]), "seq": round(w["comp"]["avg_seq"], 1)},
                              variant="rhythm"))
    return out


def _shape_moments(shapes: list[tuple[int, list]], flow: list[tuple[int, dict]], tl: MatchTimeline) -> list[Moment]:
    """A state held for 3 points (90 s) with the ball mostly in play; 10' cooldown per team and kind."""
    out, ready = [], _cooldown()
    poss = {t: w["poss_share"] for t, w in flow}
    bip = {t: w["bip"] for t, w in flow}
    for i in range(2, len(shapes)):
        t = shapes[i][0]
        if bip.get(t, 1.0) < 0.5:
            continue
        for k in (0, 1):
            rows = [shapes[j][1][k] for j in (i - 2, i - 1, i)]
            if any(r is None or r["def"] is None for r in rows):
                continue
            avg = {key: float(np.mean([r[key] for r in rows if r[key] is not None] or [0])) for key in ("length", "width", "def", "gap_dm", "area")}
            share = (poss.get(t) or [0.5, 0.5])[k]
            f = {"len": round(avg["length"]), "wid": round(avg["width"]), "def": round(avg["def"]), "gap": round(avg["gap_dm"]), "area": round(avg["area"])}
            if (avg["length"] >= 34 or avg["gap_dm"] >= 13) and ready(f"str{k}", t, 600_000):
                out.append(Moment(t, "shape", k, 0.34, f, variant="stretched"))
            elif avg["def"] <= 22 and share < 0.4 and ready(f"low{k}", t, 600_000):
                out.append(Moment(t, "shape", k, 0.3, f, variant="lowblock"))
            elif avg["def"] >= 55 and share < 0.5 and ready(f"high{k}", t, 600_000):
                out.append(Moment(t, "shape", k, 0.3, f, variant="highline"))
    return out


def _physical_moments(phys: Physical, tl: MatchTimeline, side: dict[str, int]) -> list[Moment]:
    out = []
    # fastest sustained speed of the match so far
    jumps = []
    for pid, p in phys.by_player.items():
        top = p["cum_top"] * 3.6
        inc = np.flatnonzero(np.diff(np.concatenate([[0.0], top])) > 0)
        for i in inc:
            jumps.append((int(p["sec"][i]) * 1000, float(top[i]), pid))
    best = 0.0   # includes the unannounced first minutes
    told_v, told_t = 0.0, -10**12
    for t, v, pid in sorted(jumps):
        prev, best = best, max(best, v)
        new_record = v >= max(SPRINT_START_KMH, prev + SPRINT_STEP_KMH)
        if t >= SPRINT_AFTER_MS and new_record and (t - told_t >= SPRINT_COOLDOWN_MS or v >= told_v + 1.0):
            told_v, told_t = v, t
            st = phys.at(pid, t) or {}
            k = side.get(phys.by_player[pid]["team_id"])
            out.append(Moment(t, "speed", k, 0.3, {"spd": round(v, 1), "km": st.get("km"), "sprints": st.get("sprints")},
                              variant="sprint", player_id=pid))
    # first player of each team past 10 km
    for team, k in side.items():
        best = None
        for pid, p in phys.by_player.items():
            if p["team_id"] != team:
                continue
            j = int(np.searchsorted(p["cum_dist"], 10_000))
            if j < len(p["sec"]) and (best is None or p["sec"][j] < best[0]):
                best = (int(p["sec"][j]), pid)
        if best:
            st = phys.at(best[1], best[0] * 1000) or {}
            out.append(Moment(best[0] * 1000, "milestone", k, 0.22, {"km": st.get("km"), "sprints": st.get("sprints")},
                              variant="km10", player_id=best[1]))
    return out
