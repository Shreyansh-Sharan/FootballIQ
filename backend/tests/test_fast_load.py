"""Fast restarts: cached queries, match packs and pinning answer without waiting for OneLake."""
import threading
import time

import pyarrow as pa

from footballiq.fabric_source import FabricLakehouse
from footballiq.store import FabricStore


def _lakehouse(cache_dir, versions, executed):
    lh = object.__new__(FabricLakehouse)          # no network: ids, versions and scans are faked below
    lh.lakehouse_id, lh.workspace_id, lh.cache_dir = "lh-1", "ws-1", cache_dir
    lh._lock = threading.Lock()
    lh._init_cache_state()
    lh.version = lambda table, max_age=0: versions[table]

    def execute(sql, tables):
        executed.append(sql)
        return pa.table({"v": [versions["t"]]})

    lh._execute = execute
    return lh


def _wait_idle(lh):
    lh._bg.submit(lambda: None).result(5)
    for _ in range(100):
        if not lh._revalidating:
            return
        time.sleep(0.02)


def test_cached_query_is_served_from_disk_and_refreshed_in_the_background(tmp_path):
    versions, executed = {"t": 1}, []
    lh = _lakehouse(tmp_path, versions, executed)
    assert lh.query("select v", {"x": "t"})["v"].to_pylist() == [1] and len(executed) == 1

    gate = threading.Event()                      # after a restart OneLake is slow: the answer must not wait
    lh2 = _lakehouse(tmp_path, versions, executed)
    lh2.version = lambda table, max_age=0: (gate.wait(5), versions[table])[1]
    t0 = time.monotonic()
    assert lh2.query("select v", {"x": "t"})["v"].to_pylist() == [1]
    assert time.monotonic() - t0 < 1.0
    gate.set()
    _wait_idle(lh2)
    assert len(executed) == 1                     # unchanged table: nothing recomputed

    versions["t"] = 2                             # a notebook rewrote the table
    lh3 = _lakehouse(tmp_path, versions, executed)
    assert lh3.query("select v", {"x": "t"})["v"].to_pylist() == [1]   # stale answer first...
    _wait_idle(lh3)
    assert lh3.query("select v", {"x": "t"})["v"].to_pylist() == [2]   # ...then the refreshed one
    assert lh3.query("select v", {"x": "t"}, fresh=True)["v"].to_pylist() == [2]


class _PackLakehouse:
    lakehouse_id = "lh-1"

    def __init__(self, cache_dir, versions):
        self.cache_dir, self.versions = cache_dir, versions

    def version(self, table, max_age=0):
        return self.versions.get(table, 1)


def _store(tmp_path, timeline, versions, builds, max_cached=4):
    st = FabricStore(lakehouse=_PackLakehouse(tmp_path, versions), max_cached=max_cached)
    st._summaries, st._matches, st._tracking_index = [], {timeline.match.canonical_match_id: timeline.match}, {}

    def build(match_id, fresh=False):
        builds.append((match_id, fresh))
        return timeline

    st._build_match = build
    return st


def test_match_pack_makes_a_restart_instant_and_is_rebuilt_when_a_table_changes(tmp_path, timeline):
    mid, versions, builds = timeline.match.canonical_match_id, {"silver_match_event": 1}, []
    first = _store(tmp_path, timeline, versions, builds)
    assert first.get(mid) is timeline and builds == [(mid, False)]
    assert (tmp_path / "packs" / f"{mid}.pkl").exists()

    second = _store(tmp_path, timeline, versions, builds)
    tl = second.get(mid)
    assert tl.match.canonical_match_id == mid and len(tl.events) == len(timeline.events)
    assert builds == [(mid, False)]               # served from the pack, OneLake untouched

    pack = second._read_pack(mid)
    second._refresh_pack(mid, pack["versions"] or {"silver_match_event": 1, "silver_freeze_frame": 1})
    assert builds == [(mid, False)]               # same versions: nothing rebuilt
    versions["silver_match_event"] = 2
    second._refresh_pack(mid, {"silver_match_event": 1, "silver_freeze_frame": 1})
    assert builds[-1] == (mid, True)              # a newer table version rebuilds from fresh queries
    assert second._read_pack(mid)["versions"]["silver_match_event"] == 2


def test_pinned_match_survives_eviction(tmp_path, timeline):
    st = _store(tmp_path, timeline, {}, [], max_cached=1)
    st.pin("keep")
    st._put("keep", timeline)
    st._put("other-1", timeline)
    st._put("other-2", timeline)
    assert "keep" in st._cache and "other-2" in st._cache and "other-1" not in st._cache
