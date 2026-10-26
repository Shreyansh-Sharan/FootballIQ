"""Fabric catalogue: one loader, served from a local snapshot after a restart, refreshed in the background."""
import json
import threading
import time

import pyarrow as pa

from footballiq.ingest.statsbomb import normalize_match
from footballiq.store import MATCH_JSON_COLS, FabricStore


class FakeLakehouse:
    lakehouse_id = "lh-1"

    def __init__(self, cache_dir, match_row, gate: threading.Event | None = None, fail: bool = False):
        self.cache_dir, self.gate, self.fail, self.calls = cache_dir, gate, fail, 0
        self.lock = threading.Lock()
        self.t = {
            "silver_match": pa.Table.from_pylist([match_row]),
            "silver_match_event": pa.table({"match_id": [match_row["canonical_match_id"]], "events": [10], "n360": [2]}),
            "silver_tracking_period": pa.table({"match_id": pa.array([], pa.string()), "pff_game_id": pa.array([], pa.int64()),
                                                "periods": pa.array([], pa.int64()), "frames": pa.array([], pa.int64()),
                                                "dir_ok": pa.array([], pa.int64())}),
        }

    def query(self, sql, tables):
        with self.lock:
            self.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise ConnectionError("onelake unreachable")
        name = next(iter(tables.values()))
        if name not in self.t:
            raise KeyError(name)  # silver_tracking_match_std not created yet
        return self.t[name]


def _row(raw_match):
    match, _, _ = normalize_match(raw_match, 99)
    row = match.model_dump(mode="json")
    for k in MATCH_JSON_COLS:
        row[k] = json.dumps(row[k])
    return row


def test_cold_load_writes_snapshot_and_restart_serves_it_without_waiting(tmp_path, raw_match):
    row = _row(raw_match)
    first = FabricStore(lakehouse=FakeLakehouse(tmp_path, row))
    assert [s["completeness"]["events"] for s in first.summaries()] == [10]
    assert (tmp_path / "catalogue_snapshot.json").exists()

    gate = threading.Event()     # OneLake "hangs": the restarted store must answer from the snapshot anyway
    lh = FakeLakehouse(tmp_path, row, gate=gate)
    second = FabricStore(lakehouse=lh)
    t0 = time.monotonic()
    assert second.match_ids() == first.match_ids()
    assert time.monotonic() - t0 < 1.0
    assert second.all_matches()[0].canonical_match_id == row["canonical_match_id"]
    gate.set()


def test_refresh_failure_keeps_serving_the_snapshot(tmp_path, raw_match):
    row = _row(raw_match)
    FabricStore(lakehouse=FakeLakehouse(tmp_path, row)).summaries()
    store = FabricStore(lakehouse=FakeLakehouse(tmp_path, row, fail=True))
    assert len(store.summaries()) == 1


def test_concurrent_callers_share_one_load(tmp_path, raw_match):
    lh = FakeLakehouse(tmp_path, _row(raw_match))
    store = FabricStore(lakehouse=lh)
    threads = [threading.Thread(target=store.summaries) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert lh.calls == 4          # four catalogue queries, once - not once per caller


def test_snapshot_from_another_lakehouse_is_ignored(tmp_path, raw_match):
    row = _row(raw_match)
    FabricStore(lakehouse=FakeLakehouse(tmp_path, row)).summaries()
    other = FakeLakehouse(tmp_path, row)
    other.lakehouse_id = "lh-2"
    store = FabricStore(lakehouse=other)
    store.summaries()
    assert other.calls == 4       # loaded from "OneLake", not from lh-1's snapshot
