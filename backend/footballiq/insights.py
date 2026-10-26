"""Analyst-style match insights from events, model outputs, tracking and player form.

Each check at time t reads only data up to t, so the full list is computed once and cut at the replay clock.
"""

from __future__ import annotations

import hashlib
import logging
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from footballiq.replay.timeline import MatchTimeline
from footballiq.schema import MatchEvent

log = logging.getLogger(__name__)
STEP_MS = 30_000
MIN = 60_000
HIGH, MEDIUM, LOW = 1, 2, 3
PITCH_X = 105.0


@dataclass
class Insight:
    id: str
    t_ms: int
    clock_label: str
    minute: str
    category: str               # event | momentum | pressing | model | tactical | physical | player | discipline | set_piece
    kind: str
    priority: int               # 1 high, 2 medium, 3 low
    team_id: str | None
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    player: str | None = None
    seek_ms: int = 0
    source: str = "events"
    subject: dict[str, Any] | None = None    # player / substitution / best-player payload for the UI

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _minute(clock_label: str) -> str:
    base, _, extra = clock_label.partition("+")
    if extra:
        m, _, s = extra.partition(":")
        return f"{base}+{int(m) + (1 if int(s or 0) or int(m) == 0 else 0)}'"
    m, _, s = clock_label.partition(":")
    return f"{int(m) + 1}'" if int(s or 0) or int(m) == 0 else f"{int(m)}'"


class _Builder:
    def __init__(self, tl: MatchTimeline):
        self.tl = tl
        self.mid = tl.match.canonical_match_id
        self.out: list[Insight] = []
        self.last: dict[tuple, int] = {}
        self.names = {tl.match.home.team_id: tl.match.home.name, tl.match.away.team_id: tl.match.away.name}

    def cooled(self, key: tuple, t: int, cooldown_ms: int) -> bool:
        prev = self.last.get(key)
        return prev is None or t - prev >= cooldown_ms

    def add(self, t: int, category: str, kind: str, priority: int, team: str | None, title: str, detail: str,
            evidence: list[str] | None = None, player: str | None = None, source: str = "events", key: tuple | None = None,
            seek_back_ms: int = 8_000, subject: dict[str, Any] | None = None) -> None:
        clock = self.tl.clock_label_at(t)
        iid = hashlib.sha1(f"{self.mid}|{kind}|{team}|{player}|{t}".encode()).hexdigest()[:12]
        self.out.append(Insight(iid, int(t), clock, _minute(clock), category, kind, priority, team, title, detail,
                                evidence or [], player, max(0, int(t) - seek_back_ms), source, subject))
        self.last[key or (kind, team, player)] = t


