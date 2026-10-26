"""Player form at the replay clock: impact, dips, substitution options and the best player per situation.

Uses this match up to at_ms plus earlier matches in the competition; recommendations carry their reasons.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from footballiq.replay.timeline import MatchTimeline

MIN = 60_000
DEF_TYPES = {"Interception", "Ball Recovery", "Clearance", "Block"}
WON = {"Won", "Success", "Success In Play", "Success Out"}
SITUATIONS = ("penalty", "corner", "free_kick", "counter", "defend")
SUB_LIMIT = {"regulation": 5, "extra_time": 6}

HISTORY_SQL = """
select match_id, team_id, player_id, count(*) as n, avg(x_m) as ax,
  sum(case when type = 'Goal Keeper' then 1 else 0 end) as gk,
  sum(case when type = 'Shot' then 1 else 0 end) as shots,
  sum(case when is_goal then 1 else 0 end) as goals,
  sum(case when type = 'Shot' and subtype = 'Penalty' then 1 else 0 end) as pens,
  sum(case when type = 'Shot' and subtype = 'Penalty' and is_goal then 1 else 0 end) as pen_goals,
  sum(case when type = 'Shot' and subtype = 'Free Kick' then 1 else 0 end) as fk_shots,
  sum(case when type = 'Shot' and subtype = 'Free Kick' and is_goal then 1 else 0 end) as fk_goals,
  sum(case when type = 'Pass' and subtype = 'Corner' then 1 else 0 end) as corners,
  sum(case when type = 'Pass' and subtype = 'Free Kick' then 1 else 0 end) as fk_passes,
  sum(coalesce(provider_xg, 0)) as xg,
  sum(case when type in ('Interception', 'Ball Recovery', 'Clearance', 'Block') then 1 else 0 end) as def_actions,
  sum(case when type = 'Duel' and outcome in ('Won', 'Success', 'Success In Play', 'Success Out') then 1 else 0 end) as duels_won,
  sum(case when type in ('Dispossessed', 'Miscontrol') then 1 else 0 end) as losses,
  sum(case when type = 'Pass' then 1 else 0 end) as passes,
  sum(case when type = 'Pass' and outcome = 'Complete' then 1 else 0 end) as passes_completed,
  sum(case when type = 'Pressure' then 1 else 0 end) as pressures,
  sum(case when card like '%Yellow%' and card not like '%Second%' then 1 else 0 end) as yellows,
  max(player_name) as player_name,
  min(match_elapsed_ms) as first_ms, max(match_elapsed_ms) as last_ms
