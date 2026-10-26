"""IDSSE (DFL) 2022/23 open data -> canonical match, events and common-schema tracking, parsed with kloppy.

Optical tracking at 25 Hz; kloppy's STATIC_HOME_AWAY orientation (home attacks left to right) is the canonical frame.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from footballiq import spatial as SP
from footballiq.ingest.statsbomb import clock_label, slugify
from footballiq.schema import PERIOD_LABELS, Match, MatchEvent, Period, Player, Team

PROVIDER = "dfl_idsse"
ATTRIBUTION = "Data: IDSSE / DFL open data (Bassek et al., 2025), CC BY 4.0"
L, W = 105.0, 68.0
MATCHES = {  # DFL match id -> competition file prefix
    "J03WMX": "DFL-COM-000001", "J03WN1": "DFL-COM-000001", "J03WOH": "DFL-COM-000002", "J03WOY": "DFL-COM-000002",
    "J03WPY": "DFL-COM-000002", "J03WQQ": "DFL-COM-000002", "J03WR9": "DFL-COM-000002",
}
COMPETITION = {"DFL-COM-000001": "Bundesliga", "DFL-COM-000002": "2. Bundesliga"}
BASE_URL = "https://huggingface.co/datasets/pysport/idsse-data/resolve/main"


def file_names(match_id: str) -> dict[str, str]:
    c = MATCHES[match_id]
    return {"meta": f"DFL_02_01_matchinformation_{c}_DFL-MAT-{match_id}.xml",
            "events": f"DFL_03_02_events_raw_{c}_DFL-MAT-{match_id}.xml",
            "tracking": f"DFL_04_03_positions_raw_observed_{c}_DFL-MAT-{match_id}.xml"}


def _ms(td) -> int:
    return int(round(td.total_seconds() * 1000))


def _name(enum_value) -> str | None:
    return getattr(enum_value, "name", None)


PASS_OUTCOME = {"COMPLETE": "Complete", "INCOMPLETE": "Incomplete", "OUT": "Out", "OFFSIDE": "Pass Offside"}
SHOT_OUTCOME = {"GOAL": "Goal", "SAVED": "Saved", "OFF_TARGET": "Off T", "BLOCKED": "Blocked", "POST": "Post", "OWN_GOAL": "Own Goal"}
SET_PIECE = {"CORNER_KICK": "Corner", "FREE_KICK": "Free Kick", "THROW_IN": "Throw-in", "GOAL_KICK": "Goal Kick",
             "KICK_OFF": "Kick Off", "PENALTY": "Penalty"}
CARD = {"FIRST_YELLOW": "Yellow Card", "SECOND_YELLOW": "Second Yellow", "RED": "Red Card"}
TYPE = {"PASS": "Pass", "SHOT": "Shot", "FOUL_COMMITTED": "Foul Committed", "RECOVERY": "Ball Recovery",
        "SUBSTITUTION": "Substitution", "CARD": "Bad Behaviour", "BALL_OUT": "Ball Out", "INTERCEPTION": "Interception",
        "CLEARANCE": "Clearance", "TAKE_ON": "Dribble", "DUEL": "Duel"}


def normalize(event_ds, match_id: str) -> tuple[Match, list[MatchEvent]]:
    """kloppy event dataset (any orientation) -> canonical Match + events."""
    from kloppy.domain import SetPieceQualifier

    ev = event_ds.transform(to_orientation="STATIC_HOME_AWAY")
    md = ev.metadata
    home_t, away_t = md.teams
    home = Team(team_id=slugify(home_t.name), name=home_t.name, source_ids={"dfl": home_t.team_id})
    away = Team(team_id=slugify(away_t.name), name=away_t.name, source_ids={"dfl": away_t.team_id})
    tid = {home_t.team_id: home.team_id, away_t.team_id: away.team_id}

    periods, start, pstart = [], 0, {}
    for p in md.periods:
        dur = _ms(p.end_timestamp - p.start_timestamp)
        periods.append(Period(period=p.id, label=PERIOD_LABELS.get(p.id, f"Period {p.id}"), start_match_ms=start, duration_ms=dur))
        pstart[p.id] = start
        start += dur

    players, pid = [], {}
    for t, team in ((home_t, home), (away_t, away)):
        for p in t.players:
            pid[p.player_id] = f"{team.team_id}_{slugify(p.name)}"
            players.append(Player(player_id=pid[p.player_id], team_id=team.team_id, name=p.name, jersey_number=p.jersey_no,
                                  starter=bool(p.starting), source_ids={"dfl": p.player_id}))

    events: list[MatchEvent] = []
    for i, e in enumerate(ev.records):
        kind = _name(e.event_type)
        if kind not in TYPE or e.timestamp.total_seconds() < 0 or e.period is None:
            continue  # unknown types and invalid clocks are not replayed
        ms = _ms(e.timestamp)
        team_id = tid.get(e.team.team_id) if e.team else None
        res = _name(getattr(e, "result", None))
        sp = _name(e.get_qualifier_value(SetPieceQualifier)) if hasattr(e, "get_qualifier_value") else None
        loc = e.coordinates
        end = getattr(e, "receiver_coordinates", None) if kind == "PASS" else None
        subtype = SET_PIECE.get(sp) if sp else None
        outcome = PASS_OUTCOME.get(res) if kind == "PASS" else SHOT_OUTCOME.get(res) if kind == "SHOT" else None
        card = CARD.get(_name(getattr(e, "card_type", None))) if kind == "CARD" else None
        repl = getattr(e, "replacement_player", None) if kind == "SUBSTITUTION" else None
        recv = getattr(e, "receiver_player", None) if kind == "PASS" else None
        events.append(MatchEvent(
            event_id=f"dfl-{match_id}-{e.event_id or i}", match_id="", provider=PROVIDER, source_sequence=i,
            period=e.period.id, period_elapsed_ms=ms, match_elapsed_ms=pstart[e.period.id] + ms,
            clock_label=clock_label(e.period.id, ms), team_id=team_id, team_name=e.team.name if e.team else None,
            player_id=pid.get(e.player.player_id) if e.player else None, player_name=e.player.name if e.player else None,
            type=TYPE[kind], subtype=subtype, outcome=outcome,
            x_m=round(loc.x * L, 2) if loc is not None and loc.x is not None else None,
            y_m=round(loc.y * W, 2) if loc is not None and loc.y is not None else None,
            end_x_m=round(end.x * L, 2) if end is not None and end.x is not None else None,
            end_y_m=round(end.y * W, 2) if end is not None and end.y is not None else None,
            is_goal=kind == "SHOT" and res == "GOAL", is_own_goal=kind == "SHOT" and res == "OWN_GOAL",
            card=card, recipient_id=pid.get((repl or recv).player_id) if (repl or recv) else None,
            recipient_name=(repl or recv).name if (repl or recv) else None,
        ))
    date = md.date.date().isoformat() if md.date else "unknown"
    canonical = f"{date}_{home.team_id}_{away.team_id}"
    for e in events:
        e.match_id = canonical
    events.sort(key=lambda e: (e.match_elapsed_ms, e.source_sequence))
    score = getattr(md, "score", None)
    comp = COMPETITION.get(MATCHES.get(match_id, ""), "Bundesliga")
    match = Match(
        canonical_match_id=canonical, competition=comp, season="2022/2023", stage=None,
        kickoff_utc=md.date.isoformat() if md.date else None, kickoff_source=md.date.isoformat() if md.date else "unknown",
        home=home, away=away, periods=periods, duration_ms=start, source_ids={"dfl": match_id}, players=players,
        result={"home_score": getattr(score, "home", None), "away_score": getattr(score, "away", None), "shootout": None},
        attribution=ATTRIBUTION,
    )
    return match, events


def tracking_columns(tracking_ds, match: Match, every: int = 1) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """kloppy tracking -> (frame, position) columns in the common spatial schema; keeps every ``every``-th frame."""
    tr = tracking_ds.transform(to_orientation="STATIC_HOME_AWAY")
    side = {t.team_id: ("home" if i == 0 else "away") for i, t in enumerate(tr.metadata.teams)}
    team = {t.team_id: (match.home.team_id if i == 0 else match.away.team_id) for i, t in enumerate(tr.metadata.teams)}
    pid = {p.source_ids.get("dfl"): p.player_id for p in match.players}
    pstart = {p.period: p.start_match_ms for p in match.periods}
    method, _ = SP.PROVIDERS[PROVIDER]
    fr: dict[str, list[Any]] = {c: [] for c in SP.FRAME_COLUMNS}
    po: dict[str, list[Any]] = {c: [] for c in SP.POSITION_COLUMNS}
    for k, f in enumerate(tr.records):
        if k % every or f.period is None:
            continue
        t = pstart.get(f.period.id, 0) + _ms(f.timestamp)
        b = f.ball_coordinates
        flags = []
        for p, d in f.players_data.items():
            c = d.coordinates
            x, y = (c.x * L, c.y * W) if c is not None and c.x is not None and c.y is not None else (None, None)
            fl = SP.optical_flags(x, y)
            flags.append(fl.is_observed)
            for col, val in (("source_provider", PROVIDER), ("tracking_method", method), ("match_id", match.canonical_match_id),
                             ("period", f.period.id), ("frame_num", int(f.frame_id)), ("match_elapsed_ms", t),
                             ("team_id", team.get(p.team.team_id)), ("side", side.get(p.team.team_id)),
                             ("jersey_num", str(p.jersey_no)), ("player_id", pid.get(p.player_id)),
                             ("x_m", None if x is None else round(x, 3)), ("y_m", None if y is None else round(y, 3)),
                             ("speed_mps", d.speed), ("is_observed", fl.is_observed), ("is_extrapolated", fl.is_extrapolated),
                             ("confidence", None)):
                po[col].append(val)
        bfl = SP.optical_flags(b.x if b is not None else None, b.y if b is not None else None)
        for col, val in (("source_provider", PROVIDER), ("tracking_method", method), ("match_id", match.canonical_match_id),
                         ("period", f.period.id), ("frame_num", int(f.frame_id)), ("match_elapsed_ms", t),
                         ("ball_x_m", None if b is None or b.x is None else round(b.x * L, 3)),
                         ("ball_y_m", None if b is None or b.y is None else round(b.y * W, 3)),
                         ("ball_z_m", None if b is None else getattr(b, "z", None)), ("ball_is_observed", bfl.is_observed),
                         ("ball_is_extrapolated", bfl.is_extrapolated), ("ball_alive", _name(f.ball_state) == "ALIVE"),
                         ("players_on_pitch", len(flags)), ("players_observed", sum(1 for v in flags if v)),
                         ("coverage_score", SP.coverage(flags))):
            fr[col].append(val)
    return ({c: np.asarray(v, dtype=object) for c, v in fr.items()}, {c: np.asarray(v, dtype=object) for c, v in po.items()})