# ------------------------------------------------------------------------------------------- events
def _event_insights(b: _Builder) -> None:
    tl, names = b.tl, b.names
    booked: dict[str, int] = {}
    subs: dict[str, list[MatchEvent]] = {}

    def flush_subs(team: str) -> None:
        batch = subs.pop(team, [])
        if not batch:
            return
        on = ", ".join(e.recipient_name or "?" for e in batch)
        off = ", ".join(e.player_name or "?" for e in batch)
        n = len(batch)
        b.add(batch[-1].match_elapsed_ms, "event", "substitution", MEDIUM if n >= 2 else LOW, team,
              f"{names[team]} {'make ' + str(n) + ' changes' if n > 1 else 'make a change'}",
              f"On: {on}. Off: {off}.", [f"Substitution events {', '.join(_minute(e.clock_label) for e in batch)}"])

    for e in tl.events:
        if e.is_shootout:
            continue
        t, team = e.match_elapsed_ms, e.team_id
        for tm in list(subs):
            if t - subs[tm][-1].match_elapsed_ms > 3 * MIN:
                flush_subs(tm)
        if e.is_goal or e.is_own_goal:
            st = tl.state_at(t)
            score = " - ".join(f"{names[k]} {v}" for k, v in st["score"].items())
            scorer_team = team if e.is_goal else next(k for k in names if k != team)
            xg = f", shot xG {e.provider_xg:.2f}" if e.provider_xg is not None else ""
            b.add(t, "event", "goal", HIGH, scorer_team, f"Goal for {names[scorer_team]}",
                  f"{e.player_name or 'Own goal'}{' (own goal)' if e.is_own_goal else ''}{xg}. Score: {score}.",
                  [f"Event {e.event_id}"], player=e.player_name, seek_back_ms=12_000)
        elif e.card and ("Red" in e.card or "Second" in e.card):
            b.add(t, "discipline", "red_card", HIGH, team, f"{names.get(team, '')} down to ten men",
                  f"{e.player_name}: {e.card}.", [f"Event {e.event_id}"], player=e.player_name)
        elif e.card and e.player_id:
            booked[e.player_id] = t
        elif e.type == "Foul Committed" and e.player_id in booked and t - booked[e.player_id] > 30_000 and \
                b.cooled(("second_yellow_risk", team, e.player_id), t, 15 * MIN):
            b.add(t, "discipline", "second_yellow_risk", MEDIUM, team, f"{e.player_name} is walking a tightrope",
                  f"Booked at {_minute(tl.clock_label_at(booked[e.player_id]))} and fouled again at {_minute(e.clock_label)}. "
                  "Second-yellow risk.", [f"Foul event {e.event_id}"], player=e.player_name, key=("second_yellow_risk", team, e.player_id))
        elif e.type == "Substitution" and team:
            subs.setdefault(team, []).append(e)
        elif e.type == "Tactical Shift" and e.formation and b.cooled(("shape_sheet", team, None), t, 5 * MIN):
            b.add(t, "tactical", "team_sheet_shape", MEDIUM, team, f"{names.get(team, '')} change shape to {e.formation}",
                  "New formation on the team sheet (StatsBomb tactical shift).", [f"Event {e.event_id}"],
                  key=("shape_sheet", team, None))
        elif e.type == "Injury Stoppage" and b.cooled(("injury", team, None), t, 5 * MIN):
            b.add(t, "event", "injury", LOW, team, "Injury stoppage", f"{e.player_name or 'A player'} ({names.get(team, '')}) is down.",
                  [f"Event {e.event_id}"], player=e.player_name, key=("injury", team, None))
    for tm in list(subs):
        flush_subs(tm)


# ------------------------------------------------------------------------------- momentum / pressing
def _attacking(team: str, home: str, x: float | None, zone: str) -> bool:
    if x is None:
        return False
    fwd = x if team == home else PITCH_X - x
    return fwd >= 70 if zone == "final_third" else fwd > PITCH_X / 2


