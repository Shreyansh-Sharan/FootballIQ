"""Tactical and physical views from Fabric gold tables, bounded by the replay clock.

Windows are served only after they end; physical totals accumulate over seconds <= at_ms.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from typing import Any

import numpy as np

from footballiq.fabric_source import FabricLakehouse, sql_str

WINDOWS = [
    ("0-15", "0–15′"), ("15-30", "15–30′"), ("30-45", "30–45+′"), ("45-60", "45–60′"), ("60-70", "60–70′"),
    ("70-80", "70–80′"), ("80-90", "80–90+′"), ("et1", "ET 1"), ("et2", "ET 2"),
]
LABEL = dict(WINDOWS)
HSR, SPRINT = 5.5, 7.0


class WindowNotComplete(Exception):
    pass


class TacticalStore:
    def __init__(self, lakehouse: FabricLakehouse, max_cached: int = 6):
        self.lh = lakehouse
        self.max_cached = max_cached
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._forms: OrderedDict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = OrderedDict()
        self._lock = threading.Lock()

    def _load(self, match_id: str) -> dict[str, Any]:
        with self._lock:
            if match_id in self._cache:
                self._cache.move_to_end(match_id)
                return self._cache[match_id]
        mid = sql_str(match_id)
        queries = {
            "windows": ("select * from t where match_id = {m}", "gold_tactical_window"),
            "network": ("select * from t where match_id = {m}", "gold_passing_network"),
            "heat": ("select window_id, team_id, cx, cy, samples from t where match_id = {m}", "gold_heatmap"),
            "regains": ("select window_id, team_id, zx, zy, regains from t where match_id = {m}", "gold_regains"),
            "physical": ("select team_id, side, jersey_num, player_id, player_name, position_group, second, distance_m, "
                         "avg_speed_mps, frames, observed_frames from t where match_id = {m}", "gold_player_metrics_1s"),
        }
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:  # independent tables: load concurrently
            futs = {k: pool.submit(self.lh.query, sql.format(m=mid), {"t": table}) for k, (sql, table) in queries.items()}
            res = {k: f.result() for k, f in futs.items()}
        data: dict[str, Any] = {k: res[k].to_pylist() for k in ("windows", "network", "heat", "regains")}
        data["physical"] = _index_physical(res["physical"])
        with self._lock:
            self._cache[match_id] = data
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
        return data

    # ------------------------------------------------------------------ windows
    def windows(self, match_id: str, at_ms: int) -> list[dict[str, Any]]:
        rows = self._load(match_id)["windows"]
        out = []
        for wid, label in WINDOWS:
            r = [x for x in rows if x["window_id"] == wid]
            if not r:
                continue
            start, end = min(x["start_ms"] for x in r), max(x["end_ms"] for x in r)
            out.append({"window_id": wid, "label": label, "start_ms": start, "end_ms": end,
                        "available": end <= at_ms, "in_progress": start <= at_ms < end})
        return out

    def window(self, match_id: str, team_id: str, window_id: str, at_ms: int) -> dict[str, Any]:
        d = self._load(match_id)
        row = next((x for x in d["windows"] if x["window_id"] == window_id and x["team_id"] == team_id), None)
        if row is None:
            raise KeyError(f"no tactical data for {team_id} in window {window_id}")
        if row["end_ms"] > at_ms:
            raise WindowNotComplete(f"window {LABEL.get(window_id, window_id)} ends at {row['end_ms']} ms; replay is at {at_ms} ms")
        keep = ("possession_pct", "links_per_sample", "lane_clearance_pct", "triangles_per_sample", "quads_per_sample",
                "pentagons_per_sample", "width_in_possession_m", "depth_in_possession_m", "width_out_of_possession_m",
                "depth_out_of_possession_m", "regains", "formation", "declared_formation", "samples", "possession_samples",
                "possession_pct_statsbomb", "possession_pct_pff", "possession_agree_statsbomb_pct", "possession_agree_pff_pct",
                "viable_triangles_per_sample", "viable_quads_per_sample", "viable_pentagons_per_sample", "best_motif_score_mean",
                "start_ms", "end_ms")
        edges = [e for e in d["network"] if e["window_id"] == window_id and e["team_id"] == team_id and e.get("from_x") is not None and e.get("to_x") is not None]
        nodes: dict[str, dict[str, Any]] = {}
        for e in edges:
            for k in ("from", "to"):
                pid = e[f"{k}_id"]
                nodes.setdefault(pid, {"player_id": pid, "x_m": e[f"{k}_x"], "y_m": e[f"{k}_y"], "passes": 0})
            nodes[e["from_id"]]["passes"] += e["passes"]
        return {
            "match_id": match_id, "team_id": team_id, "window_id": window_id, "label": LABEL.get(window_id, window_id),
            "metrics": {k: _num(row.get(k)) for k in keep},
            "network": {"nodes": list(nodes.values()),
                        "edges": [{"from": e["from_id"], "to": e["to_id"], "passes": e["passes"]} for e in edges]},
            "heatmap": [{"cx": h["cx"], "cy": h["cy"], "samples": h["samples"]} for h in d["heat"] if h["window_id"] == window_id and h["team_id"] == team_id],
            "regains": [{"zx": r["zx"], "zy": r["zy"], "regains": r["regains"]} for r in d["regains"] if r["window_id"] == window_id and r["team_id"] == team_id],
            "definitions": {
                "frame": "team attacks left -> right", "links": "team-mates < 20 m apart (in-possession samples, 0.25 Hz)",
                "lane_clearance": "share of links with no opponent within 2.5 m of the passing lane",
                "motifs": "simple 3/4/5-cycles of the open-link graph per possession sample",
                "viable_motifs": "motifs scoring >= 0.5 on 0.35 lane feasibility + 0.25 progression beyond the ball + "
                                 "0.20 pressure relief + 0.20 persistence (same players in the previous sample)",
                "possession": "ours, from tracking at 5 Hz: a player controls the ball within 1.0 m (ball below 1.8 m, "
                              "0.3 m clear of the nearest opponent); the other team must control it for consecutive samples "
                              "(0.4 s) to take over; dead-ball time excluded",
                "possession_benchmark": "StatsBomb labelled possession (and PFF on-the-ball events) on the same samples; "
                                        "agreement = share of samples where our team matches the label",
                "formation": "detected shape: nearest of 11 templates (Hungarian match, z-scored mean outfield positions "
                             "out of possession)",
                "declared_formation": "StatsBomb Starting XI / Tactical Shift formation in force at the end of the window",
                "network": "StatsBomb completed passes; node = mean action location",
            },
        }

    def timeline(self, match_id: str, at_ms: int) -> list[dict[str, Any]]:
        rows = [r for r in self._load(match_id)["windows"] if r["end_ms"] <= at_ms]
        order = {w: i for i, (w, _) in enumerate(WINDOWS)}
        return sorted(({"window_id": r["window_id"], "label": LABEL.get(r["window_id"]), "team_id": r["team_id"],
                        "start_ms": r["start_ms"], "end_ms": r["end_ms"], "formation": r.get("formation"),
                        "declared_formation": r.get("declared_formation"),
                        "possession_pct": _num(r.get("possession_pct")),
                        "possession_pct_statsbomb": _num(r.get("possession_pct_statsbomb")),
                        "possession_agree_statsbomb_pct": _num(r.get("possession_agree_statsbomb_pct")),
                        "width_in_possession_m": _num(r.get("width_in_possession_m")),
                        "depth_in_possession_m": _num(r.get("depth_in_possession_m"))} for r in rows),
                      key=lambda x: (order.get(x["window_id"], 99), x["team_id"]))

    def _formation_tables(self, match_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The match's whole formation timeline and switches, queried once (one query per clock was seconds each time)."""
        with self._lock:
            if match_id in self._forms:
                self._forms.move_to_end(match_id)
                return self._forms[match_id]
        mid = sql_str(match_id)
        try:
            tl = self.lh.query(f"select team_id, start_ms, end_ms, raw_formation, confidence, formation from t where match_id = {mid} "
                               f"order by start_ms, team_id", {"t": "gold_formation_timeline"}).to_pylist()
            sw = self.lh.query(f"select team_id, at_ms, from_formation, to_formation from t where match_id = {mid} "
                               f"order by at_ms, team_id", {"t": "gold_formation_switches"}).to_pylist()
        except Exception:  # noqa: BLE001 - tables are built by nb_gold_tactical; not cached, they may appear later
            return [], []
        with self._lock:
            self._forms[match_id] = (tl, sw)
            while len(self._forms) > self.max_cached:
                self._forms.popitem(last=False)
        return tl, sw

    def formations(self, match_id: str, at_ms: int) -> dict[str, Any]:
        """Smoothed 60 s formation timeline and switches, only for segments that have ended by at_ms."""
        tl, sw = self._formation_tables(match_id)
        return {"segments": [dict(s) for s in tl if s["end_ms"] <= at_ms],
                "switches": [dict(s) for s in sw if s["at_ms"] + 60_000 <= at_ms],
                "method": "60 s out-of-possession segments, Hungarian template match; a switch needs 2 consecutive confident segments"}

    # ------------------------------------------------------------------ physical
    def physical_index(self, match_id: str) -> list[dict[str, Any]]:
        """Per-player prefix sums (see _index_physical); callers cut at the replay clock."""
        return self._load(match_id)["physical"]

    def physical(self, match_id: str, at_ms: int) -> list[dict[str, Any]]:
        idx = self._load(match_id)["physical"]
        sec = at_ms // 1000
        out = []
        for p in idx:
            k = int(np.searchsorted(p["second"], sec, side="right"))
            if k == 0:
                continue
            frames = int(p["cum_frames"][k - 1])
            out.append({
                "team_id": p["team_id"], "side": p["side"], "jersey": p["jersey_num"], "player_id": p["player_id"],
                "name": p["player_name"], "position_group": p["position_group"],
                "distance_km": round(float(p["cum_dist"][k - 1]) / 1000, 3),
                "hsr_km": round(float(p["cum_hsr"][k - 1]) / 1000, 3),
                "sprint_km": round(float(p["cum_sprint"][k - 1]) / 1000, 3),
                "top_speed_kmh": round(float(p["cum_top"][k - 1]) * 3.6, 1),
                "minutes_tracked": round(k / 60, 1),
                "observed_pct": round(100 * float(p["cum_obs"][k - 1]) / frames, 1) if frames else None,
                "on_pitch": bool(sec - p["second"][k - 1] <= 5),
            })
        return sorted(out, key=lambda r: -r["distance_km"])