from t where player_id is not null group by match_id, team_id, player_id
"""
HISTORY_KEYS = ("shots", "goals", "pens", "pen_goals", "fk_shots", "fk_goals", "corners", "fk_passes", "xg", "def_actions",
                "duels_won", "losses", "passes", "passes_completed", "pressures", "yellows")
PROFILE_KEYS = ("goals", "shots", "xg", "corners", "passes", "passes_completed", "pressures", "def_actions", "losses", "yellows")


POSITION_ROLE = {"GK": "GK", "CB": "DEF", "LCB": "DEF", "RCB": "DEF", "LB": "DEF", "RB": "DEF", "LWB": "DEF", "RWB": "DEF",
                 "DM": "MID", "CM": "MID", "AM": "MID", "LM": "MID", "RM": "MID", "LW": "FWD", "RW": "FWD", "CF": "FWD", "ST": "FWD"}
LIKELY_GK_NUMBERS = {1, 12, 13, 23}   # only for players with no data at all


def _role(ax: float | None, gk_actions: int) -> str:
    if gk_actions > 0 and (ax is None or ax < 30):
        return "GK"
    if ax is None:
        return "?"
    return "DEF" if ax < 40 else "MID" if ax < 60 else "FWD"


class PlayerHistory:
    """Per player, per earlier match aggregates (from silver_match_event), oriented to the team's attack."""

    def __init__(self, rows: list[dict[str, Any]], matches: dict[str, dict[str, Any]]):
        self.by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.match_competition = {mid: m["competition"] for mid, m in matches.items()}
        for r in rows:
            m = matches.get(r["match_id"])
            if m is None:
                continue
            ax = r["ax"]
            if ax is not None and r["team_id"] != m["home"]:
                ax = 105.0 - ax                       # canonical frame: home attacks x = 105
            self.by_player[r["player_id"]].append({**r, "ax": ax, "date": m["date"], "competition": m["competition"],
                                                   "minutes": max(0.0, (r["last_ms"] - r["first_ms"]) / MIN)})

    def team_profile(self, team_id: str, date: str, competition: str) -> dict[str, Any]:
        """Per-match averages for and against from earlier competition matches, plus key players."""
        per_match: dict[str, dict[str, float]] = {}
        against: dict[str, dict[str, float]] = {}
        players: dict[str, dict[str, Any]] = {}
        for games in self.by_player.values():
            for g in games:
                if g["date"] >= date or g["competition"] != competition:
                    continue
                if g["team_id"] == team_id:
                    agg = per_match.setdefault(g["match_id"], dict.fromkeys(PROFILE_KEYS, 0.0))
                    for k in PROFILE_KEYS:
                        agg[k] += g[k] or 0
                    pl = players.setdefault(g["player_id"], {"player_id": g["player_id"], "name": g.get("player_name"), "matches": 0,
                                                              **{k: 0 for k in ("goals", "xg", "shots", "def_actions", "yellows")}})
                    pl["matches"] += 1
                    for k in ("goals", "xg", "shots", "def_actions", "yellows"):
                        pl[k] += g[k] or 0
        for games in self.by_player.values():
            for g in games:
                if g["match_id"] in per_match and g["team_id"] != team_id:
                    agg = against.setdefault(g["match_id"], dict.fromkeys(PROFILE_KEYS, 0.0))
                    for k in PROFILE_KEYS:
                        agg[k] += g[k] or 0
        n = len(per_match)
        avg = lambda rows, k: round(sum(r[k] for r in rows.values()) / n, 2) if n else None
        prof = {k: avg(per_match, k) for k in PROFILE_KEYS}
        prof["pass_pct"] = round(100 * prof["passes_completed"] / prof["passes"], 1) if n and prof["passes"] else None
        conceded = {k: avg(against, k) for k in ("goals", "shots", "xg")}
        key = sorted(players.values(), key=lambda p: -(p["goals"] * 2 + p["xg"] + 0.05 * p["def_actions"]))[:5]
        for p in key:
            p["xg"] = round(p["xg"], 2)
        return {"matches": n, "for": prof, "against": conceded, "key_players": key,
                "yellow_carriers": sorted((p for p in players.values() if p["yellows"]), key=lambda p: -p["yellows"])}

    def competition_of(self, match_id: str, fallback: str) -> str:
        """Competition as stored in history, by match id, since display names may be pseudonyms."""
        return self.match_competition.get(match_id, fallback)

    def before(self, player_id: str, date: str, competition: str) -> dict[str, Any]:
        games = [g for g in self.by_player.get(player_id, []) if g["date"] < date and g["competition"] == competition]
        out = {k: sum(g[k] or 0 for g in games) for k in HISTORY_KEYS}
        out["matches"] = len(games)
        out["minutes"] = round(sum(g["minutes"] for g in games))
        w = sum(g["n"] for g in games)
        out["ax"] = sum((g["ax"] or 0) * g["n"] for g in games) / w if w else None
        out["gk"] = sum(g["gk"] for g in games)
        return out


@dataclass
class PlayerForm:
    player_id: str
    name: str
    team_id: str
    jersey: int | None
    on_pitch: bool
    minutes: float
    role: str
    role_source: str = "inferred"
    booked: bool = False
    sent_off: bool = False
    stats: dict[str, float] = field(default_factory=dict)
    impact: float = 0.0
    impact_per15: float = 0.0
    recent_per15: float | None = None
    earlier_per15: float | None = None
    physical: dict[str, Any] | None = None
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    history: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _event_impact(e, xt: float | None) -> float:
    v = 0.0
    if xt and xt > 0:
        v += 10 * xt
    if e.type == "Shot":
        v += 4 * (e.provider_xg or 0) + (2 if e.is_goal else 0)
    elif e.type in DEF_TYPES:
        v += 0.25
    elif (e.type == "Duel" and e.outcome in WON) or (e.type == "Dribble" and e.outcome == "Complete"):
        v += 0.3
    elif e.type == "Pass":
        v += 0.02 if e.outcome == "Complete" else -0.08
    elif e.type in ("Dispossessed", "Miscontrol"):
        v -= 0.3
    elif e.type == "Foul Committed":
        v -= 0.15
    elif e.type == "Dribbled Past":
        v -= 0.2
    if e.card:
        v -= 2.0 if ("Red" in e.card or "Second" in e.card) else 0.5
    return v


