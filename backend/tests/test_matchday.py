"""Matchday: flow, tracking shape, moments, player focus and API cutoffs."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from footballiq.api.app import create_app
from footballiq.matchday.flow import FlowIndex, flow_series, scale
from footballiq.matchday.moments import detect
from footballiq.matchday.service import MatchdayData, meta, player_focus
from footballiq.matchday.shape import ShapeIndex, player_roles, tracking_to_match
from footballiq.replay.timeline import MatchTimeline
from footballiq.replay.tracking import TrackedPlayer, TrackingTimeline
from footballiq.schema import Match, MatchEvent, Period, Player, Team

H, A = "home-fc", "away-fc"
MIN = 60_000
# shirt, position code, x in the team's own frame (metres from own goal), y
LINEUP = [(1, "GK", 5, 34), (2, "RB", 30, 60), (4, "RCB", 30, 44), (5, "LCB", 30, 24), (3, "LB", 30, 8),
          (6, "DM", 45, 34), (8, "CM", 45, 50), (10, "CM", 45, 18), (7, "RW", 60, 58), (9, "CF", 60, 34), (11, "LW", 60, 10)]


def _players() -> list[Player]:
    out = []
    for team in (H, A):
        for shirt, _, _, _ in LINEUP:
            out.append(Player(player_id=f"{team}_p{shirt}", team_id=team, name=f"{team.split('-')[0].title()} Player {shirt}",
                              jersey_number=shirt, starter=True, source_ids={}))
        out.append(Player(player_id=f"{team}_p14", team_id=team, name=f"{team.split('-')[0].title()} Sub 14", jersey_number=14,
                          starter=False, source_ids={}))
    return out


def _match() -> Match:
    return Match(canonical_match_id="m-test", competition="Test Cup", season="2026", stage="Final", kickoff_source="2026-01-01",
                 home=Team(team_id=H, name="Home FC", source_ids={}), away=Team(team_id=A, name="Away FC", source_ids={}),
                 periods=[Period(period=1, label="1st half", start_match_ms=0, duration_ms=45 * MIN),
                          Period(period=2, label="2nd half", start_match_ms=45 * MIN, duration_ms=45 * MIN)],
                 duration_ms=90 * MIN, source_ids={}, players=_players(), result={"home": 1, "away": 0})


class _Ev:
    def __init__(self):
        self.events: list[MatchEvent] = []
        self.poss = 0

    def add(self, t, typ, team, player=None, **kw):
        n = len(self.events) + 1
        period = 1 if t < 45 * MIN else 2
        self.events.append(MatchEvent(
            event_id=f"e{n}", match_id="m-test", provider="test", source_sequence=n, period=period,
            period_elapsed_ms=t - (0 if period == 1 else 45 * MIN), match_elapsed_ms=t, clock_label="00:00", team_id=team,
            team_name="Home FC" if team == H else "Away FC", player_id=player, player_name=player, type=typ,
            possession=kw.pop("possession", self.poss), possession_team_id=kw.pop("poss_team", team), **kw))


def _events() -> list[MatchEvent]:
    ev = _Ev()
    ev.poss = 1
    ev.add(0, "Pass", H, f"{H}_p9", subtype="Kick Off", outcome="Complete", x_m=52.5, y_m=34, end_x_m=45, end_y_m=34,
           play_pattern="From Kick Off", recipient_id=f"{H}_p6")
    t = 2_000
    # 8 minutes of settled home possession: short forward passes
    for i in range(80):
        ev.add(t, "Pass", H, f"{H}_p{(6, 8, 10)[i % 3]}", outcome="Complete", x_m=40 + i % 20, y_m=34, end_x_m=48 + i % 20,
               end_y_m=30, play_pattern="From Kick Off", recipient_id=f"{H}_p{(8, 10, 6)[i % 3]}", duration_ms=1000)
        t += 6_000
    # open-play turnover -> away counter reaches the final third within 15 s (a fast transition)
    ev.poss = 2
    ev.add(t, "Interception", A, f"{A}_p6", x_m=55, y_m=34, play_pattern="Regular Play")
    ev.add(t + 2_000, "Pass", A, f"{A}_p6", outcome="Complete", x_m=50, y_m=34, end_x_m=20, end_y_m=34,
           play_pattern="Regular Play", recipient_id=f"{A}_p9")
    ev.add(t + 5_000, "Shot", A, f"{A}_p9", outcome="Off T", x_m=20, y_m=34, provider_xg=0.25, play_pattern="Regular Play")
    # dead ball: goal kick 40 s later
    ev.poss = 3
    ev.add(t + 45_000, "Pass", H, f"{H}_p1", subtype="Goal Kick", outcome="Complete", x_m=5, y_m=34, end_x_m=40, end_y_m=34,
           play_pattern="From Goal Kick", recipient_id=f"{H}_p6")
    # 20': home penalty goal, 30': yellow for away 4, 60': away substitution 9 -> 14
    ev.poss = 4
    ev.add(20 * MIN, "Shot", H, f"{H}_p9", subtype="Penalty", outcome="Goal", is_goal=True, x_m=94, y_m=34, provider_xg=0.78,
           play_pattern="From Penalty")
    ev.poss = 5
    ev.add(30 * MIN, "Foul Committed", A, f"{A}_p4", card="Yellow Card", x_m=60, y_m=30, play_pattern="From Penalty", poss_team=H)
    ev.add(60 * MIN, "Substitution", A, f"{A}_p9", recipient_id=f"{A}_p14", play_pattern="From Penalty", poss_team=H)
    return ev.events


def _tracking(minutes=12, hz=2, estimated=()) -> TrackingTimeline:
    """Both teams in the LINEUP shape (away mirrored); pff-style ids that differ from the event ids."""
    n = minutes * 60 * hz
    t = (np.arange(n) * 1000 / hz).astype(np.int64)
    players, xs, ys = [], [], []
    for side, team in enumerate((H, A)):
        for shirt, code, x, y in LINEUP:
            players.append(TrackedPlayer(len(players), team, ("home", "away")[side], str(shirt), f"{team}_pff-{shirt}", f"Pff {shirt}", code, True))
            xs.append(x if side == 0 else 105 - x)
            ys.append(y if side == 0 else 68 - y)
    k = len(players)
    frames = {"frame_num": np.arange(n), "t": t, "period": np.ones(n, np.int8), "ball_x": np.full(n, 52.5, np.float32),
              "ball_y": np.full(n, 34, np.float32), "ball_z": np.zeros(n, np.float32), "ball_observed": np.ones(n, bool)}
    observed = np.array([not (p.team_id == H and int(p.jersey_num) in estimated) for p in players])
    positions = {"frame_num": np.repeat(np.arange(n), k), "player_idx": np.tile(np.arange(k), n),
                 "x": np.tile(np.array(xs, np.float32), n), "y": np.tile(np.array(ys, np.float32), n),
                 "observed": np.tile(observed, n)}
    return TrackingTimeline.from_columns("m-test", "test", frames, positions, players)


def _timeline(**kw) -> MatchTimeline:
    return MatchTimeline(_match(), _events(), tracking=_tracking(**kw))


def test_flow_counts_turnovers_transitions_and_dead_time():
    tl = _timeline()
    idx = FlowIndex(tl)
    assert len(idx.turnover_t) == 1 and len(idx.transition_t) == 1
    assert 39_000 <= int(idx.dead[0, 1] - idx.dead[0, 0]) <= 45_000      # goal kick 40 s after the shot
    r = idx.raw(8 * MIN)                            # settled home spell: long sequences, home has the ball
    f = scale(r)
    assert f["poss_share"][0] > 0.95 and f["control"][0] > f["control"][1]
    assert f["pattern"] in {"balanced", "settled", "high_tempo", "end_to_end", "stop_start", "siege"}
    after = idx.raw(idx.turnover_t[0] + 20_000)
    assert after["transitions"] > 0 and after["bip"] <= 1.0


def test_flow_is_causal():
    """Each point from the full match equals the same point computed from the past only."""
    tl = _timeline()
    full = FlowIndex(tl)
    idx = FlowIndex(tl)
    for cut in (4 * MIN, idx.turnover_t[0] + 3_000, idx.turnover_t[0] + 20_000, 9 * MIN, 15 * MIN, 21 * MIN):
        past = FlowIndex(MatchTimeline(tl.match, [e for e in tl.events if e.match_elapsed_ms <= cut]))
        assert scale(full.raw(cut)) == scale(past.raw(cut)), cut


def test_shape_lines_from_tracking_joined_by_shirt():
    tl = _timeline()
    assert tracking_to_match(tl)[f"{H}_pff-9"] == f"{H}_p9"          # provider ids differ, shirts agree
    roles = player_roles(tl)
    assert roles[f"{H}_p4"]["role"] == "DEF" and roles[f"{A}_p9"]["role"] == "ATT" and roles[f"{H}_p1"]["role"] == "GK"
    home, away = ShapeIndex(tl).at(5 * MIN)
    for s in (home, away):                          # both teams in the same shape (away mirrored)
        assert s["def"] == 30 and s["mid"] == 45 and s["att"] == 60
        assert s["length"] == 30 and s["gap_dm"] == 15 and s["width"] == 52 and s["def_w"] == 52


def test_shape_ignores_estimated_positions():
    # three home outfielders never observed -> only 7 qualify -> no honest home shape
    home, away = ShapeIndex(_timeline(estimated=(2, 4, 7))).at(5 * MIN)
    assert home is None and away is not None


def test_moments_goal_card_sub_and_causality():
    tl = _timeline()
    d = MatchdayData(tl)
    by_kind = {m.kind: m for m in d.moments}
    goal = by_kind["goal"]
    assert goal.t_ms == 20 * MIN and goal.player_id == f"{H}_p9" and goal.f["pen"] and (goal.f["sa"], goal.f["sb"]) == (1, 0)
    assert goal.f["wcA"] > goal.f["wcB"]
    assert by_kind["card"].f["card"] == "yellow" and by_kind["card"].side == 1
    sub = by_kind["sub"]
    assert sub.player_id == f"{A}_p14" and sub.player2_id == f"{A}_p9" and sub.f["behind"] is True
    assert by_kind["chance"].f["xg"] == 0.25
    # no moment after the cutoff, and event moments don't change when the future is removed
    cut = 25 * MIN
    assert all(m["t_ms"] <= cut for m in d.moments_until(cut))
    past = detect(MatchTimeline(tl.match, [e for e in tl.events if e.match_elapsed_ms <= cut]))
    full = [m for m in detect(tl) if m.t_ms <= cut and m.kind in ("goal", "card", "chance", "sub")]
    assert [(m.kind, m.t_ms, m.f) for m in full] == [(m.kind, m.t_ms, m.f) for m in past if m.kind in ("goal", "card", "chance", "sub")]


def test_series_cut_and_meta_and_focus():
    tl = _timeline()
    d = MatchdayData(tl)
    pts = d.series(10 * MIN)["points"]
    assert pts and all(p["t_ms"] <= 10 * MIN for p in pts) and pts[-1]["clock"] == "11′"
    assert pts[-1]["win"] is not None and abs(sum(pts[-1]["win"]) - 1) < 0.01
    m = meta(tl, d.roles)
    assert m["home"]["side"] == "home" and len(m["players"]) == 24 and m["has_tracking"]
    assert {p["role"] for p in m["players"] if p["team_id"] == H} >= {"GK", "DEF", "MID", "ATT"}
    pf = player_focus(d, f"{H}_p6", 10 * MIN)
    assert pf["passes"] > 0 and pf["passes_ok"] == pf["passes"] and pf["heat"]["cols"] == 21 and sum(pf["heat"]["counts"]) > 0
    assert player_focus(d, "nobody", 10 * MIN) is None


class _Store:
    def __init__(self, tl):
        self.tl = tl

    def get(self, match_id):
        return self.tl if match_id == "m-test" else None

    def match_ids(self):
        return ["m-test"]

    def summaries(self):
        return [{"match_id": "m-test", "competition": "Test Cup"}]

    def status(self):
        return {"source": "test"}

    def all_matches(self):
        return [self.tl.match]


def test_api_matchday_endpoints(monkeypatch):
    monkeypatch.setenv("FOOTBALLIQ_PRELOAD", "m-test")
    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "off")
    c = TestClient(create_app(store=_Store(_timeline())))
    assert c.get("/v1/matches").json()[0]["featured"] is True
    meta_ = c.get("/v1/matches/m-test/matchday/meta").json()
    assert meta_["home"]["name"] == "Home FC" and meta_["periods"][1]["base_minute"] == 45
    s = c.get("/v1/matches/m-test/matchday/series", params={"to_ms": 15 * MIN}).json()
    assert s["step_ms"] == 30_000 and max(p["t_ms"] for p in s["points"]) <= 15 * MIN
    mo = c.get("/v1/matches/m-test/matchday/moments", params={"to_ms": 15 * MIN}).json()["moments"]
    assert all(m["t_ms"] <= 15 * MIN for m in mo) and not any(m["kind"] == "goal" for m in mo)
    assert any(m["kind"] == "goal" for m in c.get("/v1/matches/m-test/matchday/moments", params={"to_ms": 21 * MIN}).json()["moments"])
    assert c.get("/v1/matches/m-test/matchday/player/home-fc_p6", params={"at_ms": 10 * MIN}).status_code == 200
    assert c.get("/v1/matches/m-test/matchday/player/nobody", params={"at_ms": 10 * MIN}).status_code == 404
    assert c.get("/v1/matches/nope/matchday/meta").status_code == 404
