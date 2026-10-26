"""SkillCorner A-League 2024/25 open data -> canonical match, events and common-schema tracking.

Events come from "player_possession" dynamic events and the match sheet; cards have no timestamp and are skipped.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

import numpy as np

from footballiq import spatial as SP
from footballiq.ingest.statsbomb import clock_label, slugify
from footballiq.schema import PERIOD_LABELS, Match, MatchEvent, Period, Player, Team

PROVIDER = "skillcorner"
ATTRIBUTION = "Data: SkillCorner open data (github.com/SkillCorner/opendata)"
RAW = "https://raw.githubusercontent.com/SkillCorner/opendata/master/data"
LFS = "https://media.githubusercontent.com/media/SkillCorner/opendata/master/data"
FRAME_MS = 100

PASS_OUTCOME = {"successful": "Complete", "unsuccessful": "Incomplete", "offside": "Pass Offside"}
END_TYPE = {"pass": "Pass", "shot": "Shot", "clearance": "Clearance", "possession_loss": "Dispossessed", "foul_suffered": "Foul Won"}


def urls(match_id: int) -> dict[str, str]:
    base = f"matches/{match_id}/{match_id}"
    return {"match": f"{RAW}/{base}_match.json", "events": f"{RAW}/{base}_dynamic_events.csv",
            "tracking": f"{LFS}/{base}_tracking_extrapolated.jsonl"}


def _period_table(meta: dict) -> tuple[list[Period], dict[int, tuple[int, int]]]:
    periods, start, frames = [], 0, {}
    for p in sorted(meta["match_periods"], key=lambda p: p["period"]):
        dur = (p["end_frame"] - p["start_frame"]) * FRAME_MS
        periods.append(Period(period=p["period"], label=PERIOD_LABELS.get(p["period"], f"Period {p['period']}"),
                              start_match_ms=start, duration_ms=dur))
        frames[p["period"]] = (p["start_frame"], start)
        start += dur
    return periods, frames


def frame_time(frames: dict[int, tuple[int, int]], period: int, frame: int) -> tuple[int, int]:
    """(period_elapsed_ms, match_elapsed_ms) of a 10 fps frame."""
    f0, t0 = frames[period]
    pe = max(0, (int(frame) - f0) * FRAME_MS)
    return pe, t0 + pe


def _team(meta: dict, key: str) -> Team:
    t = meta[key]
    return Team(team_id=slugify(t["name"]), name=t["name"], source_ids={"skillcorner": t["id"]})


def normalize(meta: dict, events_df) -> tuple[Match, list[MatchEvent]]:
    L, W = float(meta.get("pitch_length") or 105), float(meta.get("pitch_width") or 68)
    home, away = _team(meta, "home_team"), _team(meta, "away_team")
    tid = {meta["home_team"]["id"]: home.team_id, meta["away_team"]["id"]: away.team_id}
    periods, frames = _period_table(meta)

    players, pid = [], {}
    for p in meta["players"]:
        team = tid.get(p["team_id"])
        name = p.get("short_name") or f'{p.get("first_name", "")} {p.get("last_name", "")}'.strip()
        pid[p["id"]] = f"{team}_{slugify(name)}"
        players.append(Player(player_id=pid[p["id"]], team_id=team, name=name, jersey_number=p.get("number"),
                              starter=p.get("start_time") == "00:00:00", source_ids={"skillcorner": p["id"]}))

    def canon(team_id, x, y):
        if x is None or y is None or x != x or y != y:
            return None, None
        return (round(x + L / 2, 2), round(W / 2 - y, 2)) if team_id == home.team_id else (round(L / 2 - x, 2), round(W / 2 + y, 2))

    out: list[MatchEvent] = []
    pp = events_df[events_df["event_type"] == "player_possession"]
    for r in pp.itertuples(index=False):
        kind = END_TYPE.get(getattr(r, "end_type", None))
        if kind is None or r.period not in frames:
            continue
        team = tid.get(r.team_id)
        pe, me = frame_time(frames, int(r.period), int(r.frame_end))
        x, y = canon(team, r.x_end, r.y_end)   # possession end = pass / shot location
        goal = kind == "Shot" and bool(getattr(r, "lead_to_goal", False))
        out.append(MatchEvent(
            event_id=f"sc-{meta['id']}-{r.event_id}", match_id="", provider=PROVIDER, source_sequence=int(r.index),
            period=int(r.period), period_elapsed_ms=pe, match_elapsed_ms=me, clock_label=clock_label(int(r.period), pe),
            team_id=team, team_name=getattr(r, "team_shortname", None), player_id=pid.get(r.player_id),
            player_name=getattr(r, "player_name", None), type=kind,
            outcome=PASS_OUTCOME.get(getattr(r, "pass_outcome", None)) if kind == "Pass" else ("Goal" if goal else None),
            x_m=x, y_m=y, is_goal=goal,
        ))
    # subs: pair each player on with a teammate whose playing time ends at that frame
    subs_on = [p for p in meta["players"] if p.get("start_time") not in (None, "00:00:00") and (p.get("playing_time") or {}).get("total")]
    used: set[int] = set()
    for p in sorted(subs_on, key=lambda p: (p["playing_time"]["total"]["start_frame"], p["id"])):
        f_on = p["playing_time"]["total"]["start_frame"]
        cands = [q for q in meta["players"] if q["team_id"] == p["team_id"] and q is not p and q["id"] not in used
                 and (q.get("playing_time") or {}).get("total") and abs(q["playing_time"]["total"]["end_frame"] - f_on) <= 20]
        off = min(cands, key=lambda q: (abs(q["playing_time"]["total"]["end_frame"] - f_on), q["id"])) if cands else None
        if off:
            used.add(off["id"])
        period = next((k for k, (f0, _) in sorted(frames.items(), reverse=True) if f_on >= f0), 1)
        pe, me = frame_time(frames, period, f_on)
        on_name = next(pl.name for pl in players if pl.player_id == pid[p["id"]])
        off_name = next((pl.name for pl in players if off and pl.player_id == pid[off["id"]]), None)
        out.append(MatchEvent(
            event_id=f"sc-{meta['id']}-sub-{p['id']}", match_id="", provider=PROVIDER, source_sequence=10**6 + len(out),
            period=period, period_elapsed_ms=pe, match_elapsed_ms=me, clock_label=clock_label(period, pe),
            team_id=tid.get(p["team_id"]), team_name=home.name if tid.get(p["team_id"]) == home.team_id else away.name,
            player_id=pid.get(off["id"]) if off else None, player_name=off_name,
            type="Substitution", recipient_id=pid[p["id"]], recipient_name=on_name,
        ))
    date = (meta.get("date_time") or "unknown")[:10]
    canonical = f"{date}_{home.team_id}_{away.team_id}"
    for e in out:
        e.match_id = canonical
    out.sort(key=lambda e: (e.match_elapsed_ms, e.source_sequence))
    comp = (meta.get("competition_edition") or {}).get("name") or "A-League Men 2024/2025"
    match = Match(
        canonical_match_id=canonical, competition=comp, season="2024/2025",
        stage=(meta.get("competition_round") or {}).get("name"), kickoff_utc=meta.get("date_time"),
        kickoff_source=meta.get("date_time") or "unknown", stadium=(meta.get("stadium") or {}).get("name"),
        home=home, away=away, periods=periods, duration_ms=sum(p.duration_ms for p in periods),
        source_ids={"skillcorner": meta["id"]}, players=players,
        result={"home_score": meta.get("home_team_score"), "away_score": meta.get("away_team_score"), "shootout": None},
        attribution=ATTRIBUTION,
    )
    return match, out


def tracking_columns(lines: Iterable[str], meta: dict, match: Match) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """SkillCorner JSONL frames -> (frame columns, position columns) in the common spatial schema."""
    L, W = float(meta.get("pitch_length") or 105), float(meta.get("pitch_width") or 68)
    _, frames = _period_table(meta)
    home_ltr = {i + 1: side == "left_to_right" for i, side in enumerate(meta.get("home_team_side") or [])}
    team_of = {p["id"]: p["team_id"] for p in meta["players"]}
    home_id = meta["home_team"]["id"]
    tid = {home_id: match.home.team_id, meta["away_team"]["id"]: match.away.team_id}
    jersey = {p["id"]: str(p.get("number")) for p in meta["players"]}
    pid = {p.source_ids.get("skillcorner"): p.player_id for p in match.players}
    method, _ = SP.PROVIDERS[PROVIDER]
    fr: dict[str, list[Any]] = {c: [] for c in SP.FRAME_COLUMNS}
    po: dict[str, list[Any]] = {c: [] for c in SP.POSITION_COLUMNS}

    def xy(period, x, y):
        if x is None or y is None:
            return None, None
        return (x + L / 2, W / 2 - y) if home_ltr.get(period, True) else (L / 2 - x, W / 2 + y)

    for line in lines:
        r = json.loads(line)
        period = r.get("period")
        if period not in frames or not r.get("player_data"):
            continue
        _, t = frame_time(frames, period, r["frame"])
        flags = []
        for p in r["player_data"]:
            x, y = xy(period, p.get("x"), p.get("y"))
            fl = SP.skillcorner_flags(p.get("is_detected"))
            flags.append(fl.is_observed)
            team_sc = team_of.get(p["player_id"])
            for col, val in (("source_provider", PROVIDER), ("tracking_method", method), ("match_id", match.canonical_match_id),
                             ("period", period), ("frame_num", r["frame"]), ("match_elapsed_ms", t), ("team_id", tid.get(team_sc)),
                             ("side", "home" if team_sc == home_id else "away"), ("jersey_num", jersey.get(p["player_id"])),
                             ("player_id", pid.get(p["player_id"])), ("x_m", None if x is None else round(x, 3)),
                             ("y_m", None if y is None else round(y, 3)), ("speed_mps", None), ("is_observed", fl.is_observed),
                             ("is_extrapolated", fl.is_extrapolated), ("confidence", None)):
                po[col].append(val)
        b = r.get("ball_data") or {}
        bx, by = xy(period, b.get("x"), b.get("y"))
        bfl = SP.skillcorner_flags(b.get("is_detected")) if bx is not None else SP.Flags(None, None)
        for col, val in (("source_provider", PROVIDER), ("tracking_method", method), ("match_id", match.canonical_match_id),
                         ("period", period), ("frame_num", r["frame"]), ("match_elapsed_ms", t),
                         ("ball_x_m", None if bx is None else round(bx, 3)), ("ball_y_m", None if by is None else round(by, 3)),
                         ("ball_z_m", b.get("z")), ("ball_is_observed", bfl.is_observed), ("ball_is_extrapolated", bfl.is_extrapolated),
                         ("ball_alive", None), ("players_on_pitch", len(flags)), ("players_observed", sum(1 for v in flags if v)),
                         ("coverage_score", SP.coverage(flags))):
            fr[col].append(val)
    return ({c: np.asarray(v, dtype=object) for c, v in fr.items()}, {c: np.asarray(v, dtype=object) for c, v in po.items()})