def _stints(tl: MatchTimeline, at_ms: int) -> dict[str, tuple[int, int]]:
    """player_id -> (on_ms, off_ms) up to at_ms (off = at_ms while still on)."""
    on: dict[str, int] = {p.player_id: 0 for p in tl.match.players if p.starter}
    off: dict[str, int] = {}
    for e in tl.events_between(-1, at_ms):
        if e.type == "Substitution" and not e.is_shootout:
            if e.player_id:
                off[e.player_id] = e.match_elapsed_ms
            if e.recipient_id:
                on[e.recipient_id] = e.match_elapsed_ms
        elif e.card and ("Red" in e.card or "Second" in e.card) and e.player_id:
            off[e.player_id] = e.match_elapsed_ms
    return {p: (t0, off.get(p, at_ms)) for p, t0 in on.items()}


def player_form(tl: MatchTimeline, at_ms: int, *, history: PlayerHistory | None = None, xt_by_event: dict[str, float] | None = None,
                physical_now: list[dict[str, Any]] | None = None, physical_then: list[dict[str, Any]] | None = None,
                positions: dict[str, str] | None = None, window_min: int = 15) -> dict[str, list[PlayerForm]]:
    m = tl.match
    at_ms = max(0, min(int(at_ms), m.duration_ms))
    stints = _stints(tl, at_ms)
    window = window_min * MIN
    events = [e for e in tl.events_between(-1, at_ms) if not e.is_shootout and e.player_id]
    by_player: dict[str, list] = defaultdict(list)
    for e in events:
        by_player[e.player_id].append(e)
    phys_now = {r.get("player_id"): r for r in physical_now or [] if r.get("player_id")}
    phys_then = {r.get("player_id"): r for r in physical_then or [] if r.get("player_id")}
    home = m.home.team_id
    date = m.kickoff_source[:10]
    out: dict[str, list[PlayerForm]] = {m.home.team_id: [], m.away.team_id: []}
    for p in m.players:
        evs = by_player.get(p.player_id, [])
        stint = stints.get(p.player_id)
        hist = history.before(p.player_id, date, history.competition_of(m.canonical_match_id, m.competition)) if history else None
        on_pitch = stint is not None and stint[1] >= at_ms
        minutes = (stint[1] - stint[0]) / MIN if stint else 0.0
        xs = [e.x_m if p.team_id == home else 105.0 - e.x_m for e in evs if e.x_m is not None]
        gk = sum(e.type == "Goal Keeper" for e in evs) + (hist["gk"] if hist else 0)
        ax = sum(xs) / len(xs) if len(xs) >= 8 else (hist["ax"] if hist and hist["ax"] is not None else (sum(xs) / len(xs) if xs else None))
        pos = (positions or {}).get(p.player_id)
        role, source = (POSITION_ROLE[pos], f"tracking roster ({pos})") if pos in POSITION_ROLE else (_role(ax, gk), "inferred")
        if role == "?" and not (hist and hist["matches"]) and p.jersey_number in LIKELY_GK_NUMBERS:
            role, source = "GK", "likely goalkeeper (squad number, no minutes)"
        f = PlayerForm(p.player_id, p.nickname or p.name, p.team_id, p.jersey_number, on_pitch, round(minutes, 1), role,
                       role_source=source, history=hist)
        f.booked = any(e.card and "Yellow" in e.card for e in evs)
        f.sent_off = any(e.card and ("Red" in e.card or "Second" in e.card) for e in evs)
        passes = [e for e in evs if e.type == "Pass"]
        s = f.stats
        s["actions"] = len(evs)
        s["passes"] = len(passes)
        s["pass_pct"] = round(100 * sum(e.outcome == "Complete" for e in passes) / len(passes), 1) if passes else None
        s["shots"] = sum(e.type == "Shot" for e in evs)
        s["goals"] = sum(bool(e.is_goal) for e in evs)
        s["xg"] = round(sum(e.provider_xg or 0 for e in evs if e.type == "Shot"), 2)
        s["def_actions"] = sum(e.type in DEF_TYPES for e in evs)
        s["duels_won"] = sum(e.type == "Duel" and e.outcome in WON for e in evs)
        s["dribbles_won"] = sum(e.type == "Dribble" and e.outcome == "Complete" for e in evs)
        s["losses"] = sum(e.type in ("Dispossessed", "Miscontrol") for e in evs)
        s["fouls"] = sum(e.type == "Foul Committed" for e in evs)
        s["pressures"] = sum(e.type == "Pressure" for e in evs)
        s["corners"] = sum(e.type == "Pass" and e.subtype == "Corner" for e in evs)
        s["pens"] = sum(e.type == "Shot" and e.subtype == "Penalty" for e in evs)
        s["pen_goals"] = sum(e.type == "Shot" and e.subtype == "Penalty" and bool(e.is_goal) for e in evs)
        s["progressive_carries"] = sum(e.type == "Carry" and e.x_m is not None and e.end_x_m is not None and
                                       ((e.end_x_m - e.x_m) if p.team_id == home else (e.x_m - e.end_x_m)) >= 10 for e in evs)
        if xt_by_event is not None:
            s["xt_added"] = round(sum(max(0.0, xt_by_event.get(e.event_id) or 0) for e in evs), 3)
        imp = [(e.match_elapsed_ms, _event_impact(e, (xt_by_event or {}).get(e.event_id))) for e in evs]
        f.impact = round(sum(v for _, v in imp), 2)
        f.impact_per15 = round(15 * f.impact / minutes, 2) if minutes >= 5 else 0.0
        if stint and minutes >= window_min + 20 and on_pitch:
            cut = at_ms - window
            recent = sum(v for t, v in imp if t > cut)
            earlier_min = (cut - stint[0]) / MIN
            f.recent_per15 = round(15 * recent / window_min, 2)
            f.earlier_per15 = round(15 * sum(v for t, v in imp if t <= cut) / earlier_min, 2) if earlier_min > 0 else None
            losses_recent = sum(1 for e in evs if e.match_elapsed_ms > cut and e.type in ("Dispossessed", "Miscontrol"))
            if f.earlier_per15 is not None and f.earlier_per15 >= 0.8 and f.recent_per15 < 0.4 * f.earlier_per15:
                f.flags.append("dip")
                f.reasons.append(f"Impact {f.recent_per15:.1f} per 15' in the last {window_min}' vs {f.earlier_per15:.1f} before")
            if losses_recent >= 3:
                f.flags.append("dip")
                f.reasons.append(f"Lost the ball {losses_recent} times in the last {window_min}'")
        pn, pt = phys_now.get(p.player_id), phys_then.get(p.player_id)
        if pn:
            f.physical = {k: pn.get(k) for k in ("distance_km", "hsr_km", "sprint_km", "top_speed_kmh", "minutes_tracked")}
            if pt and pt["minutes_tracked"] >= 25 and pn["minutes_tracked"] - pt["minutes_tracked"] >= 10 and f.role != "GK":
                span = pn["minutes_tracked"] - pt["minutes_tracked"]
                usual_hsr = pt["hsr_km"] / pt["minutes_tracked"] * span
                usual_dist = pt["distance_km"] / pt["minutes_tracked"] * span
                rec_hsr, rec_dist = pn["hsr_km"] - pt["hsr_km"], pn["distance_km"] - pt["distance_km"]
                f.physical.update({"recent_hsr_m": round(1000 * rec_hsr), "usual_hsr_m": round(1000 * usual_hsr),
                                   "recent_distance_km": round(rec_dist, 2), "usual_distance_km": round(usual_dist, 2)})
                if usual_hsr >= 0.04 and rec_hsr < 0.5 * usual_hsr and rec_dist < 0.9 * usual_dist:
                    f.flags.append("fatigue")
                    f.reasons.append(f"High-speed running {1000 * rec_hsr:.0f} m in the last {span:.0f}' vs a usual {1000 * usual_hsr:.0f} m "
                                     f"(distance {rec_dist:.2f} vs {usual_dist:.2f} km)")
        if f.booked and on_pitch:
            late_fouls = sum(1 for e in evs if e.type == "Foul Committed" and e.match_elapsed_ms > min(
                (x.match_elapsed_ms for x in evs if x.card), default=at_ms))
            if late_fouls:
                f.flags.append("card_risk")
                f.reasons.append(f"Booked, and {late_fouls} foul{'s' if late_fouls > 1 else ''} since")
        if f.impact_per15 >= 2.0 and minutes >= 20:
            f.flags.append("in_form")
        f.flags = sorted(set(f.flags))
        out.setdefault(p.team_id, []).append(f)
    for team_players in out.values():
        team_players.sort(key=lambda f: (not f.on_pitch, -f.impact_per15))
    return out