def _flow_insights(b: _Builder) -> None:
    tl, names = b.tl, b.names
    home, away = tl.match.home.team_id, tl.match.away.team_id
    times = [e.match_elapsed_ms for e in tl.events]

    def window(t: int, span: int) -> list[MatchEvent]:
        return tl.events[bisect_right(times, t - span):bisect_right(times, t)]

    for t in range(10 * MIN, tl.match.duration_ms + 1, STEP_MS):
        if tl.period_at(t) >= 5:
            break
        w10 = [e for e in window(t, 10 * MIN) if not e.is_shootout]
        for team, opp in ((home, away), (away, home)):
            mine = [e for e in w10 if e.team_id == team]
            theirs = [e for e in w10 if e.team_id == opp]
            # penalties excluded: they already get a goal card
            shots = [e for e in mine if e.type == "Shot" and e.subtype != "Penalty"]
            opp_shots = [e for e in theirs if e.type == "Shot" and e.subtype != "Penalty"]
            scored_recently = any((e.is_goal or e.is_own_goal) and e.match_elapsed_ms > t - 2 * MIN for e in w10)
            xg, opp_xg = sum(e.provider_xg or 0 for e in shots), sum(e.provider_xg or 0 for e in opp_shots)
            if not scored_recently and ((xg >= 0.5 and xg >= 2.5 * max(opp_xg, 0.05)) or (len(shots) >= 4 and len(opp_shots) <= 1)) and \
                    b.cooled(("pressure", team, None), t, 12 * MIN):
                b.add(t, "momentum", "pressure", MEDIUM, team, f"{names[team]} are turning the screw",
                      f"Last 10': {len(shots)} shots, xG {xg:.2f} vs {len(opp_shots)} shots, xG {opp_xg:.2f}.",
                      ["StatsBomb shots and provider xG, rolling 10'"], key=("pressure", team, None))
            entries = sum(1 for e in mine if e.type in ("Pass", "Carry") and e.outcome in (None, "Complete")
                          and _attacking(team, home, e.end_x_m, "final_third") and not _attacking(team, home, e.x_m, "final_third"))
            opp_entries = sum(1 for e in theirs if e.type in ("Pass", "Carry") and e.outcome in (None, "Complete")
                              and _attacking(opp, home, e.end_x_m, "final_third") and not _attacking(opp, home, e.x_m, "final_third"))
            if entries >= 12 and entries >= 2 * max(opp_entries, 1) and b.cooled(("territory", team, None), t, 12 * MIN):
                b.add(t, "momentum", "territory", LOW, team, f"{names[team]} camp in the final third",
                      f"Last 10': {entries} entries into the final third vs {opp_entries}.",
                      ["Completed passes and carries ending in the final third, rolling 10'"], key=("territory", team, None))
            # pressing vs the team's own earlier baseline
            press = sum(1 for e in mine if e.type == "Pressure" and _attacking(team, home, e.x_m, "half"))
            before = [e for e in tl.events[:bisect_right(times, t - 10 * MIN)]
                      if e.team_id == team and e.type == "Pressure" and _attacking(team, home, e.x_m, "half")]
            base = len(before) / max((t - 10 * MIN) / (10 * MIN), 1)
            recov = sum(1 for e in mine if e.type == "Ball Recovery" and _attacking(team, home, e.x_m, "half"))
            if t >= 25 * MIN and press >= 15 and press >= 1.6 * max(base, 1) and b.cooled(("press", team, None), t, 15 * MIN):
                b.add(t, "pressing", "press_up", MEDIUM, team, f"{names[team]} press higher",
                      f"Last 10': {press} pressures in the opponent half (their usual: {base:.0f} per 10'), {recov} high ball recoveries.",
                      ["StatsBomb pressure and ball-recovery events by location"], key=("press", team, None))
            lost = sum(1 for e in mine if e.type in ("Dispossessed", "Miscontrol"))
            if lost >= 6 and b.cooled(("turnovers", team, None), t, 15 * MIN):
                b.add(t, "momentum", "turnovers", LOW, team, f"{names[team]} keep giving it away",
                      f"Last 10': {lost} times dispossessed or miscontrolled.", ["Dispossessed / Miscontrol events"],
                      key=("turnovers", team, None))
            fouls = sum(1 for e in mine if e.type == "Foul Committed")
            if fouls >= 5 and b.cooled(("fouls", team, None), t, 15 * MIN):
                b.add(t, "discipline", "foul_rate", LOW, team, f"{names[team]} are fouling a lot",
                      f"Last 10': {fouls} fouls. Cards and dangerous free kicks become likely.", ["Foul Committed events"],
                      key=("fouls", team, None))
            corners = sum(1 for e in mine if e.subtype == "Corner")
            if corners >= 3 and b.cooled(("corners", team, None), t, 12 * MIN):
                b.add(t, "set_piece", "corner_spell", MEDIUM, team, f"Corner pressure from {names[team]}",
                      f"Last 10': {corners} corners.", ["Corner pass events"], key=("corners", team, None))
            recent = [e for e in tl.events[:bisect_right(times, t)] if e.team_id == team and e.type == "Shot" and not e.is_shootout][-4:]
            if len(recent) == 4 and t - recent[0].match_elapsed_ms <= 20 * MIN and recent[-1].match_elapsed_ms > t - STEP_MS and \
                    all((e.provider_xg or 0) < 0.06 for e in recent) and b.cooled(("shot_quality", team, None), t, 15 * MIN):
                b.add(t, "momentum", "low_quality_shots", LOW, team, f"{names[team]} are forcing it from distance",
                      f"Last 4 shots all under 0.06 xG ({', '.join(f'{e.provider_xg or 0:.2f}' for e in recent)}).",
                      ["Shot events, StatsBomb xG"], key=("shot_quality", team, None))
        if t >= 15 * MIN:
            now, then = tl.stats_at(t), tl.stats_at(t - 5 * MIN)
            got = {k: now[k]["possession_ms"] - then[k]["possession_ms"] for k in (home, away)}
            total = sum(got.values())
            for team in (home, away):
                share = 100 * got[team] / total if total > 0 else 0
                usual = then[team].get("possession_pct") or 50.0      # the team's own share up to 5' ago
                if total >= 2 * MIN and share >= 72 and share - usual >= 15 and b.cooled(("squeeze", team, None), t, 15 * MIN):
                    b.add(t, "momentum", "possession_squeeze", LOW, team, f"{names[team]} have the ball pinned",
                          f"{share:.0f}% of the ball in the last 5' (their match average so far {usual:.0f}%).",
                          ["Possession from StatsBomb possession chains"], key=("squeeze", team, None))


