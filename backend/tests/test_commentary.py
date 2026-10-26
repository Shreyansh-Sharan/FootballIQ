"""Commentary lines, causality, booth rules, API and the TTS fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient

from footballiq.api.app import create_app
from footballiq.commentary import tts
from footballiq.commentary.engine import LANGS, build_script, speak_ms
from footballiq.commentary.lexicon import COLOUR, PBP
from footballiq.matchday.service import MatchdayData, meta
from test_matchday import MIN, _Store, _timeline


def _script(lang):
    tl = _timeline()
    d = MatchdayData(tl)
    return tl, build_script(tl, meta(tl, d.roles), lang, d)


def test_lexicon_has_the_same_situations_in_every_language():
    assert set(PBP["en"]) == set(PBP["es"]) == set(PBP["hi"])
    assert set(COLOUR["en"]) == set(COLOUR["es"]) == set(COLOUR["hi"])


def test_goal_call_and_post_goal_sequence_in_every_language():
    for lang in LANGS:
        tl, lines = _script(lang)
        goal = next(l for l in lines if l.kind == "goal")
        assert goal.priority == 1 and goal.excitement == 3 and goal.t_ms > 20 * MIN       # said after the ball went in
        after = [l.kind for l in lines if goal.t_ms < l.t_ms <= goal.t_ms + 60_000]
        assert "goal_reaction" in after and "score_recap" in after
        assert any(l.kind == "card" for l in lines) and any(l.kind == "sub" for l in lines)


def test_lines_are_causal_unique_and_one_voice_at_a_time():
    tl, lines = _script("en")
    events = {e.event_id: e for e in tl.events}
    assert len({l.id for l in lines}) == len(lines) and [l.t_ms for l in lines] == sorted(l.t_ms for l in lines)
    for a, b in zip(lines, lines[1:]):
        assert a.t_ms + a.dur_ms <= b.t_ms or b.interrupts          # overlap only when the next line cuts in
    first_event = min(e.match_elapsed_ms for e in events.values())
    assert lines[0].t_ms >= first_event


def test_analyst_speaks_and_names_are_used():
    tl, lines = _script("en")
    d = MatchdayData(tl)
    scorer = next(p["short"] for p in meta(tl, d.roles)["players"] if p["player_id"] == "home-fc_p9")
    assert any(l.speaker == "colour" for l in lines)
    assert scorer in next(l for l in lines if l.kind == "goal").text          # the scorer is named in the call


def test_speaking_time_model():
    assert speak_ms("Fernández, inside to Mac Allister.", "en", "pbp", 0) < speak_ms("Fernández, inside to Mac Allister.", "en", "pbp", 3)
    assert 1_500 < speak_ms("Fernández, inside to Mac Allister.", "en", "pbp", 0) < 4_000


def test_api_commentary_cut_and_audio_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("FOOTBALLIQ_PSEUDONYMS", "off")
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.setattr(tts.config, "data_dir", lambda: tmp_path)
    c = TestClient(create_app(store=_Store(_timeline())))
    r = c.get("/v1/matches/m-test/commentary", params={"lang": "es", "to_ms": 21 * MIN}).json()
    assert r["tts"] == "none" and r["lines"] and all(l["t_ms"] <= 21 * MIN for l in r["lines"])
    assert any(l["kind"] == "goal" for l in r["lines"]) and all(l["audio_url"] is None for l in r["lines"])
    later = c.get("/v1/matches/m-test/commentary", params={"lang": "es", "from_ms": 21 * MIN, "to_ms": 31 * MIN}).json()["lines"]
    assert all(21 * MIN < l["t_ms"] <= 31 * MIN for l in later)
    line_id = r["lines"][0]["id"]
    audio = c.get(f"/v1/matches/m-test/commentary/audio/{line_id}", params={"lang": "es"})
    assert audio.status_code == 503 and audio.headers["retry-after"] == "5"      # the client speaks it with the browser voice
    assert c.get("/v1/matches/m-test/commentary/audio/nope", params={"lang": "es"}).status_code in (404, 503)
    assert c.get("/v1/matches/m-test/commentary", params={"lang": "fr", "to_ms": 1000}).status_code == 422