def _form_score(h: dict[str, Any] | None) -> float:
    if not h or not h["matches"]:
        return 0.0
    return (h["goals"] * 1.0 + h["xg"] * 1.5 + 0.08 * h["def_actions"] + 0.05 * h["duels_won"]) / h["matches"]


METHOD = "rule-based coach analytics (not a trained model)"


def substitution_options(tl: MatchTimeline, at_ms: int, team_id: str, form: dict[str, list[PlayerForm]], top: int = 3) -> dict[str, Any]:
    m = tl.match
    st = tl.state_at(at_ms)
    period = st["period"]
    if period >= 5:
        return {"team_id": team_id, "remaining": 0, "options": [], "method": METHOD, "note": "Shoot-out: no substitutions."}
    made = sum(1 for e in tl.events_between(-1, at_ms) if e.type == "Substitution" and e.team_id == team_id and not e.is_shootout)
    limit = SUB_LIMIT["extra_time" if period >= 3 else "regulation"]
    remaining = max(0, limit - made)
    opp = m.away.team_id if team_id == m.home.team_id else m.home.team_id
    diff = st["score"][team_id] - st["score"][opp]
    minute = at_ms / MIN
    chasing = diff < 0 and minute >= 55
    protecting = diff > 0 and minute >= 70
    players = form.get(team_id, [])
    used = {p.player_id for p in players if p.minutes > 0 or p.on_pitch}
    bench = [p for p in players if not p.on_pitch and p.player_id not in used and not p.sent_off]
    top_impact = sorted((p.impact for p in players if p.on_pitch), reverse=True)[:2]
    outs = []
    for p in players:
        if not p.on_pitch or p.role == "GK" or p.minutes < 40:
            continue
        need, why = 0.0, list(p.reasons)
        talisman = bool(top_impact) and p.impact >= top_impact[-1] and p.impact > 0
        if "fatigue" in p.flags:
            need += 1.0
        if "dip" in p.flags:
            need += 0.9
        if "card_risk" in p.flags:
            need += 0.8
        elif p.booked and protecting:
            need += 0.3
            why.append("Booked while protecting a lead")
        if chasing and p.role in ("DEF", "MID") and p.impact_per15 < 1.0:
            need += 0.4
            why.append(f"Team trailing by {-diff}: low attacking output from a {p.role.lower()} ({p.impact_per15:.1f} impact per 15')")
        if p.minutes >= 70:
            need += 0.2
        scored = int(p.stats.get("goals", 0))
        if scored and "fatigue" not in p.flags and not (protecting and p.role == "FWD"):
            need -= 0.6
            why.append(f"Counterpoint: scored {scored} today; a quiet spell from a scorer may pass")
        elif talisman and "fatigue" not in p.flags:
            need -= 0.5
            why.append(f"Counterpoint: still one of the two highest-impact players today ({p.impact:.1f}); a quiet spell may pass")
        if need >= 0.8:
            outs.append((need, p, why))
    outs.sort(key=lambda x: -x[0])
    options = []
    taken: set[str] = set()
    for need, p, why in outs[:top]:
        want = "FWD" if chasing and p.role != "FWD" else ("DEF" if protecting and p.role == "FWD" else p.role)
        # known outfield role or earlier tournament minutes
        pool = [b for b in bench if b.player_id not in taken and b.role != "GK" and (b.role != "?" or (b.history or {}).get("matches"))]
        ranked = sorted(pool, key=lambda b: -((1.0 if b.role == want else 0.4 if b.role == "?" else 0.0) + _form_score(b.history)))
        if not ranked:
            options.append({"off": {"player_id": p.player_id, "name": p.name, "role": p.role, "minutes": p.minutes, "flags": p.flags},
                            "on": None, "urgency": "high" if need >= 1.6 else "medium", "score": round(need, 2), "why_off": why,
                            "why_on": ["No unused bench player with a known role or minutes in this tournament to recommend"]})
            continue
        b = ranked[0]
        taken.add(b.player_id)
        h = b.history or {}
        on_why = [f"Fresh legs ({b.role if b.role != '?' else 'role unknown'}, {b.role_source})"]
        if h.get("matches"):
            on_why.append(f"This tournament before today: {h['matches']} matches, {h['goals']} goals, xG {h['xg']:.2f}, "
                          f"{h['def_actions']} defensive actions")
        if b.role == want and want != p.role:
            on_why.append(f"A {want.lower()} for a {p.role.lower()}: {'more attacking threat while chasing' if chasing else 'more protection for the lead'}")
        options.append({"off": {"player_id": p.player_id, "name": p.name, "role": p.role, "minutes": p.minutes, "flags": p.flags},
                        "on": {"player_id": b.player_id, "name": b.name, "role": b.role, "history": h},
                        "urgency": "high" if need >= 1.6 else "medium", "score": round(need, 2),
                        "why_off": why, "why_on": on_why})
    context = ("chasing the game" if chasing else "protecting a lead" if protecting else "level" if diff == 0 else "ahead" if diff > 0 else "behind")
    return {"team_id": team_id, "remaining": remaining, "made": made, "context": context, "options": options if remaining else [], "method": METHOD,
            "note": None if remaining else "No substitutions left."}