# ------------------------------------------------------------------------------------------- model
def _model_insights(b: _Builder, latest: Callable[[str, int], dict[str, Any]]) -> None:
    tl, names = b.tl, b.names
    teams = (tl.match.home.team_id, tl.match.away.team_id)
    goal_times = [e.match_elapsed_ms for e in tl.events if (e.is_goal or e.is_own_goal) and not e.is_shootout]
    hist: dict[int, dict[str, Any]] = {}
    g10: dict[str, list[float]] = {t: [] for t in teams}
    for t in range(0, tl.match.duration_ms + 1, STEP_MS):
        if tl.period_at(t) >= 5:
            break
        p = latest(b.mid, t)
        if p.get("feature_cutoff_ms") is None:
            continue
        hist[t] = p
        for team in teams:
            f = (p["teams"].get(team) or {}).get("goal_next_10m")
            if not f or f["probability"] is None:
                continue
            prob, mean = f["probability"], (sum(g10[team]) / len(g10[team]) if g10[team] else None)
            prev = g10[team][-1] if g10[team] else None
            g10[team].append(prob)
            bar = max(0.15, 1.4 * mean) if mean is not None else None
            if bar is not None and prev is not None and len(g10[team]) > 10 and prob >= bar and prev < bar and \
                    b.cooled(("danger", team, None), t, 10 * MIN):
                drivers = ", ".join(d["feature"].replace("_", " ") for d in f["drivers"][:2] if d["contribution"] > 0)
                b.add(t, "model", "danger_window", MEDIUM, team, f"Danger window for {names[team]}",
                      f"Goal in the next 10' now {100 * prob:.0f}% (their match average {100 * mean:.0f}%)"
                      + (f", driven by {drivers}." if drivers else "."),
                      [f"Goal model {p['model_version']}"], source="model", key=("danger", team, None))
        old = hist.get(t - 5 * MIN)
        if old is None or tl.period_at(t - 5 * MIN) != tl.period_at(t) or any(t - 5 * MIN < g <= t for g in goal_times) \
                or tl.state_at(t - 5 * MIN)["score"] != tl.state_at(t)["score"] or (p.get("phase_remaining_s") or 0) < 300:
            continue   # goals and phase endings move win probability on their own
        for team in teams:
            a = ((old["teams"].get(team) or {}).get("win_phase") or {}).get("probability")
            c = ((p["teams"].get(team) or {}).get("win_phase") or {}).get("probability")
            if a is None or c is None or abs(c - a) < 0.12 or not b.cooled(("swing", team, None), t, 10 * MIN):
                continue
            b.add(t, "model", "win_swing", MEDIUM, team,
                  f"{names[team]}'s chances {'rising' if c > a else 'falling'} without a goal",
                  f"Win probability {100 * a:.0f}% to {100 * c:.0f}% in 5' with no goal: the play itself has shifted.",
                  [f"Outcome model {p['model_version']}"], source="model", key=("swing", team, None))


