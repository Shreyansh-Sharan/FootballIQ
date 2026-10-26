"""Read-only access to the Fabric lakehouse (OneLake Delta tables) for the API.

Queries run on delta-rs QueryBuilder, which handles deletion vectors; results are cached on disk as Arrow files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pyarrow as pa
from pyarrow import ipc

from footballiq import config

log = logging.getLogger(__name__)
API = "https://api.fabric.microsoft.com/v1"
VERSION_TTL_S = 300          # seconds a looked-up Delta version is trusted


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


class FabricLakehouse:
    def __init__(self) -> None:
        missing = [n for n in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET") if not _env(n)]
        if missing:
            raise RuntimeError(f"Fabric source needs {', '.join(missing)} (see .env.example)")
        self.storage_options = {
            "azure_tenant_id": _env("FABRIC_TENANT_ID"),
            "azure_client_id": _env("FABRIC_CLIENT_ID"),
            "azure_client_secret": _env("FABRIC_CLIENT_SECRET"),
            "use_fabric_endpoint": "true",
        }
        self.workspace_id = _env("FABRIC_WORKSPACE_ID") or None
        self.lakehouse_id = _env("FABRIC_LAKEHOUSE_ID") or None
        self.cache_dir = Path(_env("FOOTBALLIQ_CACHE_DIR", str(config.data_dir() / "cache" / "fabric")))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ids_path, names = self.cache_dir / "ids.json", f"{_env('FABRIC_WORKSPACE_NAME', '')}|{_env('FABRIC_LAKEHOUSE_NAME', '')}"
        if not (self.workspace_id and self.lakehouse_id):   # reuse ids resolved on an earlier start
            try:
                known = json.loads(ids_path.read_text()).get(names) or {}
                self.workspace_id = self.workspace_id or known.get("workspace_id")
                self.lakehouse_id = self.lakehouse_id or known.get("lakehouse_id")
            except (OSError, ValueError):
                pass
        if not (self.workspace_id and self.lakehouse_id):
            for attempt in range(5):   # survive transient network resets at startup
                try:
                    self._resolve_ids()
                    break
                except httpx.TransportError as e:
                    if attempt == 4:
                        raise
                    log.warning("Fabric id lookup failed (%s); retrying in %ss", e, 2 ** attempt)
                    time.sleep(2 ** attempt)
            ids_path.write_text(json.dumps({names: {"workspace_id": self.workspace_id, "lakehouse_id": self.lakehouse_id}}))
        self._lock = threading.Lock()
        self._init_cache_state()

    def _init_cache_state(self) -> None:
        self._index_lock = threading.Lock()
        self._index_path = self.cache_dir / "index.json"
        try:
            self._index: dict[str, str] = json.loads(self._index_path.read_text())
        except (OSError, ValueError):
            self._index = {}
        self._versions: dict[str, tuple[int, float]] = {}       # table -> (version, looked up at)
        self._revalidating: set[str] = set()
        self._bg = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lh-revalidate")
        self.stale_ok = os.environ.get("FOOTBALLIQ_CACHE_STRICT") != "1"

    def _token(self) -> str:
        r = httpx.post(
            f"https://login.microsoftonline.com/{_env('FABRIC_TENANT_ID')}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": _env("FABRIC_CLIENT_ID"),
                  "client_secret": _env("FABRIC_CLIENT_SECRET"), "scope": "https://api.fabric.microsoft.com/.default"},
            timeout=30)
        r.raise_for_status()
        return r.json()["access_token"]

    def _resolve_ids(self) -> None:
        ws_name = _env("FABRIC_WORKSPACE_NAME", "Football Analytics Shreyansh")
        lh_name = _env("FABRIC_LAKEHOUSE_NAME", "lh_football_intelligence")
        with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {self._token()}"}, timeout=60) as c:
            if not self.workspace_id:
                ws = next((w for w in c.get("/workspaces").json()["value"] if w["displayName"] == ws_name), None)
                if ws is None:
                    raise RuntimeError(f"workspace {ws_name!r} not visible to the service principal")
                self.workspace_id = ws["id"]
            if not self.lakehouse_id:
                lhs = c.get(f"/workspaces/{self.workspace_id}/lakehouses").json()["value"]
                lh = next((x for x in lhs if x["displayName"] == lh_name), None)
                if lh is None:
                    raise RuntimeError(f"lakehouse {lh_name!r} not found in workspace {self.workspace_id}")
                self.lakehouse_id = lh["id"]
        log.info("Fabric source: workspace %s lakehouse %s", self.workspace_id, self.lakehouse_id)

    def table_uri(self, table: str) -> str:
        return f"abfss://{self.workspace_id}@onelake.dfs.fabric.microsoft.com/{self.lakehouse_id}/Tables/{table}"

    def query(self, sql: str, tables: dict[str, str], cache: bool = True, fresh: bool = False) -> pa.Table:
        """Run SQL over Delta tables ({alias: table_name}), cached by SQL and table versions.

        Unless ``fresh`` or FOOTBALLIQ_CACHE_STRICT=1, a cached result returns at once and is revalidated in the background."""
        base = self._base_key(sql, tables)
        if cache and not fresh and self.stale_ok:
            path = self._indexed(base)
            if path is not None:
                self._revalidate(base, sql, tables)
                return self._read(path)
        return self._versioned(sql, tables, cache, max_age=0 if fresh or not self.stale_ok else VERSION_TTL_S)

    def _versioned(self, sql: str, tables: dict[str, str], cache: bool, max_age: float) -> pa.Table:
        versions = sorted((t, self.version(t, max_age)) for t in tables.values())
        key = hashlib.sha256(json.dumps([sql, versions, self.lakehouse_id]).encode()).hexdigest()[:24]
        path = self.cache_dir / f"{key}.arrow"
        base = self._base_key(sql, tables)
        if cache and path.exists():
            self._remember(base, key)
            return self._read(path)
        result = self._execute(sql, tables)
        if cache:
            tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
            # own the sink: a path-opened file stays open on Windows and the rename fails
            with pa.OSFile(str(tmp), "wb") as sink, ipc.new_file(sink, result.schema) as w:
                w.write_table(result)
            tmp.replace(path)
            self._remember(base, key)
        return result

    def version(self, table: str, max_age: float = VERSION_TTL_S) -> int:
        """Current Delta version of a table, memoised for ``max_age`` seconds."""
        hit = self._versions.get(table)
        if hit is not None and time.time() - hit[1] < max_age:
            return hit[0]
        from deltalake import DeltaTable

        v = DeltaTable(self.table_uri(table), storage_options=self.storage_options).version()
        self._versions[table] = (v, time.time())
        return v

    def _execute(self, sql: str, tables: dict[str, str]) -> pa.Table:
        from deltalake import DeltaTable, QueryBuilder

        dts = {alias: DeltaTable(self.table_uri(table), storage_options=self.storage_options) for alias, table in tables.items()}
        with self._lock:  # one OneLake scan at a time keeps memory predictable
            qb = QueryBuilder()
            for alias, dt in dts.items():
                qb.register(alias, dt)
            return pa.table(qb.execute(sql).read_all())

    def _base_key(self, sql: str, tables: dict[str, str]) -> str:
        return hashlib.sha256(json.dumps([sql, sorted(tables.items()), self.lakehouse_id]).encode()).hexdigest()[:24]

    def _indexed(self, base: str) -> Path | None:
        key = self._index.get(base)
        path = self.cache_dir / f"{key}.arrow" if key else None
        return path if path is not None and path.exists() else None

    def _remember(self, base: str, key: str) -> None:
        with self._index_lock:
            if self._index.get(base) == key:
                return
            self._index[base] = key
            tmp = self._index_path.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(self._index))
            tmp.replace(self._index_path)

    def _revalidate(self, base: str, sql: str, tables: dict[str, str]) -> None:
        with self._index_lock:
            if base in self._revalidating:
                return
            self._revalidating.add(base)

        def run() -> None:
            try:
                self._versioned(sql, tables, True, VERSION_TTL_S)
            except Exception:  # the stale result stays in use; the next request tries again
                log.warning("background refresh failed for %s", list(tables.values()), exc_info=True)
            finally:
                with self._index_lock:
                    self._revalidating.discard(base)

        self._bg.submit(run)

    @staticmethod
    def _read(path: Path) -> pa.Table:
        # no memory map: Windows locks a mapped file, so a refreshed result could not replace it
        with pa.OSFile(str(path), "rb") as src, ipc.open_file(src) as f:
            return f.read_all()


def sql_str(value: str) -> str:
    """Quote a DataFusion SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"