def _num(v: Any) -> Any:
    return round(float(v), 2) if isinstance(v, float) else v


def _sustained(sec: np.ndarray, speed: np.ndarray) -> np.ndarray:
    """Speed held over two consecutive seconds; single-second peaks are often camera-cut glitches."""
    out = np.zeros(len(speed))
    if len(speed) > 1:
        out[1:] = np.where(np.diff(sec) == 1, np.minimum(speed[:-1], speed[1:]), 0.0)
    return out


def _index_physical(t) -> list[dict[str, Any]]:
    """Per player: seconds ascending with prefix sums, so 'total up to t' is one binary search."""
    import pyarrow as pa
    import pyarrow.compute as pc

    if t.num_rows == 0:
        return []
    t = t.cast(pa.schema([pa.field(f.name, pa.string()) if pa.types.is_string_view(f.type) else f for f in t.schema]))
    key = pc.binary_join_element_wise(t["team_id"], t["jersey_num"], "|")
    t = t.append_column("_k", key).sort_by([("_k", "ascending"), ("second", "ascending")])
    keys = t["_k"].to_numpy(zero_copy_only=False)
    cuts = np.flatnonzero(keys[1:] != keys[:-1]) + 1
    bounds = np.concatenate([[0], cuts, [len(keys)]])
    col = lambda name, dt=np.float64: np.nan_to_num(t[name].to_numpy(zero_copy_only=False).astype(dt))  # noqa: E731
    sec, dist, avg = col("second", np.int64), col("distance_m"), col("avg_speed_mps")
    frames, obs = col("frames"), col("observed_frames")
    meta = {c: t[c].to_pylist() for c in ("team_id", "side", "jersey_num", "player_id", "player_name", "position_group")}
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        out.append({
            **{c: meta[c][a] for c in meta},
            "second": sec[a:b], "cum_dist": np.cumsum(dist[a:b]),
            "cum_hsr": np.cumsum(np.where(avg[a:b] >= HSR, dist[a:b], 0)),
            "cum_sprint": np.cumsum(np.where(avg[a:b] >= SPRINT, dist[a:b], 0)),
            "cum_top": np.maximum.accumulate(_sustained(sec[a:b], avg[a:b])),
            "cum_frames": np.cumsum(frames[a:b]), "cum_obs": np.cumsum(obs[a:b]),
        })
    return out
