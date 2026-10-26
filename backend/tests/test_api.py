from fastapi.testclient import TestClient

from footballiq.api.app import create_app

MID = "2022-01-01_home-fc_away-fc"


def test_rest_endpoints_hide_result(silver_store):
    client = TestClient(create_app(silver_store))
    assert client.get("/health").json()["matches"] == 1
    matches = client.get("/v1/matches").json()
    assert matches[0]["match_id"] == MID and "result" not in matches[0]
    ov = client.get(f"/v1/matches/{MID}/overview").json()
    assert "result" not in ov and ov["home"]["name"] == "Home FC"
    assert client.get(f"/v1/matches/{MID}/events").status_code == 422  # cutoff required
    evs = client.get(f"/v1/matches/{MID}/events", params={"to_ms": 600_000}).json()["events"]
    assert evs[-1]["event_id"] == "e4"
    st = client.get(f"/v1/matches/{MID}/state", params={"at_ms": 600_000}).json()
    assert st["score"] == {"home-fc": 1, "away-fc": 0}
    assert client.get("/v1/matches/nope/overview").status_code == 404


def test_matches_allowlist_hides_other_matches(silver_store, monkeypatch):
    monkeypatch.setenv("FOOTBALLIQ_MATCHES", "some-other-match")
    client = TestClient(create_app(silver_store))
    assert client.get("/v1/matches").json() == []
    assert client.get(f"/v1/matches/{MID}/overview").status_code == 404
    monkeypatch.setenv("FOOTBALLIQ_MATCHES", f" {MID} ,some-other-match")
    assert [m["match_id"] for m in client.get("/v1/matches").json()] == [MID]
    assert client.get(f"/v1/matches/{MID}/overview").status_code == 200


def test_websocket_seek_and_generation(silver_store):
    client = TestClient(create_app(silver_store))
    with client.websocket_connect(f"/v1/matches/{MID}/replay") as ws:
        kinds = []
        first = ws.receive_json()
        while first["type"] != "reset":
            kinds.append(first["type"])
            first = ws.receive_json()
        assert kinds == ["loading", "tracking_meta"]
        assert first["generation_id"] == 0
        ws.send_json({"action": "seek", "to_ms": 66 * 60_000})
        msg = ws.receive_json()
        while msg["type"] != "reset":
            msg = ws.receive_json()
        assert msg["generation_id"] == 1
        assert msg["state"]["score"] == {"home-fc": 1, "away-fc": 1}
        assert [e["event_id"] for e in msg["recent_events"]][-1] == "e7"
        assert [e["event_id"] for e in msg["key_events"]] == ["e1", "e4", "e5", "e6", "e7"]
        ws.send_json({"action": "bogus"})
        msg = ws.receive_json()
        while msg["type"] != "error":
            msg = ws.receive_json()


def test_history_excludes_the_match_itself(silver_store):
    client = TestClient(create_app(silver_store))
    h = client.get(f"/v1/matches/{MID}/history").json()
    assert h["cutoff_date"] == "2022-01-01"
    assert h["teams"]["home-fc"]["form"] == [] and h["head_to_head"] == []