# ---------------------------------------------------------------------------------------- tracking
def _tactical_insights(b: _Builder, tactical: Any) -> None:
    tl, names = b.tl, b.names
    forms = tactical.formations(b.mid, tl.match.duration_ms)
    for s in forms.get("switches", []):
        t = int(s["at_ms"]) + MIN          # released once its confirming segment ends
        if t <= tl.match.duration_ms:
            # detected shapes flicker: LOW keeps them in the feed, not a popup
            b.add(t, "tactical", "shape_switch", LOW, s["team_id"], f"{names.get(s['team_id'], '')} now defend in a {s['to_formation']}",
                  f"Out-of-possession shape changed from {s['from_formation']} to {s['to_formation']} (tracking, smoothed).",
                  ["Formation detection from tracking (60 s segments)"], source="tracking", seek_back_ms=60_000)
    prev: dict[str, dict[str, Any]] = {}
    for w in sorted(tactical.timeline(b.mid, tl.match.duration_ms), key=lambda w: w["end_ms"]):
        p, team = prev.get(w["team_id"]), w["team_id"]
        prev[team] = w
        if p is None:
            continue
        notes = []
        for key, label, thr in (("width_in_possession_m", "width in possession", 5.0), ("depth_in_possession_m", "depth in possession", 5.0),
                                ("possession_pct", "possession", 12.0)):
            if w.get(key) is not None and p.get(key) is not None and abs(w[key] - p[key]) >= thr:
                unit = "%" if key == "possession_pct" else " m"
                notes.append(f"{label} {p[key]:.0f}{unit} to {w[key]:.0f}{unit}")
        if notes:
            b.add(int(w["end_ms"]), "tactical", "window_shift", LOW if len(notes) == 1 else MEDIUM, team,
                  f"{names.get(team, '')} look different in {w.get('label') or w['window_id']}", "; ".join(notes).capitalize() + ".",
                  ["Tactical windows from tracking"], source="tracking", seek_back_ms=60_000)


def _physical_insights(b: _Builder, tactical: Any) -> None:
    tl = b.tl
    best_speed = 0.0
    for t in range(15 * MIN, tl.match.duration_ms + 1, 5 * MIN):
        for r in tactical.physical(b.mid, t):
            if r["top_speed_kmh"] > best_speed + 0.2 and r["top_speed_kmh"] >= 33 and t >= 20 * MIN:
                best_speed = r["top_speed_kmh"]
                b.add(t, "physical", "top_speed", LOW, r["team_id"], f"Fastest sprint of the match: {r['name']}",
                      f"{r['top_speed_kmh']:.1f} km/h (sustained over 2 s).", ["Tracking speeds"], player=r["name"], source="tracking")


# ------------------------------------------------------------------------------------------ players
def _player_insights(b: _Builder, coach: Any) -> None:
    """Fading players and substitution suggestions, every 5' from 45'."""
    from footballiq.players import substitution_options

    tl, names = b.tl, b.names
    for t in range(45 * MIN, tl.match.duration_ms + 1, 5 * MIN):
        if tl.period_at(t) >= 5:
            break
        form = coach.form(b.mid, t, tl)
        for team, players in form.items():
            top2 = sorted((x.impact for x in players if x.on_pitch), reverse=True)[:2]
            for p in players:
                if not p.on_pitch or not ({"dip", "fatigue"} & set(p.flags)) or not b.cooled(("dip", team, p.player_id), t, 25 * MIN):
                    continue
                what = "is fading physically" if "fatigue" in p.flags else "has dropped off"
                star = bool(top2) and p.impact >= top2[-1] and "fatigue" not in p.flags
                detail = "; ".join(p.reasons[:2]) + "." + (" Still one of the team's two most influential players today." if star else "")
                b.add(t, "player", "performance_dip", LOW if star else MEDIUM, team, f"{p.name} {what}", detail,
                      ["Player impact index (events" + (", xT" if "xt_added" in p.stats else "") + ")"]
                      + (["Tracking: high-speed running"] if "fatigue" in p.flags else []),
                      player=p.name, source="tracking" if "fatigue" in p.flags else "events", key=("dip", team, p.player_id),
                      seek_back_ms=60_000, subject={"type": "player", "player_id": p.player_id, "name": p.name, "team_id": team,
                                                    "role": p.role, "flags": p.flags, "reasons": p.reasons, "stats": p.stats})
            if t < 55 * MIN or not b.cooled(("sub", team, None), t, 15 * MIN):
                continue
            so = substitution_options(tl, t, team, form)
            best = [o for o in so["options"] if o["on"] and (o["urgency"] == "high" or t >= 60 * MIN)]
            if not so["remaining"] or not best:
                continue
            o = best[0]
            b.add(t, "player", "sub_suggestion", HIGH if o["urgency"] == "high" else MEDIUM, team,
                  f"Change to consider for {names[team]}: {o['off']['name']} off, {o['on']['name']} on",
                  f"{o['why_off'][0]}. {o['why_on'][0]}. {so['remaining']} substitution{'s' if so['remaining'] != 1 else ''} left, "
                  f"team {so['context']}.",
                  ["Player impact, tracking load, cards and tournament form"], player=o["off"]["name"], key=("sub", team, None),
                  seek_back_ms=30_000, subject={"type": "substitution", "team_id": team, "context": so["context"],
                                                "remaining": so["remaining"], "options": so["options"][:3]})


