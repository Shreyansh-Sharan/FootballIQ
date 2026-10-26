"""Match sources for the API: LocalStore (silver JSON) or FabricStore (OneLake, LRU and local match packs).

Select with FOOTBALLIQ_SOURCE=fabric|local; the render loop only touches in-memory timelines.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from footballiq import config
from footballiq.replay.timeline import MatchTimeline
from footballiq.replay.tracking import TrackedPlayer, TrackingTimeline
from footballiq.schema import FreezeFrame, FreezeFramePlayer, Match, MatchEvent

log = logging.getLogger(__name__)
PACK_FORMAT = 1   # bump when the timeline classes change shape; old packs rebuild


# --------------------------------------------------------------------------- local


def load_timeline(match_dir: Path) -> MatchTimeline:
    match = Match.model_validate_json((match_dir / "match.json").read_text())
    with (match_dir / "events.jsonl").open() as fh:
        events = [MatchEvent.model_validate_json(line) for line in fh if line.strip()]
    frames: list[FreezeFrame] = []
    ff_path = match_dir / "freeze_frames.jsonl"
    if ff_path.exists():
        with ff_path.open() as fh:
            frames = [FreezeFrame.model_validate(json.loads(line)) for line in fh if line.strip()]
    return MatchTimeline(match, events, frames)


class LocalStore:
    source = "local"

    def __init__(self, silver: Path | None = None):
        self.silver = silver or config.silver_dir()
        self._cache: dict[str, MatchTimeline] = {}

    def match_ids(self) -> list[str]:
        if not self.silver.exists():
            return []
        return sorted(p.name for p in self.silver.iterdir() if (p / "match.json").exists())

    def summaries(self) -> list[dict[str, Any]]:
        out = []
        for mid in self.match_ids():
            tl = self.get(mid)
            out.append(summary_of(tl.match, len(tl.events), len(tl.frames), tracking=None))
        return out

    def get(self, match_id: str) -> MatchTimeline | None:
        if match_id not in self._cache:
            path = self.silver / match_id
            if not (path / "match.json").exists():
                return None
            self._cache[match_id] = load_timeline(path)
        return self._cache[match_id]

    def status(self) -> dict[str, Any]:
        return {"source": self.source, "matches": len(self.match_ids())}

    def all_matches(self) -> list[Match]:
        return [self.get(mid).match for mid in self.match_ids()]


MatchStore = LocalStore  # backwards-compatible name


def summary_of(match: Match, n_events: int | None, n_360: int | None, tracking: dict | None) -> dict[str, Any]:
    return {
        "match_id": match.canonical_match_id,
        "competition": match.competition,
        "season": match.season,
        "stage": match.stage,
        "date": match.kickoff_source[:10],
        "home": match.home.model_dump(),
        "away": match.away.model_dump(),
        "completeness": {
            "events": n_events,
            "event_snapshots_360": n_360,
            "continuous_tracking": bool(tracking),
            "tracking": tracking,
        },
    }


# --------------------------------------------------------------------------- fabric

MATCH_JSON_COLS = ("home", "away", "periods", "players", "result", "source_ids")


def _match_from_row(row: dict[str, Any]) -> Match:
    data = {k: v for k, v in row.items() if k not in ("ingested_at_utc", "statsbomb_match_id", "provider")}
    for k in MATCH_JSON_COLS:
        if isinstance(data.get(k), str):
            data[k] = json.loads(data[k])
    return Match.model_validate(data)


def _event_from_row(row: dict[str, Any]) -> MatchEvent:
    data = {k: v for k, v in row.items() if k != "ingested_at_utc"}
    for k, default in (("related_events", []), ("source_location", None)):
        v = data.get(k)
        data[k] = json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    data["related_events"] = data["related_events"] or []
    return MatchEvent.model_validate(data)


class FabricStore:
    source = "fabric"

    def __init__(self, lakehouse=None, max_cached: int | None = None):
        from footballiq.fabric_source import FabricLakehouse

        self.lh = lakehouse or FabricLakehouse()
        self.max_cached = max_cached or int(os.environ.get("FOOTBALLIQ_CACHE_MATCHES", "4"))
        self._cache: OrderedDict[str, MatchTimeline] = OrderedDict()
        self._lock = threading.Lock()
        self._loading: dict[str, threading.Event] = {}
        self._summaries: list[dict[str, Any]] | None = None
        self._matches: dict[str, Match] = {}
        self._tracking_index: dict[str, dict[str, Any]] = {}
        self._catalogue_lock = threading.Lock()
        self._pinned: set[str] = set()

    def pin(self, match_id: str) -> None:
        """Keep a match in memory for the life of the process."""
        self._pinned.add(match_id)

    # -- catalogue --------------------------------------------------------------------
    # local snapshot first, OneLake refresh in the background (~20 s); one builder thread at a time
    def _snapshot_path(self) -> Path | None:
        d = getattr(self.lh, "cache_dir", None)
        return Path(d) / "catalogue_snapshot.json" if d else None

    def _load_catalogue(self) -> None:
        if self._summaries is not None:
            return
        with self._catalogue_lock:
            if self._summaries is not None:
                return
            if self._read_snapshot():
                threading.Thread(target=self._refresh_catalogue, daemon=True, name="catalogue-refresh").start()
                return
            self._refresh_catalogue(raise_errors=True)

    def _refresh_catalogue(self, raise_errors: bool = False) -> None:
        t0 = time.time()
        try:
            matches, index, summaries = self._query_catalogue()
        except Exception:
            if raise_errors:
                raise
            log.exception("catalogue refresh failed; still serving the snapshot")
            return
        # swap whole dicts so readers never see a mix
        self._matches, self._tracking_index = matches, index
        self._summaries = summaries
        self._write_snapshot()
        log.info("Fabric catalogue: %d matches in %.1fs", len(matches), time.time() - t0)

    def _query_catalogue(self) -> tuple[dict[str, Match], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from concurrent.futures import ThreadPoolExecutor

        def std_rows() -> list[dict[str, Any]]:
            try:
                return self.lh.query("select * from t", {"t": "silver_tracking_match_std"}).to_pylist()
            except Exception:  # noqa: BLE001 - table not created until a non-PFF provider is ingested
                return []

        with ThreadPoolExecutor(max_workers=4) as pool:   # the Delta log reads dominate; do them together
            f_rows = pool.submit(lambda: self.lh.query("select * from m", {"m": "silver_match"}).to_pylist())
            f_counts = pool.submit(lambda: self.lh.query(
                "select match_id, count(*) as events, sum(case when has_freeze_frame then 1 else 0 end) as n360 "
                "from e group by match_id", {"e": "silver_match_event"}).to_pylist())
            f_trk = pool.submit(lambda: self.lh.query(
                "select p.match_id, p.pff_game_id, count(*) as periods, sum(p.frames) as frames, "
                "min(case when p.direction_agrees_with_metadata then 1 else 0 end) as dir_ok "
                "from p group by p.match_id, p.pff_game_id", {"p": "silver_tracking_period"}).to_pylist())
            f_std = pool.submit(std_rows)
            rows, counts, trk, std = f_rows.result(), f_counts.result(), f_trk.result(), f_std.result()
        matches = {r["canonical_match_id"]: _match_from_row(r) for r in rows}
        counts = {r["match_id"]: r for r in counts}
        index = {r["match_id"]: {"provider": "pff_fc", "method": "broadcast_cv", "pff_game_id": r["pff_game_id"],
                                 "periods": r["periods"], "frames": r["frames"],
                                 "direction_agrees_with_metadata": bool(r["dir_ok"])}
                 for r in trk}
        # non-PFF providers from the common spatial schema
        for r in std:
            if r["source_provider"] != "pff_fc":
                index[r["match_id"]] = {"provider": r["source_provider"], "method": r["tracking_method"],
                                        "periods": r["periods"], "frames": r["frames"], "hz": r["frame_rate"],
                                        "coverage_mean": r.get("coverage_mean")}
        summaries = sorted(
            (summary_of(m, counts.get(mid, {}).get("events"), counts.get(mid, {}).get("n360"), index.get(mid))
             for mid, m in matches.items()),
            key=lambda s: (s["date"], s["match_id"]))
        return matches, index, summaries

    def _read_snapshot(self) -> bool:
        path = self._snapshot_path()
        if path is None or not path.exists():
            return False
        try:
            snap = json.loads(path.read_text())
            if snap.get("lakehouse_id") != getattr(self.lh, "lakehouse_id", None):
                return False
            self._matches = {k: Match.model_validate(v) for k, v in snap["matches"].items()}
            self._tracking_index = snap["tracking_index"]
            self._summaries = snap["summaries"]
        except Exception:  # noqa: BLE001 - a corrupt snapshot just means a normal (slow) load
            log.warning("ignoring unreadable catalogue snapshot %s", path)
            self._matches, self._tracking_index, self._summaries = {}, {}, None
            return False
        log.info("Fabric catalogue: %d matches from snapshot (refreshing in the background)", len(self._matches))
        return True

    def _write_snapshot(self) -> None:
        path = self._snapshot_path()
        if path is None:
            return
        snap = {"lakehouse_id": getattr(self.lh, "lakehouse_id", None), "written_at": time.time(),
                "matches": {k: m.model_dump(mode="json") for k, m in self._matches.items()},
                "tracking_index": self._tracking_index, "summaries": self._summaries}
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap, default=str))
            tmp.replace(path)
        except OSError:
            log.warning("could not write catalogue snapshot %s", path)

    def match_ids(self) -> list[str]:
        self._load_catalogue()
        return [s["match_id"] for s in self._summaries]

    def summaries(self) -> list[dict[str, Any]]:
        self._load_catalogue()
        return self._summaries

    def all_matches(self) -> list[Match]:
        self._load_catalogue()
        return list(self._matches.values())

    def status(self) -> dict[str, Any]:
        return {"source": self.source, "workspace_id": self.lh.workspace_id, "lakehouse_id": self.lh.lakehouse_id,
                "matches": len(self._matches) if self._summaries is not None else None,
                "cached": list(self._cache)}

    # -- per match --------------------------------------------------------------------
    def get(self, match_id: str) -> MatchTimeline | None:
        self._load_catalogue()
        if match_id not in self._matches:
            return None
        with self._lock:
            if match_id in self._cache:
                self._cache.move_to_end(match_id)
                return self._cache[match_id]
            waiter = self._loading.get(match_id)
            owner = waiter is None
            if owner:
                waiter = self._loading[match_id] = threading.Event()
        if not owner:
            waiter.wait()
            return self._cache.get(match_id)
        try:
            tl = self._load_match(match_id)
            self._put(match_id, tl)
            return tl
        finally:
            waiter.set()
            self._loading.pop(match_id, None)

    def _put(self, match_id: str, tl: MatchTimeline) -> None:
        with self._lock:
            self._cache[match_id] = tl
            self._cache.move_to_end(match_id)
            for old in [k for k in self._cache if k not in self._pinned and k != match_id]:
                if len(self._cache) <= self.max_cached:
                    break
                self._cache.pop(old)

    # -- match packs ------------------------------------------------------------------
    def _pack_path(self, match_id: str) -> Path | None:
        d = getattr(self.lh, "cache_dir", None)
        return Path(d) / "packs" / f"{match_id.replace('/', '_')}.pkl" if d else None

    def _source_tables(self, match_id: str) -> list[str]:
        idx = self._tracking_index.get(match_id)
        tables = ["silver_match_event", "silver_freeze_frame"]
        if idx is not None:
            tables += (["silver_tracking_frame", "silver_player_position", "silver_pff_roster"] if idx["provider"] == "pff_fc"
                       else ["silver_tracking_frame_std", "silver_player_position_std"])
        return tables

    def _read_pack(self, match_id: str) -> dict[str, Any] | None:
        path = self._pack_path(match_id)
        if path is None or not path.exists():
            return None
        try:
            with path.open("rb") as fh:
                pack = pickle.load(fh)  # written by this process, never downloaded
        except Exception:  # corrupt or incompatible: rebuild from OneLake
            log.warning("match pack %s unreadable; rebuilding", path, exc_info=True)
            return None
        if pack.get("format") != PACK_FORMAT or pack.get("lakehouse_id") != getattr(self.lh, "lakehouse_id", None):
            return None
        return pack

    def _write_pack(self, match_id: str, tl: MatchTimeline, versions: dict[str, int] | None) -> None:
        path = self._pack_path(match_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        with tmp.open("wb") as fh:
            pickle.dump({"format": PACK_FORMAT, "lakehouse_id": getattr(self.lh, "lakehouse_id", None),
                         "versions": versions, "built_at": time.time(), "timeline": tl}, fh, protocol=5)
        tmp.replace(path)

    def _refresh_pack(self, match_id: str, versions: dict[str, int] | None, built: MatchTimeline | None = None) -> None:
        """Background: rebuild the pack when any source table has a newer Delta version than the pack."""
        try:
            now = {t: self.lh.version(t) for t in self._source_tables(match_id)}
            if versions is None:                      # just built (or versions never recorded): record them
                if built is not None:
                    self._write_pack(match_id, built, now)
                return
            if now == versions:
                return
            log.info("match pack %s is stale (%s -> %s); rebuilding", match_id, versions, now)
            tl = self._build_match(match_id, fresh=True)
            self._put(match_id, tl)
            self._write_pack(match_id, tl, now)
        except Exception:  # keep serving the pack; the next start tries again
            log.warning("match pack refresh failed for %s", match_id, exc_info=True)

    def _load_match(self, match_id: str) -> MatchTimeline:
        t0 = time.time()
        pack = self._read_pack(match_id)
        if pack is not None:
            log.info("loaded %s from its match pack in %.1fs", match_id, time.time() - t0)
            if hasattr(self.lh, "version"):
                threading.Thread(target=self._refresh_pack, args=(match_id, pack["versions"], pack["timeline"]), daemon=True,
                                 name=f"pack-refresh-{match_id}").start()
            return pack["timeline"]
        tl = self._build_match(match_id)
        try:
            self._write_pack(match_id, tl, None)
            if hasattr(self.lh, "version"):
                threading.Thread(target=self._refresh_pack, args=(match_id, None, tl), daemon=True).start()
        except OSError:
            log.warning("could not write the match pack for %s", match_id, exc_info=True)
        return tl

    def _build_match(self, match_id: str, fresh: bool = False) -> MatchTimeline:
        from footballiq.fabric_source import sql_str

        q = (lambda sql, tables: self.lh.query(sql, tables, fresh=True)) if fresh else self.lh.query
        t0 = time.time()
        mid = sql_str(match_id)
        match = self._matches[match_id]
        events = [_event_from_row(r) for r in q(
            f"select * from e where match_id = {mid}", {"e": "silver_match_event"}).to_pylist()]
        frames = []
        for r in q(f"select event_id, match_elapsed_ms, players, visible_area, source from f "
                               f"where match_id = {mid}", {"f": "silver_freeze_frame"}).to_pylist():
            frames.append(FreezeFrame(
                event_id=r["event_id"], match_elapsed_ms=r["match_elapsed_ms"], source=r["source"] or "statsbomb_360",
                players=[FreezeFramePlayer(**p) for p in json.loads(r["players"] or "[]")],
                visible_area=json.loads(r["visible_area"] or "[]")))
        idx = self._tracking_index.get(match_id)
        tracking = None if idx is None else self._load_tracking(match_id, q) if idx["provider"] == "pff_fc" else self._load_tracking_std(match_id, q)
        log.info("loaded %s: %d events, %d 360, tracking=%s in %.1fs", match_id, len(events), len(frames),
                 tracking.n_frames if tracking else None, time.time() - t0)
        return MatchTimeline(match, events, frames, tracking=tracking)

    def _load_tracking(self, match_id: str, q=None) -> TrackingTimeline:
        q = q or self.lh.query
        import pyarrow as pa
        import pyarrow.compute as pc

        gid = int(self._tracking_index[match_id]["pff_game_id"])
        fr = q(
            "select frame_num, match_elapsed_ms as t, period, coalesce(ball_x_smooth_m, ball_x_m) as ball_x, "
            "coalesce(ball_y_smooth_m, ball_y_m) as ball_y, ball_z_m as ball_z, ball_observed "
            f"from f where pff_game_id = {gid}", {"f": "silver_tracking_frame"})
        pos = q(
            "select frame_num, team_id, side, jersey_num, coalesce(x_smooth_m, x_m) as x, coalesce(y_smooth_m, y_m) as y, "
            f"observed from p where pff_game_id = {gid}", {"p": "silver_player_position"})
        roster = {(r["team_id"], r["jersey_num"]): r for r in q(
            "select team_id, jersey_num, player_id, player_name, position_group, started from r "
            f"where pff_game_id = {gid}", {"r": "silver_pff_roster"}).to_pylist()}

        def s(c):  # DataFusion returns string_view; compute kernels want plain strings
            return pc.cast(pos[c], pa.string())

        key = pc.binary_join_element_wise(s("side"), s("team_id"), s("jersey_num"), "|")
        enc = pc.dictionary_encode(key).combine_chunks()
        players = []
        for i, k in enumerate(enc.dictionary.to_pylist()):
            side, team_id, jersey = k.split("|")
            r = roster.get((team_id, jersey), {})
            players.append(TrackedPlayer(idx=i, team_id=team_id, side=side, jersey_num=jersey,
                                         player_id=r.get("player_id"), name=r.get("player_name"),
                                         position_group=r.get("position_group"), started=r.get("started")))

        def col(t, name, dtype=None, fill=np.nan):
            a = t[name].to_numpy(zero_copy_only=False)
            if dtype is not None:
                a = np.where(a == None, fill, a).astype(dtype) if a.dtype == object else a.astype(dtype)  # noqa: E711
            return a

        frames = {"frame_num": col(fr, "frame_num", np.int64), "t": col(fr, "t", np.int64),
                  "period": col(fr, "period", np.int8), "ball_x": col(fr, "ball_x", np.float32),
                  "ball_y": col(fr, "ball_y", np.float32), "ball_z": col(fr, "ball_z", np.float32),
                  "ball_observed": col(fr, "ball_observed", bool, False)}
        positions = {"frame_num": col(pos, "frame_num", np.int64), "player_idx": enc.indices.to_numpy().astype(np.int16),
                     "x": col(pos, "x", np.float32), "y": col(pos, "y", np.float32),
                     "observed": col(pos, "observed", bool, False)}
        return TrackingTimeline.from_columns(match_id, "pff_fc", frames, positions, players)

    def _load_tracking_std(self, match_id: str, q=None) -> TrackingTimeline:
        """Tracking from the common spatial schema (any provider). Unknown observation state -> not observed."""
        q = q or self.lh.query
        import pyarrow as pa
        import pyarrow.compute as pc

        from footballiq.fabric_source import sql_str

        mid = sql_str(match_id)
        fr = q("select frame_num, match_elapsed_ms as t, period, ball_x_m as ball_x, ball_y_m as ball_y, "
                           f"ball_z_m as ball_z, ball_is_observed as ball_observed from f where match_id = {mid}",
                           {"f": "silver_tracking_frame_std"})
        pos = q("select frame_num, team_id, side, jersey_num, player_id, x_m as x, y_m as y, is_observed as observed "
                            f"from p where match_id = {mid} and x_m is not null", {"p": "silver_player_position_std"})
        m = self._matches.get(match_id)
        names = {p.player_id: p for p in (m.players if m else [])}

        def s(c):
            return pc.cast(pos[c], pa.string())

        key = pc.binary_join_element_wise(s("side"), s("team_id"), s("jersey_num"), pc.fill_null(s("player_id"), ""), "|")
        enc = pc.dictionary_encode(key).combine_chunks()
        players = []
        for i, k in enumerate(enc.dictionary.to_pylist()):
            side, team_id, jersey, pid = k.split("|")
            pl = names.get(pid)
            players.append(TrackedPlayer(idx=i, team_id=team_id, side=side, jersey_num=jersey, player_id=pid or None,
                                         name=pl.name if pl else None, position_group=None, started=pl.starter if pl else None))

        def col(t, name, dtype, fill=np.nan):
            a = t[name].to_numpy(zero_copy_only=False)
            return np.where(a == None, fill, a).astype(dtype) if a.dtype == object else a.astype(dtype)  # noqa: E711

        frames = {"frame_num": col(fr, "frame_num", np.int64), "t": col(fr, "t", np.int64), "period": col(fr, "period", np.int8),
                  "ball_x": col(fr, "ball_x", np.float32), "ball_y": col(fr, "ball_y", np.float32),
                  "ball_z": col(fr, "ball_z", np.float32), "ball_observed": col(fr, "ball_observed", bool, False)}
        positions = {"frame_num": col(pos, "frame_num", np.int64), "player_idx": enc.indices.to_numpy().astype(np.int16),
                     "x": col(pos, "x", np.float32), "y": col(pos, "y", np.float32),
                     "observed": col(pos, "observed", bool, False)}
        return TrackingTimeline.from_columns(match_id, self._tracking_index[match_id]["provider"], frames, positions, players)


# --------------------------------------------------------------------------- factory


def make_store() -> LocalStore | FabricStore:
    source = os.environ.get("FOOTBALLIQ_SOURCE") or ("fabric" if os.environ.get("FABRIC_CLIENT_ID") else "local")
    return FabricStore() if source == "fabric" else LocalStore()


@lru_cache(maxsize=1)
def default_store() -> LocalStore | FabricStore:
    return make_store()
