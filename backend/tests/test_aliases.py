"""Fictional names and public ids: no real name or real-name id reaches a client."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from footballiq import aliases
from footballiq.agents.definitions import AGENTS
from footballiq.agents.tools import MatchTools
from footballiq.aliases import ALIAS_RE, AliasBook, AliasedStore, get_book, name_key
from footballiq.api.app import create_app
from footballiq.api.privacy import install_privacy
from footballiq.replay.timeline import MatchTimeline, event_payload
from footballiq.replay.tracking import TrackedPlayer, TrackingTimeline
from footballiq.schema import Match, MatchEvent, Period, Player, Team
from footballiq.store import LocalStore

MID = "2022-12-18_argentina_france"
DEVANAGARI = re.compile(r"^[ऀ-ॿ0-9 .\-]+$")

# real team names (mapped by the curated table); the people are made up
HOME_PLAYERS = [  # (slug, name, nickname, shirt)
    ("ramon-quintana-velez", "Ramón Quintana Vélez", "Ramón Quintana", 10),
    ("lisandro-bermudez", "Lisandro Bermúdez", None, 9),
    ("esteban-carrizo", "Esteban Carrizo", None, 1),
    ("hugo-de-la-pena", "Hugo de la Peña", None, 5),
    ("tadeo-villagra", "Tadeo Villagra", None, 7),
    ("nicanor-ezcurra", "Nicanor Ezcurra", None, 19),
]
AWAY_PLAYERS = [
    ("theo-garnier-lavalle", "Théo Garnier-Lavalle", "Théo Garnier", 10),
    ("mamadou-keita-sow", "Mamadou Kéïta Sow", None, 7),
    ("gaspard-roulin", "Gaspard Roulin", None, 1),
    ("yanis-fontanel", "Yanis Fontanel", None, 4),
    ("cyprien-maubert", "Cyprien Maubert", None, 11),
]
REFEREE, STADIUM, COMPETITION = "Bartolomé Ziegler", "Lusail Stadium", "FIFA World Cup"
REAL_STRINGS = (["Argentina", "France", "Argentine", "Argentinian", "French", "Les Bleus", "Albiceleste", REFEREE,
                 "Ziegler", STADIUM, "Lusail", COMPETITION, "World Cup", MID, "argentina", "france"]
                + [n for _, n, _, _ in HOME_PLAYERS + AWAY_PLAYERS]
                + [nick for _, _, nick, _ in HOME_PLAYERS + AWAY_PLAYERS if nick]
                + ["Quintana", "Bermúdez", "Carrizo", "de la Peña", "Villagra", "Ezcurra", "Garnier", "Roulin", "Fontanel",
                   "Maubert", "Kéïta Sow"]
                + [f"{t}_{slug}" for t, ps in (("argentina", HOME_PLAYERS), ("france", AWAY_PLAYERS)) for slug, *_ in ps])


def pid(team, slug):
    return f"{team}_{slug}"


def build_match() -> Match:
    players = [Player(player_id=pid("argentina", s), team_id="argentina", name=n, nickname=k, jersey_number=j, starter=True,
                      source_ids={}) for s, n, k, j in HOME_PLAYERS]
    players += [Player(player_id=pid("france", s), team_id="france", name=n, nickname=k, jersey_number=j, starter=True,
                       source_ids={}) for s, n, k, j in AWAY_PLAYERS]
    return Match(canonical_match_id=MID, competition=COMPETITION, season="2022", stage="Final",
                 kickoff_source="2022-12-18 15:00:00.000", stadium=STADIUM, referee=REFEREE,
                 home=Team(team_id="argentina", name="Argentina", source_ids={}),
                 away=Team(team_id="france", name="France", source_ids={}),
                 periods=[Period(period=1, label="1st half", start_match_ms=0, duration_ms=2_700_000),
                          Period(period=2, label="2nd half", start_match_ms=2_700_000, duration_ms=2_700_000)],
                 duration_ms=5_400_000, source_ids={}, players=players, result={"home": 1, "away": 0})


def _ev(i, t, team, typ, player=None, recipient=None, **kw):
    names = {pid(tm, s): n for tm, ps in (("argentina", HOME_PLAYERS), ("france", AWAY_PLAYERS)) for s, n, *_ in ps}
    return MatchEvent(event_id=f"e{i}", match_id=MID, provider="statsbomb", source_sequence=i, period=1 if t < 2_700_000 else 2,
                      period_elapsed_ms=t % 2_700_000, match_elapsed_ms=t, clock_label="00:00", team_id=team,
                      team_name={"argentina": "Argentina", "france": "France"}[team], player_id=player,
                      player_name=names.get(player), recipient_id=recipient, recipient_name=names.get(recipient), type=typ,
                      possession_team_id=team, x_m=50.0, y_m=34.0, **kw)


def build_events() -> list[MatchEvent]:
    q, b, g = pid("argentina", "ramon-quintana-velez"), pid("argentina", "lisandro-bermudez"), pid("france", "theo-garnier-lavalle")
    return [_ev(1, 0, "argentina", "Half Start"),
            _ev(2, 60_000, "argentina", "Pass", q, b, outcome="Complete"),
            _ev(3, 600_000, "argentina", "Shot", b, outcome="Goal", is_goal=True, provider_xg=0.4),
            _ev(4, 900_000, "france", "Foul Committed", g, card="Yellow Card"),
            _ev(5, 3_000_000, "france", "Substitution", pid("france", "cyprien-maubert"), pid("france", "yanis-fontanel"))]


PFF_Q10 = "argentina_ramon-quintana"     # PFF-style id of Argentina's #10; differs from the event id
EXTRA = "argentina_pablo-extra"          # tracked player with no line-up shirt match


def build_tracking() -> TrackingTimeline:
    n = 60
    t = (np.arange(n) * 100).astype(np.int64)
    frames = {"frame_num": np.arange(n), "t": t, "period": np.ones(n, np.int8), "ball_x": np.full(n, 50, np.float32),
              "ball_y": np.full(n, 34, np.float32), "ball_z": np.zeros(n, np.float32), "ball_observed": np.ones(n, bool)}
    positions = {"frame_num": np.repeat(np.arange(n), 3), "player_idx": np.tile([0, 1, 2], n),
                 "x": np.full(3 * n, 40, np.float32), "y": np.full(3 * n, 30, np.float32), "observed": np.ones(3 * n, bool)}
    players = [TrackedPlayer(0, "argentina", "home", "10", PFF_Q10, "Ramon Quintana"),
               TrackedPlayer(1, "france", "away", "10", pid("france", "theo-garnier-lavalle"), "Théo Garnier"),
               TrackedPlayer(2, "argentina", "home", "99", EXTRA, "Pablo Extrañez")]
    return TrackingTimeline.from_columns(MID, "pff_fc", frames, positions, players)


def build_timeline() -> MatchTimeline:
    return MatchTimeline(build_match(), build_events(), tracking=build_tracking())


def write_store(root: Path) -> LocalStore:
    d = root / MID
    d.mkdir(parents=True)
    (d / "match.json").write_text(build_match().model_dump_json())
    (d / "events.jsonl").write_text("\n".join(e.model_dump_json() for e in build_events()) + "\n")
    store = LocalStore(root)
    store.get(MID).tracking = build_tracking()
    return store


def leaks(payload, ids: bool = True) -> list[str]:
    """Real names (any case, accents ignored) and, unless ``ids`` is False, real-name ids found in ``payload``."""
    text = json.dumps(payload, ensure_ascii=False)
    low = aliases.fold(text)
    found = [s for s in REAL_STRINGS if re.search(r"(?<![\w-])" + re.escape(aliases.fold(s)) + r"(?![\w-])", low)]
    if not ids:   # internal objects keep canonical ids on purpose: only capitalised names count
        found = [s for s in found if s[:1].isupper() and re.search(r"(?<![\w-])" + re.escape(s) + r"(?![\w-])", text)]
    return found


@pytest.fixture
def book_on(monkeypatch):
    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "on")
    aliases.reset_book()
    yield get_book()
    aliases.reset_book()


def fresh_book() -> AliasBook:
    return AliasBook(enabled=True)


def test_aliases_are_deterministic_across_processes():
    book = fresh_book()
    m = build_match()
    book.register_match(m)
    here = {"match": book.match_public_id(MID), "team": [book.team("argentina").public_id, book.team("argentina").name],
            "players": {p.player_id: [book.player(p.player_id).public_id, book.player(p.player_id).name,
                                      book.player(p.player_id).name_hi] for p in m.players},
            "referee": book.official(REFEREE).name, "stadium": book.venue(STADIUM).name}
    script = (
        "import json, sys\n"
        "from footballiq.aliases import AliasBook\n"
        "from footballiq.schema import Match\n"
        "m = Match.model_validate_json(sys.stdin.read())\n"
        "b = AliasBook(enabled=True)\n"
        "b.register_match(m)\n"
        f"print(json.dumps({{'match': b.match_public_id({MID!r}), "
        "'team': [b.team('argentina').public_id, b.team('argentina').name], "
        "'players': {p.player_id: [b.player(p.player_id).public_id, b.player(p.player_id).name, b.player(p.player_id).name_hi]"
        " for p in m.players}, "
        f"'referee': b.official({REFEREE!r}).name, 'stadium': b.venue({STADIUM!r}).name}}, ensure_ascii=False))\n")
    env = {**os.environ, "PYTHONHASHSEED": "12345", "FOOTBALLIQ_PSEUDONYMS": "on"}
    out = subprocess.run([sys.executable, "-c", script], input=build_match().model_dump_json(), capture_output=True, text=True,
                         env=env, cwd=Path(__file__).resolve().parents[1], check=True)
    assert json.loads(out.stdout) == here
    assert ALIAS_RE.match(here["match"]) and here["match"].startswith("m-") and here["team"][0].startswith("t-")
    assert here["team"][1] == "Solaria"


def test_public_ids_follow_the_salt():
    a, b = AliasBook(enabled=True, salt="one"), AliasBook(enabled=True, salt="two")
    assert a.match_public_id(MID) != b.match_public_id(MID)
    assert a.to_canonical(a.match_public_id(MID)) == MID and b.to_canonical("m-000000") is None


def test_names_unique_within_a_team_and_never_real():
    book = fresh_book()
    m = build_match()
    big = [Player(player_id=f"france_player-{i:02d}", team_id="france", name=f"Real Person{i}", jersey_number=i,
                  source_ids={}) for i in range(1, 46)]
    m.players.extend(big)
    book.register_match(m)
    als = [book.player(p.player_id) for p in m.players if p.team_id == "france"]
    assert len({a.name for a in als}) == len(als) and len({a.short for a in als}) == len(als)
    real = {name_key(p.name) for p in m.players} | {name_key(p.nickname) for p in m.players if p.nickname}
    assert not any(name_key(a.name) in real for a in als)
    real_surnames = {"quintana", "bermudez", "carrizo", "pena", "villagra", "ezcurra", "garnier", "lavalle", "sow", "roulin"}
    assert not any(t in real_surnames for a in als for t in name_key(a.short))
    for a in als:
        assert DEVANAGARI.match(a.name_hi) and DEVANAGARI.match(a.short_hi), a
        assert a.culture in ("french",)


def test_every_pool_entry_has_devanagari():
    pools = json.loads(aliases.POOLS_PATH.read_text(encoding="utf-8"))
    entries = [e for c in pools["cultures"].values() for e in c["first"] + c.get("last", [])]
    entries += pools["places"] + pools["venue_kinds"] + pools["club_suffixes"] + pools["competition_fallback"]
    entries += [[t["name"], t["name_hi"]] for t in pools["teams"].values()] + [[t["short"], t["short_hi"]] for t in pools["teams"].values()]
    entries += [[c["name"], c["name_hi"]] for c in pools["competitions"].values()]
    assert len(entries) > 2000
    bad = [e for e in entries if not (e[0].strip() and DEVANAGARI.match(e[1]) and re.search(r"[ऀ-ॿ]", e[1]))]
    assert not bad, bad[:10]
    for t in pools["teams"].values():
        assert len(t["short"]) == 3 and t["colors"]["pattern"] in ("solid", "stripes", "hoops", "tricolor")
    shorts = [t["short"] for t in pools["teams"].values()]
    assert len(set(shorts)) == len(shorts)


def test_team_alias_uses_the_pool_kit():
    a = fresh_book().team("argentina")
    assert (a.name, a.short, a.name_hi, a.short_hi) == ("Solaria", "SOL", "सोलारिया", "सोल")
    assert a.colors == {"primary": "#1f5fd6", "secondary": "#ffffff", "ink": "#ffffff", "pattern": "solid"}
    unknown = fresh_book().team("some-new-club")
    assert unknown.public_id.startswith("t-") and len(unknown.short) == 3 and DEVANAGARI.match(unknown.name_hi)


def test_rename_timeline_in_place_once():
    book = fresh_book()
    tl = build_timeline()
    book.rename_timeline(tl)
    m = tl.match
    assert m.canonical_match_id == MID and m.home.team_id == "argentina"          # ids stay canonical internally
    assert m.home.name == "Solaria" and m.away.name == "Azuria" and m.competition == "Continental Cup"
    assert m.referee == book.official(REFEREE).name and m.stadium == book.venue(STADIUM).name
    q = book.player(pid("argentina", "ramon-quintana-velez"))
    p10 = next(p for p in m.players if p.jersey_number == 10 and p.team_id == "argentina")
    assert p10.name == q.name and p10.nickname == q.short
    assert next(p for p in m.players if p.jersey_number == 9).nickname is None
    assert tl.events[1].player_name == q.name and tl.events[1].team_name == "Solaria"
    assert not leaks([e.model_dump() for e in tl.events] + [m.model_dump()] + tl.tracking.roster(), ids=False)
    before = [e.player_name for e in tl.events]
    book.rename_timeline(tl)                                                         # idempotent
    assert [e.player_name for e in tl.events] == before
    other = fresh_book()                                                             # a fresh book recovers the real names
    other.rename_timeline(tl)
    assert other.player(pid("argentina", "ramon-quintana-velez")).name == q.name


def test_pff_roster_ids_share_the_match_players_alias():
    book = fresh_book()
    tl = build_timeline()
    book.rename_timeline(tl)
    sb = pid("argentina", "ramon-quintana-velez")
    a_pff, a_sb = book.player(PFF_Q10), book.player(sb)
    assert a_pff.public_id == a_sb.public_id and a_pff.name == a_sb.name
    assert book.to_canonical(a_sb.public_id) == sb
    roster = tl.tracking.roster()
    assert roster[0]["name"] == a_sb.name and roster[0]["player_id"] == PFF_Q10       # canonical inside, fictional name
    extra = book.player(EXTRA)
    assert extra.public_id != a_sb.public_id and roster[2]["name"] == extra.name and extra.culture == "latam"
    again = fresh_book()
    again.rename_timeline(build_timeline())
    assert again.player(EXTRA).name == extra.name                                    # deterministic for tracking-only players
    out = book.to_public({"tracking": roster}, MID)["tracking"]
    assert out[0]["player_id"] == a_sb.public_id and out[1]["player_id"] == book.player(pid("france", "theo-garnier-lavalle")).public_id
    # a gold-table row (e.g. physical) with a PFF id, a shirt number and the PFF spelling of the real name
    row = {"team_id": "argentina", "jersey": "9", "player_id": "argentina_lisandro-bermudez-pff", "name": "Lisandro Bermudez"}
    pub = book.to_public(row, MID)
    b9 = book.player(pid("argentina", "lisandro-bermudez"))
    assert pub["player_id"] == b9.public_id and pub["name"] == b9.name and pub["team_id"] == book.team("argentina").public_id


def test_to_public_leaves_no_real_name_or_id():
    book = fresh_book()
    tl = build_timeline()
    book.register_timeline(tl)                       # gold-table style: the payload still carries the REAL names
    q, g = pid("argentina", "ramon-quintana-velez"), pid("france", "theo-garnier-lavalle")
    payload = {
        "overview": build_match().model_dump(exclude={"result"}),
        "events": [event_payload(e) for e in build_events()],
        "state": {"match_id": MID, "score": {"argentina": 1, "france": 0}, "stats": {"argentina": {"goals": 1}, "france": {"goals": 0}},
                  "possession_team_id": "france"},
        "physical": [{"team_id": "france", "player_id": g, "name": "Théo Garnier", "distance_km": 9.1}],
        "insight": {"title": "Argentina are turning the screw", "team": "argentina", "player": "Ramón Quintana",
                    "detail": "Quintana and Bermúdez combine; the French defence (Les Bleus) sits deep. Garnier-Lavalle is booked by "
                              "Bartolomé Ziegler at Lusail Stadium in the World Cup final. The Argentines lead.",
                    "subject": {"type": "player", "player_id": q, "name": "Ramón Quintana Vélez", "team_id": "argentina"}},
        "answer": "QUINTANA! Argentina 1-0 France. Ziegler waves play on; de la Peña and Villagra hold the line.",
        "audio_url": f"/v1/matches/{MID}/commentary/audio/c-en-000001?lang=en",
        "by_player": {q: 3, g: 1},
    }
    out = book.to_public(payload, MID)
    assert not leaks(out), leaks(out)
    ids = {book.match_public_id(MID), book.team("argentina").public_id, book.team("france").public_id}
    assert set(out["state"]["score"]) == {book.team("argentina").public_id, book.team("france").public_id}
    assert out["state"]["match_id"] in ids and out["audio_url"].startswith(f"/v1/matches/{book.match_public_id(MID)}/")
    assert out["state"]["possession_team_id"] == book.team("france").public_id
    assert set(out["by_player"]) == {book.player(q).public_id, book.player(g).public_id}
    assert out["physical"][0]["name"] == book.player(g).name
    assert out["insight"]["subject"]["name"] == book.player(q).name
    assert "Solaria" in out["insight"]["title"] and "Azurian" in out["insight"]["detail"] and "Solarians" in out["insight"]["detail"]
    assert book.player(q).short.upper() in out["answer"] and "Continental Cup" in out["insight"]["detail"]
    ev = out["events"][1]
    assert ev["player_id"] == book.player(q).public_id and ev["recipient_name"] == book.player(pid("argentina", "lisandro-bermudez")).name
    assert out["events"][0]["type"] == "Half Start" and out["events"][1]["outcome"] == "Complete"   # enums untouched
    assert book.scrub_text("Can France come back?", MID) == "Can Azuria come back?"


def test_off_switch_is_a_no_op(monkeypatch, tmp_path):
    book = AliasBook(enabled=False)
    payload = {"match_id": MID, "name": "Argentina"}
    assert book.to_public(payload) is payload and book.scrub_text("France") == "France"
    tl = build_timeline()
    book.rename_timeline(tl)
    assert tl.match.home.name == "Argentina" and tl.events[1].player_name == "Ramón Quintana Vélez"
    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "off")
    aliases.reset_book()
    store = write_store(tmp_path)
    app = create_app(store)
    assert app.state.store is store
    c = TestClient(app)
    assert c.get("/v1/matches").json()[0]["match_id"] == MID
    assert c.get(f"/v1/matches/{MID}/overview").json()["home"]["name"] == "Argentina"
    aliases.reset_book()


def test_app_serves_only_public_ids_and_fictional_names(book_on, tmp_path):
    store = write_store(tmp_path)
    app = create_app(store)
    assert isinstance(app.state.store, AliasedStore)
    c = TestClient(app)
    items = c.get("/v1/matches").json()
    assert len(items) == 1 and ALIAS_RE.match(items[0]["match_id"]) and "featured" in items[0]
    assert set(items[0]) >= {"match_id", "competition", "season", "stage", "date", "home", "away", "completeness"}
    assert items[0]["home"]["name"] == "Solaria" and items[0]["competition"] == "Continental Cup"
    pub = items[0]["match_id"]
    ov = c.get(f"/v1/matches/{pub}/overview").json()
    ev = c.get(f"/v1/matches/{pub}/events", params={"to_ms": 3_600_000}).json()
    st = c.get(f"/v1/matches/{pub}/state", params={"at_ms": 3_600_000}).json()
    tr = c.get(f"/v1/matches/{pub}/tracking").json()
    hi = c.get(f"/v1/matches/{pub}/history").json()
    ins = c.get(f"/v1/matches/{pub}/insights", params={"at_ms": 3_600_000}).json()
    for payload in (items, ov, ev, st, tr, hi, ins):
        assert not leaks(payload), leaks(payload)
    home = ov["home"]["team_id"]
    assert ALIAS_RE.match(home) and st["score"] == {home: 1, ov["away"]["team_id"]: 0}
    assert {p["player_id"] for p in tr["roster"]} <= {p["player_id"] for p in ov["players"]} | {get_book().player(EXTRA).public_id}
    # alias ids in the path and in query params are translated back
    players = c.get(f"/v1/matches/{pub}/players", params={"at_ms": 600_000, "team": home})
    assert players.status_code == 200 and not leaks(players.json())
    sub = c.get(f"/v1/matches/{pub}/players/substitutions", params={"at_ms": 600_000, "team": home})
    assert sub.status_code == 200
    # canonical ids still work for internal callers, answers are aliased anyway
    assert c.get(f"/v1/matches/{MID}/state", params={"at_ms": 0}).json()["match_id"] == pub


def test_unknown_alias_is_404(book_on, tmp_path):
    c = TestClient(create_app(write_store(tmp_path)))
    pub = c.get("/v1/matches").json()[0]["match_id"]
    r = c.get("/v1/matches/m-zzzzzz/overview")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json") and "detail" in r.json()
    assert c.get(f"/v1/matches/{pub}/players", params={"at_ms": 0, "team": "t-zzzzzz"}).status_code == 404
    assert c.get(f"/v1/matches/{pub}/matchday/player/p-zzzzzz", params={"at_ms": 0}).status_code == 404
    with pytest.raises(Exception):
        with c.websocket_connect("/v1/matches/m-zzzzzz/replay") as ws:
            ws.receive_json()


def test_websocket_frames_are_public(book_on, tmp_path):
    c = TestClient(create_app(write_store(tmp_path)))
    pub = c.get("/v1/matches").json()[0]["match_id"]
    seen = []
    with c.websocket_connect(f"/v1/matches/{pub}/replay") as ws:
        msg = ws.receive_json()
        while msg["type"] != "reset":
            seen.append(msg)
            msg = ws.receive_json()
        seen.append(msg)
        ws.send_json({"action": "seek", "to_ms": 3_600_000})
        msg = ws.receive_json()
        while msg["type"] != "reset":
            msg = ws.receive_json()
        seen.append(msg)
    assert [m["type"] for m in seen[:2]] == ["loading", "tracking_meta"]
    assert seen[0]["match_id"] == pub and not leaks(seen), leaks(seen)
    assert list(seen[-1]["state"]["score"].values()) == [1, 0] and all(ALIAS_RE.match(k) for k in seen[-1]["state"]["score"])
    # a raw JSON text frame through the middleware's sender
    book = get_book()
    from footballiq.api.privacy import PrivacyMiddleware
    sent = []

    async def capture(message):
        sent.append(message)

    sender = PrivacyMiddleware(None, book)._ws_sender(capture, book, MID)
    import asyncio
    asyncio.run(sender({"type": "websocket.send", "text": json.dumps({"type": "event", "event": {
        "team_id": "argentina", "player_id": pid("argentina", "lisandro-bermudez"), "player_name": "Lisandro Bermúdez"}})}))
    frame = json.loads(sent[0]["text"])
    assert frame["event"]["player_name"] == book.player(pid("argentina", "lisandro-bermudez")).name and not leaks(frame)


def test_non_json_responses_pass_untouched(book_on):
    book = get_book()
    book.register_match(build_match())
    app = FastAPI()
    audio = b"ID3\x03\x00" + MID.encode() + b" Argentina \xff\xfb" * 50

    @app.get("/v1/matches/{match_id}/audio")
    def audio_route(match_id: str):
        return Response(content=audio, media_type="audio/mpeg")

    @app.get("/v1/matches/{match_id}/stream")
    def stream_route(match_id: str):
        return StreamingResponse(iter([b"data: Argentina\n\n", b"data: " + match_id.encode() + b"\n\n"]), media_type="text/event-stream")

    @app.get("/v1/matches/{match_id}/json")
    def json_route(match_id: str):
        return JSONResponse({"match_id": match_id, "team": "France"})

    install_privacy(app)
    install_privacy(app)                               # idempotent
    c = TestClient(app)
    pub = book.match_public_id(MID)
    r = c.get(f"/v1/matches/{pub}/audio")
    assert r.status_code == 200 and r.content == audio and r.headers["content-type"] == "audio/mpeg"
    assert int(r.headers["content-length"]) == len(audio)
    s = c.get(f"/v1/matches/{pub}/stream")
    assert s.text == f"data: Argentina\n\ndata: {MID}\n\n"   # non-JSON streams are not buffered or rewritten
    j = c.get(f"/v1/matches/{pub}/json")
    assert j.json() == {"match_id": pub, "team": "Azuria"} and int(j.headers["content-length"]) == len(j.content)


def test_agent_tools_speak_public(book_on, tmp_path):
    store = AliasedStore(write_store(tmp_path), get_book())
    tl = store.get(MID)
    tools = MatchTools(tl, 3_600_000)
    book = get_book()
    ctx = json.loads(tools.run("get_match_context", "{}"))
    assert ctx["match_id"] == book.match_public_id(MID) and ctx["home"] == {"team_id": book.team("argentina").public_id, "name": "Solaria"}
    evs = json.loads(tools.run("get_key_events", json.dumps({"team_id": book.team("france").public_id})))["events"]
    assert evs and all(e["team_id"] == book.team("france").public_id for e in evs)
    assert not leaks(ctx) and not leaks(evs)


def test_every_agent_is_told_the_names_are_fictional():
    for spec in AGENTS.values():
        text = spec.instructions.lower()
        assert "fictional" in text and "real-world identity" in text and "use only the names the tools return" in text


def test_provider_ids_are_not_published(monkeypatch):
    """source_ids (StatsBomb / PFF ids) would let anyone look up the real team, player or match."""
    from footballiq.aliases import get_book, reset_book

    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "on")
    reset_book()
    out = get_book().to_public({"home": {"team_id": "x", "name": "X", "source_ids": {"statsbomb": 779}},
                                "source_ids": {"statsbomb": 3869685, "pff": 10517}})
    assert out["source_ids"] == {} and out["home"]["source_ids"] == {}
    reset_book()


def test_team_ids_in_lower_case_error_text_are_replaced(monkeypatch):
    """HTTP error details are lower-case free text: a canonical team id inside one must not leak."""
    from footballiq.aliases import get_book, reset_book

    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "on")
    reset_book()
    book = get_book()
    alias = book.team("home-fc")
    out = book.to_public({"detail": "no tactical data for home-fc in window w1"})
    assert "home-fc" not in out["detail"] and alias.public_id in out["detail"]
    assert book.to_public({"type": "home"}) == {"type": "home"}            # plain words are not ids
    reset_book()


def test_history_matches_competition_by_match_id_not_display_name():
    """Renamed (fictional) competition names must not break tournament history: compare via the match id."""
    from footballiq.players import HISTORY_KEYS, PROFILE_KEYS, PlayerHistory

    keys = set(PROFILE_KEYS) | set(HISTORY_KEYS) | {"goals", "xg", "shots", "def_actions", "yellows"}
    row = {k: 1 for k in keys} | {"match_id": "g1", "team_id": "a", "player_id": "a_p", "player_name": "P", "ax": 60.0,
                                    "first_ms": 0, "last_ms": 90 * 60_000, "n": 10, "gk": 0}
    meta = {"g1": {"home": "a", "date": "2022-11-20", "competition": "Real Cup"},
            "final": {"home": "a", "date": "2022-12-18", "competition": "Real Cup"}}
    h = PlayerHistory([row], meta)
    comp = h.competition_of("final", "Continental Cup")
    assert comp == "Real Cup"
    assert h.team_profile("a", "2022-12-18", comp)["matches"] == 1
    assert h.team_profile("a", "2022-12-18", "Continental Cup")["matches"] == 0
    assert h.before("a_p", "2022-12-18", comp)["matches"] == 1