def best_for(tl: MatchTimeline, at_ms: int, team_id: str, situation: str, form: dict[str, list[PlayerForm]], top: int = 3) -> dict[str, Any]:
    if situation not in SITUATIONS:
        raise ValueError(f"situation must be one of {SITUATIONS}")
    ranked = []
    for p in form.get(team_id, []):
        if not p.on_pitch or (p.role == "GK" and situation != "defend"):
            continue
        h, s, ph = p.history or {}, p.stats, p.physical or {}
        why: list[str] = []
        if situation == "penalty":
            score = 3 * (h.get("pen_goals", 0) + s["pen_goals"]) + h.get("pens", 0) + s["pens"] + 0.5 * (h.get("goals", 0) + s["goals"]) \
                + (0.3 if p.role == "FWD" else 0)
            if h.get("pens") or s["pens"]:
                why.append(f"Penalties (incl. shoot-outs): {h.get('pen_goals', 0)}/{h.get('pens', 0)} scored earlier in the tournament, "
                           f"{s['pen_goals']}/{s['pens']} today")
            if h.get("goals") or s["goals"]:
                why.append(f"Goals: {h.get('goals', 0)} before today, {s['goals']} today")
        elif situation == "corner":
            score = h.get("corners", 0) + 2 * s["corners"] + 0.01 * (s["pass_pct"] or 0)
            if h.get("corners") or s["corners"]:
                why.append(f"Corners taken: {h.get('corners', 0)} earlier in the tournament, {s['corners']} today")
            if s["pass_pct"] is not None:
                why.append(f"Pass completion today {s['pass_pct']:.0f}%")
        elif situation == "free_kick":
            score = 3 * h.get("fk_goals", 0) + h.get("fk_shots", 0) + 0.2 * h.get("fk_passes", 0) + 0.3 * s["shots"]
            if h.get("fk_shots") or h.get("fk_passes"):
                why.append(f"Free kicks earlier in the tournament: {h.get('fk_shots', 0)} shots ({h.get('fk_goals', 0)} goals), "
                           f"{h.get('fk_passes', 0)} deliveries")
            else:
                why.append(f"No free kicks earlier in the tournament; ranked on shooting today ({s['shots']} shots)")
        elif situation == "counter":
            score = 0.08 * (ph.get("top_speed_kmh") or 0) + 0.4 * s["progressive_carries"] + 0.5 * s["dribbles_won"] + 10 * s.get("xt_added", 0)
            if ph.get("top_speed_kmh"):
                why.append(f"Top speed today {ph['top_speed_kmh']:.1f} km/h")
            if s["progressive_carries"] or s["dribbles_won"]:
                why.append(f"{s['progressive_carries']} progressive carries, {s['dribbles_won']} dribbles won today")
            if "fatigue" in p.flags:
                score *= 0.6
                why.append("but fading physically")
        else:  # defend
            score = 0.3 * s["def_actions"] + 0.4 * s["duels_won"] + (0.6 if p.role == "DEF" else 0.3 if p.role == "MID" else 0) - 0.3 * s["losses"]
            why.append(f"Today: {s['def_actions']} defensive actions, {s['duels_won']} duels won, {s['losses']} ball losses")
            if "fatigue" in p.flags:
                score -= 0.5
                why.append("but fading physically")
        if p.booked and situation == "defend":
            score -= 0.4
            why.append("Booked: must be careful in duels")
        ranked.append({"player_id": p.player_id, "name": p.name, "jersey": p.jersey, "role": p.role, "score": round(score, 2), "why": why})
    ranked.sort(key=lambda r: -r["score"])
    return {"team_id": team_id, "situation": situation, "ranked": ranked[:top], "method": METHOD,
            "basis": "this match so far + the player's earlier matches in this competition"}
