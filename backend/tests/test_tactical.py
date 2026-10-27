import pyarrow as pa
import pytest

from footballiq.tactical import TacticalStore, WindowNotComplete


class FakeLakehouse:
    def __init__(self):
        self.t = {
            "gold_tactical_window": pa.table({
                "window_id": ["0-15", "15-30"], "team_id": ["home-fc", "home-fc"], "start_ms": [0, 900_000],
                "end_ms": [899_000, 1_799_000], "possession_pct": [55.0, 48.0], "formation": ["4-3-3", "4-4-2"],
                "declared_formation": ["4-2-3-1", "4-2-3-1"], "possession_pct_statsbomb": [57.25, 50.0],
                "possession_agree_statsbomb_pct": [91.5, 90.0],
                "width_in_possession_m": [44.0, 40.0], "depth_in_possession_m": [30.0, 29.0]}),
            "gold_passing_network": pa.table({
                "window_id": ["0-15"], "team_id": ["home-fc"], "from_id": ["a"], "to_id": ["b"], "passes": [4],
                "from_x": [30.0], "from_y": [20.0], "to_x": [50.0], "to_y": [30.0]}),
            "gold_heatmap": pa.table({"window_id": ["0-15"], "team_id": ["home-fc"], "cx": [3], "cy": [4], "samples": [10]}),
            "gold_regains": pa.table({"window_id": ["0-15"], "team_id": ["home-fc"], "zx": [2], "zy": [1], "regains": [3]}),
            "gold_player_metrics_1s": pa.table({
                "team_id": ["home-fc"] * 3, "side": ["home"] * 3, "jersey_num": ["9"] * 3, "player_id": ["p9"] * 3,
                "player_name": ["Nine"] * 3, "position_group": ["CF"] * 3, "second": [10, 11, 12],
                "distance_m": [5.0, 8.0, 2.0], "avg_speed_mps": [5.0, 8.0, 2.0], "max_speed_mps": [5.2, 8.4, 2.5],
                "frames": [30, 30, 30], "observed_frames": [30, 15, 0]}),
            "gold_formation_timeline": pa.table({
                "team_id": ["home-fc"] * 3, "start_ms": [0, 60_000, 120_000], "end_ms": [60_000, 120_000, 180_000],
                "raw_formation": ["4-3-3", "4-4-2", "4-4-2"], "confidence": [0.9, 0.8, 0.85], "formation": ["4-3-3", "4-3-3", "4-4-2"]}),
            "gold_formation_switches": pa.table({
                "team_id": ["home-fc"], "at_ms": [120_000], "from_formation": ["4-3-3"], "to_formation": ["4-4-2"]}),
        }
        self.sql: list[str] = []

    def query(self, sql, tables):
        self.sql.append(sql)
        return self.t[next(iter(tables.values()))]


def test_windows_gated_by_replay_clock():
    ts = TacticalStore(FakeLakehouse())
    w = {x["window_id"]: x for x in ts.windows("m", 1_000_000)}
    assert w["0-15"]["available"] and not w["15-30"]["available"] and w["15-30"]["in_progress"]
    with pytest.raises(WindowNotComplete):
        ts.window("m", "home-fc", "15-30", 1_000_000)
    d = ts.window("m", "home-fc", "0-15", 1_000_000)
    assert d["metrics"]["formation"] == "4-3-3" and d["network"]["edges"][0]["passes"] == 4
    m = d["metrics"]
    assert (m["declared_formation"], m["possession_pct"], m["possession_pct_statsbomb"], m["possession_agree_statsbomb_pct"]) == ("4-2-3-1", 55.0, 57.25, 91.5)
    assert [x["window_id"] for x in ts.timeline("m", 1_000_000)] == ["0-15"]


def test_physical_accumulates_up_to_clock():
    ts = TacticalStore(FakeLakehouse())
    assert ts.physical("m", 9_000) == []
    p = ts.physical("m", 11_500)[0]
    assert p["distance_km"] == 0.013 and p["sprint_km"] == 0.008 and p["hsr_km"] == 0.008
    assert p["top_speed_kmh"] == round(5.0 * 3.6, 1)  # speed held over 2 consecutive seconds (5 then 8 m/s)
    assert ts.physical("m", 60_000)[0]["distance_km"] == 0.015


def test_formations_cut_at_the_clock_and_queried_once_per_match():
    lh = FakeLakehouse()
    ts = TacticalStore(lh)
    early = ts.formations("m", 125_000)
    assert [x["end_ms"] for x in early["segments"]] == [60_000, 120_000] and early["switches"] == []
    late = ts.formations("m", 180_000)
    assert [x["formation"] for x in late["segments"]] == ["4-3-3", "4-3-3", "4-4-2"]
    assert [(x["from_formation"], x["to_formation"]) for x in late["switches"]] == [("4-3-3", "4-4-2")]
    assert len(lh.sql) == 2 and all("<=" not in q for q in lh.sql)      # whole timeline once, cut in memory
