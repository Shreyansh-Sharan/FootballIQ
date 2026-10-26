from __future__ import annotations

import os
from pathlib import Path

import pytest

from footballiq import config
from footballiq.ingest.statsbomb import normalize_match
from footballiq.replay.timeline import MatchTimeline
from footballiq.store import MatchStore

# tests never read the developer's real .env (credentials, live Foundry/Fabric)
os.environ["FOOTBALLIQ_ENV_FILE"] = str(Path(__file__).parent / "no-such.env")
# most tests assert real names and canonical ids; test_aliases.py turns fictional names on itself
os.environ["FOOTBALLIQ_PSEUDONYMS"] = "off"

HOME = {"id": 1, "name": "Home FC"}
AWAY = {"id": 2, "name": "Away FC"}
P_H = {"id": 10, "name": "Home Striker"}
P_A = {"id": 20, "name": "Away Striker"}


def _ev(idx, period, ts, typ, team, player=None, **extra):
    e = {
        "id": f"e{idx}", "index": idx, "period": period, "timestamp": ts, "minute": 0, "second": 0,
        "type": {"name": typ}, "team": team, "possession": idx, "possession_team": team,
        "play_pattern": {"name": "Regular Play"},
    }
    if player:
        e["player"] = player
    e.update(extra)
    return e


@pytest.fixture
def raw_match() -> dict:
    events = [
        _ev(1, 1, "00:00:00.000", "Half Start", HOME),
        _ev(2, 1, "00:00:01.000", "Pass", HOME, P_H, location=[60, 40], pass_={}),
        _ev(3, 1, "00:00:05.000", "Pass", AWAY, P_A, location=[60, 40],
            **{"pass": {"outcome": {"name": "Incomplete"}, "end_location": [70, 40]}}),
        _ev(4, 1, "00:10:00.000", "Shot", HOME, P_H, location=[108, 40],
            shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.4, "type": {"name": "Open Play"}}),
        _ev(5, 1, "00:45:00.000", "Half End", HOME),
        _ev(6, 2, "00:00:00.000", "Half Start", HOME),
        _ev(7, 2, "00:20:00.000", "Shot", AWAY, P_A, location=[110, 40],
            shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.7, "type": {"name": "Penalty"}}),
        _ev(8, 2, "00:30:00.000", "Pass", HOME, P_H, location=[30, 30],
            **{"pass": {"type": {"name": "Corner"}, "end_location": [110, 40]}}),
        _ev(9, 2, "00:46:00.000", "Half End", HOME),
    ]
    for e in events:
        e.pop("pass_", None)
    return {
        "matches": [{
            "match_id": 99, "match_date": "2022-01-01", "kick_off": "15:00:00.000",
            "competition": {"competition_name": "Test Cup"}, "season": {"season_name": "2022"},
            "home_team": {"home_team_id": 1, "home_team_name": "Home FC"},
            "away_team": {"away_team_id": 2, "away_team_name": "Away FC"},
            "home_score": 1, "away_score": 1,
        }],
        "events": events,
        "lineups": [
            {"team_id": 1, "lineup": [{"player_id": 10, "player_name": "Home Striker", "jersey_number": 9}]},
            {"team_id": 2, "lineup": [{"player_id": 20, "player_name": "Away Striker", "jersey_number": 9}]},
        ],
        "three_sixty": [{
            "event_uuid": "e4", "visible_area": [100, 0, 120, 0, 120, 80, 100, 80],
            "freeze_frame": [
                {"teammate": True, "actor": True, "keeper": False, "location": [108, 40]},
                {"teammate": False, "actor": False, "keeper": True, "location": [119, 40]},
            ],
        }],
    }


@pytest.fixture
def timeline(raw_match) -> MatchTimeline:
    match, events, frames = normalize_match(raw_match, 99)
    return MatchTimeline(match, events, frames)


REAL_SILVER = config.silver_dir() / "2022-12-18_argentina_france"


@pytest.fixture(scope="session")
def final_timeline() -> MatchTimeline:
    if not (REAL_SILVER / "match.json").exists():
        pytest.skip("run `footballiq-ingest` first to download the 2022 final")
    return MatchStore(REAL_SILVER.parent).get(REAL_SILVER.name)


@pytest.fixture
def silver_store(tmp_path: Path, raw_match) -> MatchStore:
    from footballiq.ingest.statsbomb import write_silver

    write_silver(*normalize_match(raw_match, 99), silver=tmp_path)
    return MatchStore(tmp_path)
