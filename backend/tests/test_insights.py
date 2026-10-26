"""Automatic insights and player analytics: no lookahead, stable ids, sensible signals, API wiring."""
from fastapi.testclient import TestClient

from footballiq.coach import CoachService
from footballiq.insights import detect
from footballiq.players import SITUATIONS, best_for, player_form, substitution_options


def test_insights_are_chronological_and_never_ahead_of_the_clock(timeline):
    items, sources = detect(timeline)
    assert "events" in sources and items
    assert [i.t_ms for i in items] == sorted(i.t_ms for i in items)
    goal = next(i for i in items if i.kind == "goal")
    assert goal.priority == 1 and goal.seek_ms < goal.t_ms
    # recomputing gives identical ids (the UI tracks what it has shown by id)
    assert [i.id for i in detect(timeline)[0]] == [i.id for i in items]


def test_coach_service_filters_by_clock(silver_store):
    coach = CoachService(silver_store)
    mid = silver_store.match_ids()[0]
    full = coach.insights(mid, 10**12)["insights"]
    goal_t = next(i["t_ms"] for i in full if i["kind"] == "goal")
    before = coach.insights(mid, goal_t - 1)["insights"]
    assert all(i["t_ms"] <= goal_t - 1 for i in before) and not any(i["kind"] == "goal" for i in before)
    assert coach.find_insight(mid, full[0]["id"])["id"] == full[0]["id"]


def test_player_form_and_recommendations_shape(timeline):
    t = timeline.match.duration_ms
    form = player_form(timeline, t)
    home = timeline.match.home.team_id
    assert {p.team_id for ps in form.values() for p in ps} <= set(form)
    so = substitution_options(timeline, t, home, form)
    assert so["remaining"] >= 0 and isinstance(so["options"], list)
    for situation in SITUATIONS:
        b = best_for(timeline, t, home, situation, form)
        assert b["situation"] == situation and all("why" in r for r in b["ranked"])


def test_scorer_is_less_likely_to_be_subbed_off(final_timeline):
    timeline = final_timeline
    t = timeline.match.periods[1].start_match_ms + 15 * 60_000
    form = player_form(timeline, t)
    home = timeline.match.home.team_id
    outfield = [p for p in form[home] if p.on_pitch and p.role != "GK" and p.minutes >= 40 and not p.stats.get("goals")][:2]
    assert len(outfield) == 2
    for p in outfield:
        p.flags, p.reasons, p.impact = ["dip", "card_risk"], ["dip"], -1.0
    outfield[0].stats = {**outfield[0].stats, "goals": 2}
    so = substitution_options(timeline, t, home, form, top=11)
    assert so["method"].startswith("rule-based")
    score = {o["off"]["player_id"]: o for o in so["options"]}
    if so["remaining"]:
        scorer, other = score.get(outfield[0].player_id), score[outfield[1].player_id]
        assert scorer is None or (scorer["score"] < other["score"] and any("scored 2 today" in w for w in scorer["why_off"]))


def test_real_final_penalty_signal_names_the_taker(final_timeline):
    items, _ = detect(final_timeline, coach=CoachService(store=_Single(final_timeline)))
    pens = [i for i in items if i.kind == "best_penalty"]
    assert pens, "fouls won in the box at 21' and 79' should be flagged"
    france = next(i for i in pens if i.team_id == "france")
    assert france.subject["ranked"][0]["name"].startswith("Kylian")
    for i in items:
        assert i.subject is None or "type" in i.subject


def test_api_endpoints(silver_store):
    from footballiq.api.app import create_app
    client = TestClient(create_app(store=silver_store))
    mid = silver_store.match_ids()[0]
    r = client.get(f"/v1/matches/{mid}/insights", params={"at_ms": 10**9}).json()
    assert r["insights"] and r["sources"]
    team = silver_store.get(mid).match.home.team_id
    assert client.get(f"/v1/matches/{mid}/players", params={"at_ms": 600_000}).status_code == 200
    assert client.get(f"/v1/matches/{mid}/players/substitutions", params={"at_ms": 600_000, "team": team}).status_code == 200
    ok = client.get(f"/v1/matches/{mid}/players/best", params={"at_ms": 600_000, "team": team, "situation": "corner"})
    bad = client.get(f"/v1/matches/{mid}/players/best", params={"at_ms": 600_000, "team": team, "situation": "throw_in"})
    assert ok.status_code == 200 and bad.status_code == 422


class _Single:
    """Minimal store over one timeline (for the real-final test)."""

    def __init__(self, tl):
        self.tl = tl

    def get(self, match_id):
        return self.tl if match_id == self.tl.match.canonical_match_id else None
