import math

from footballiq.schema import FreezeFrame, FreezeFramePlayer, MatchEvent
from footballiq.shots import geometry, placement, pressure, shot_rows, summary, zone


def _shot(x, y, team="h", outcome="Saved", end_y=None, eid="s1"):
    return MatchEvent(event_id=eid, match_id="m", provider="statsbomb", source_sequence=1, period=1, period_elapsed_ms=1000,
                      match_elapsed_ms=1000, clock_label="00:01", team_id=team, team_name=team, type="Shot", outcome=outcome,
                      is_goal=outcome == "Goal", x_m=x, y_m=y, end_x_m=105.0 if team == "h" else 0.0, end_y_m=end_y, provider_xg=0.2)


def test_geometry_mirrors_for_away_team():
    h, a = geometry(94.0, 34.0, True), geometry(11.0, 34.0, False)
    assert math.isclose(h["distance_m"], 11.0) and math.isclose(a["distance_m"], 11.0)
    assert math.isclose(h["angle_deg"], a["angle_deg"]) and h["centrality_deg"] == 0
    assert math.isclose(h["angle_deg"], math.degrees(2 * math.atan(3.66 / 11.0)))
    assert zone(11.0, 0.0) == "penalty area" and zone(4.0, 2.0) == "six-yard box" and zone(25.0, 0.0) == "outside the box"


def test_placement_is_from_the_shooters_view():
    # home attacks x=105, y grows downwards: their left is smaller y
    assert placement(_shot(94, 34, "h", end_y=31.0), True) == "left"
    assert placement(_shot(11, 34, "a", end_y=31.0), False) == "right"
    assert placement(_shot(94, 34, "h", end_y=34.2), True) == "centre"
    assert placement(_shot(94, 34, "h", outcome="Off T", end_y=31.0), True) is None


def test_pressure_from_360_and_summary():
    ev = _shot(94.0, 34.0)
    ff = FreezeFrame(event_id="s1", match_elapsed_ms=1000, players=[
        FreezeFramePlayer(x_m=100.0, y_m=34.0, team_id="a", teammate=False, actor=False, keeper=False),   # in the cone
        FreezeFramePlayer(x_m=95.0, y_m=20.0, team_id="a", teammate=False, actor=False, keeper=False),    # outside
        FreezeFramePlayer(x_m=104.0, y_m=34.0, team_id="a", teammate=False, actor=False, keeper=True),
    ])
    p = pressure(ev, ff, True)
    assert p["defenders_in_cone"] == 1 and p["nearest_defender_m"] == 6.0 and p["keeper_off_line_m"] == 1.0 and p["keeper_in_cone"]
    rows = shot_rows([ev, _shot(80, 34, outcome="Goal", eid="s2")], {"s1": ff}, "h", {"s2": {"xg": 0.05, "xg_lo": 0.04, "xg_hi": 0.06}})
    assert rows[0]["has_360"] and not rows[1]["has_360"] and rows[1]["xg"] == 0.05
    s = summary(rows, ["h", "a"])
    assert s["h"]["shots"] == 2 and s["h"]["accuracy_pct"] == 100.0 and s["h"]["goals"] == 1
    assert s["h"]["xg"] == 0.25 and s["a"]["shots"] == 0


def test_no_xg_source_reads_unknown_not_zero():
    e = _shot(94.0, 34.0)
    e.provider_xg = None
    s = summary(shot_rows([e], {}, "h"), ["h"])["h"]
    assert s["xg"] is None and s["xg_per_shot"] is None and s["goals_minus_xg"] is None and s["shots"] == 1