def _set_piece_insights(b: _Builder, coach: Any) -> None:
    """Best taker for each foul won in the box or in shooting range."""
    from footballiq.players import best_for

    tl, names, home = b.tl, b.names, b.tl.match.home.team_id
    for e in tl.events:
        if e.type != "Foul Won" or e.is_shootout or e.x_m is None or e.y_m is None or not e.team_id:
            continue
        fwd = e.x_m if e.team_id == home else PITCH_X - e.x_m
        lat = abs(e.y_m - 34.0)
        in_box = fwd >= 88.5 and lat <= 20.16
        if not in_box and not (fwd >= 75 and lat <= 22):
            continue
        situation = "penalty" if in_box else "free_kick"
        if not b.cooled((situation, e.team_id, None), e.match_elapsed_ms, 3 * MIN):
            continue
        t = e.match_elapsed_ms
        ranked = best_for(tl, t, e.team_id, situation, coach.form(b.mid, t, tl))["ranked"]
        if not ranked:
            continue
        top = ranked[0]
        b.add(t, "set_piece", f"best_{situation}", HIGH if in_box else MEDIUM, e.team_id,
              (f"Foul in the box: likely penalty for {names[e.team_id]}" if in_box else
               f"Free kick in shooting range for {names[e.team_id]} ({PITCH_X - fwd:.0f} m out)"),
              f"Best {'taker' if in_box else 'option'} on the pitch: {top['name']}" + (f" - {top['why'][0]}" if top["why"] else "") + ".",
              [f"Foul Won event {e.event_id}"], player=top["name"], key=(situation, e.team_id, None),
              subject={"type": "best_player", "team_id": e.team_id, "situation": situation, "ranked": ranked})


def detect(tl: MatchTimeline, predictions: Callable[[str, int], dict[str, Any]] | None = None,
           tactical: Any = None, coach: Any = None) -> tuple[list[Insight], list[str]]:
    """All match insights in time order, plus the sources used; callers filter by the replay clock."""
    b = _Builder(tl)
    _event_insights(b)
    _flow_insights(b)
    sources = ["events"]
    if predictions is not None:
        try:
            _model_insights(b, predictions)
            sources.append("model")
        except Exception as exc:  # noqa: BLE001 - no model outputs for this match
            log.info("model insights skipped for %s: %s", b.mid, exc)
    if tactical is not None and tl.tracking is not None:
        for fn in (_tactical_insights, _physical_insights):
            try:
                fn(b, tactical)
                sources.append("tracking")
            except Exception as exc:  # noqa: BLE001 - tactical tables not built for this match
                log.info("%s skipped for %s: %s", fn.__name__, b.mid, exc)
    if coach is not None:
        for fn in (_player_insights, _set_piece_insights):
            try:
                fn(b, coach)
                sources.append("players")
            except Exception as exc:  # noqa: BLE001 - player analytics are additive
                log.warning("%s failed for %s: %s", fn.__name__, b.mid, exc)
    out = sorted(b.out, key=lambda i: (i.t_ms, i.priority))
    for i in out:
        i.evidence = i.evidence[:3]
    return out, sorted(set(sources))
